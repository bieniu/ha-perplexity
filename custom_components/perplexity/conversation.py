"""Conversation support for Perplexity with custom action parsing.

Since the Perplexity API does not support native function calling / tool use,
this implementation uses a structured JSON response format to parse actions
from the LLM response and execute them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LLM_HASS_API, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PerplexityConfigEntry
from .const import CONF_PROMPT, DOMAIN, LOGGER
from .entity import PerplexityEntity

# JSON schema for structured action response
ACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "assistant_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "The text response to show to the user",
                },
                "actions": {
                    "type": ["array", "null"],
                    "description": "List of Home Assistant actions to execute",
                    "items": {
                        "type": "object",
                        "properties": {
                            "domain": {
                                "type": "string",
                                "description": (
                                    "The domain of the service "
                                    "(e.g., light, switch, climate)"
                                ),
                            },
                            "service": {
                                "type": "string",
                                "description": (
                                    "The service to call (e.g., turn_on, turn_off)"
                                ),
                            },
                            "target": {
                                "type": "string",
                                "description": "The entity_id to target",
                            },
                            "data": {
                                "type": ["object", "null"],
                                "description": "Additional service data parameters",
                            },
                        },
                        "required": ["domain", "service", "target", "data"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["response", "actions"],
            "additionalProperties": False,
        },
    },
}

# Action instructions for the system prompt
ACTION_INSTRUCTIONS = """
You can control Home Assistant devices by including actions in your response.
When the user asks to control a device, include the appropriate action.

IMPORTANT: You MUST respond with a valid JSON object in this exact format:
{
    "response": "Your text response to the user",
    "actions": [
        {
            "domain": "light",
            "service": "turn_on",
            "target": "light.living_room",
            "data": {"brightness": 255}
        }
    ]
}

If no action is needed, set "actions" to null or an empty array [].

Common domains and services:
- light: turn_on, turn_off, toggle (data: brightness, color_temp, rgb_color)
- switch: turn_on, turn_off, toggle
- climate: set_temperature, set_hvac_mode (data: temperature, hvac_mode)
- cover: open_cover, close_cover, set_cover_position
- media_player: media_play, media_pause, volume_set (data: volume_level)
- script: turn_on (to run scripts)
- scene: turn_on (to activate scenes)
- fan: turn_on, turn_off, set_percentage (data: percentage)

Always use the entity_id as the target.
If data is not needed, set it to null.
"""


@dataclass
class ParsedAction:
    """Represents a parsed action from the LLM response."""

    domain: str
    service: str
    target: str
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Return string representation."""
        data_str = json.dumps(self.data) if self.data else "{}"
        return f"{self.domain}.{self.service} -> {self.target} ({data_str})"


@dataclass
class ParsedResponse:
    """Represents a parsed response from the LLM."""

    content: str
    actions: list[ParsedAction] = field(default_factory=list)


def _parse_json_response(response_text: str) -> ParsedResponse:
    """Parse the JSON response from the LLM.

    Args:
        response_text: The raw response text from the LLM.

    Returns:
        ParsedResponse with content and optional actions.

    """
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # If JSON parsing fails, try to extract JSON from markdown code blocks
        json_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL
        )
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                return ParsedResponse(content=response_text)
        else:
            return ParsedResponse(content=response_text)

    # Extract response text
    content = data.get("response", "")
    if not content and isinstance(data.get("content"), str):
        content = data["content"]

    # Extract actions
    actions: list[ParsedAction] = []
    raw_actions = data.get("actions", [])
    if raw_actions:
        for action_data in raw_actions:
            if not isinstance(action_data, dict):
                continue
            domain = action_data.get("domain", "")
            service = action_data.get("service", "")
            target = action_data.get("target", "")
            if domain and service and target:
                actions.append(
                    ParsedAction(
                        domain=domain,
                        service=service,
                        target=target,
                        data=action_data.get("data") or {},
                    )
                )

    return ParsedResponse(content=content or response_text, actions=actions)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PerplexityConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    for subentry_id, subentry in config_entry.subentries.items():
        if subentry.subentry_type != "conversation":
            continue
        async_add_entities(
            [PerplexityConversationEntity(config_entry, subentry)],
            config_subentry_id=subentry_id,
        )


class PerplexityConversationEntity(PerplexityEntity, conversation.ConversationEntity):
    """Perplexity conversation agent with custom action parsing."""

    _attr_name = None

    def __init__(self, entry: PerplexityConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the agent."""
        super().__init__(entry, subentry)
        self._llm_api_ids: list[str] | None = subentry.data.get(CONF_LLM_HASS_API)
        if self._llm_api_ids:
            self._attr_supported_features = (
                conversation.ConversationEntityFeature.CONTROL
            )

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Process the user input and call the API."""
        options = self.subentry.data
        user_prompt = options.get(CONF_PROMPT)
        llm_api_ids = options.get(CONF_LLM_HASS_API)

        if llm_api_ids:
            # Use custom action parsing approach
            return await self._async_handle_with_actions(
                user_input, chat_log, user_prompt, llm_api_ids
            )

        # Standard conversation without action support
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                None,
                user_prompt,
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        await self._async_handle_chat_log(chat_log)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _async_handle_with_actions(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
        user_prompt: str | None,
        llm_api_ids: list[str],
    ) -> conversation.ConversationResult:
        """Handle conversation with custom action parsing.

        Since Perplexity doesn't support native tool/function calling,
        we use structured JSON output to parse actions from the response.
        """
        # Build system prompt with action instructions and entity context
        system_prompt_parts: list[str] = []

        # Add base instructions
        system_prompt_parts.append(llm.DEFAULT_INSTRUCTIONS_PROMPT)

        # Add user prompt if provided
        if user_prompt:
            system_prompt_parts.append(user_prompt)

        # Add extra system prompt if provided
        if user_input.extra_system_prompt:
            system_prompt_parts.append(user_input.extra_system_prompt)

        # Add action instructions
        system_prompt_parts.append(ACTION_INSTRUCTIONS)

        # Generate and add entity context
        entity_context = await self._async_generate_entity_context(llm_api_ids)
        if entity_context:
            system_prompt_parts.append(f"\nAvailable entities:\n{entity_context}")

        system_prompt = "\n".join(system_prompt_parts)

        # Add system prompt to chat log
        chat_log.content.insert(
            0,
            conversation.SystemContent(content=system_prompt),
        )

        # Call API with structured JSON response format
        await self._async_handle_chat_log(
            chat_log,
            response_format=ACTION_RESPONSE_SCHEMA,
        )

        # Parse and execute actions from the response
        last_content = chat_log.content[-1]
        if (
            isinstance(last_content, conversation.AssistantContent)
            and last_content.content
        ):
            parsed = _parse_json_response(last_content.content)

            # Update the response content to just the text
            chat_log.content[-1] = conversation.AssistantContent(
                agent_id=last_content.agent_id,
                content=parsed.content,
            )

            # Execute actions
            for action in parsed.actions:
                await self._async_execute_action(action)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _async_generate_entity_context(self, llm_api_ids: list[str]) -> str:
        """Generate entity context for the system prompt."""
        try:
            # Get exposed entities using the llm helper
            # Import the internal function to get exposed entities
            from homeassistant.helpers.llm import _get_exposed_entities  # noqa: PLC0415

            exposed_entities_data = _get_exposed_entities(
                self.hass, conversation.DOMAIN, include_state=True
            )

            # Build entity list from exposed entities
            entity_lines: list[str] = []
            entities = exposed_entities_data.get("entities", {})

            for entity_id, entity_info in list(entities.items())[:100]:
                state = self.hass.states.get(entity_id)
                if state:
                    names = entity_info.get("names", [entity_id])
                    name = names[0] if names else entity_id
                    areas = entity_info.get("areas", [])
                    area_str = f" (area: {areas[0]})" if areas else ""
                    entity_lines.append(
                        f"- {entity_id}: {name}, state: {state.state}{area_str}"
                    )

            return "\n".join(entity_lines)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Failed to generate entity context", exc_info=True)
            return ""

    async def _async_execute_action(self, action: ParsedAction) -> None:
        """Execute a parsed action."""
        LOGGER.debug(
            "Executing action: %s.%s on %s with data %s",
            action.domain,
            action.service,
            action.target,
            action.data,
        )

        try:
            service_data: dict[str, Any] = {"entity_id": action.target}
            if action.data:
                service_data.update(action.data)
            await self.hass.services.async_call(
                action.domain,
                action.service,
                service_data,
                blocking=True,
            )
        except HomeAssistantError as err:
            LOGGER.warning(
                "Failed to execute action %s.%s on %s: %s",
                action.domain,
                action.service,
                action.target,
                err,
            )
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                "Unexpected error executing action %s.%s on %s",
                action.domain,
                action.service,
                action.target,
            )
