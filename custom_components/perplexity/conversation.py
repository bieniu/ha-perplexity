"""Conversation platform for Perplexity integration."""

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
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.llm import _get_exposed_entities
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads_object

from . import PerplexityConfigEntry
from .const import (
    ACTION_INSTRUCTIONS,
    ACTION_RESPONSE_SCHEMA,
    CONF_PROMPT,
    DOMAIN,
    LOGGER,
)
from .entity import PerplexityEntity


@dataclass
class ParsedAction:
    """Represents a parsed action from the LLM response."""

    domain: str
    service: str
    target: str
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Return string representation."""
        data_str = json_dumps(self.data) if self.data else "{}"
        return f"{self.domain}.{self.service} -> {self.target} ({data_str})"


@dataclass
class ParsedResponse:
    """Represents a parsed response from the LLM."""

    content: str
    actions: list[ParsedAction] = field(default_factory=list)


def _parse_json_response(response_text: str) -> ParsedResponse:
    """Parse the JSON response from the LLM."""
    try:
        data = json_loads_object(response_text)
    except JSON_DECODE_EXCEPTIONS:
        # If JSON parsing fails, try to extract JSON from markdown code blocks
        json_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL
        )
        if json_match:
            try:
                data = json_loads_object(json_match.group(1))
            except JSON_DECODE_EXCEPTIONS:
                return ParsedResponse(content=response_text)
        else:
            return ParsedResponse(content=response_text)

    # Extract response text
    content_value = data.get("response")
    if isinstance(content_value, str):
        content = content_value
    else:
        content_value = data.get("content")
        content = content_value if isinstance(content_value, str) else ""

    # Extract actions
    actions: list[ParsedAction] = []
    raw_actions = data.get("actions")
    if isinstance(raw_actions, list):
        for action_data in raw_actions:
            if not isinstance(action_data, dict):
                continue
            domain = action_data.get("domain")
            service = action_data.get("service")
            target = action_data.get("target")
            raw_data = action_data.get("data")
            if (
                isinstance(domain, str)
                and isinstance(service, str)
                and isinstance(target, str)
            ):
                actions.append(
                    ParsedAction(
                        domain=domain,
                        service=service,
                        target=target,
                        data=raw_data if isinstance(raw_data, dict) else {},
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
            return await self._async_handle_with_actions(
                user_input, chat_log, user_prompt, llm_api_ids
            )

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
        """Handle conversation with custom action parsing."""
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
