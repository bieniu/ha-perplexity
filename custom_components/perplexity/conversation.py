"""Conversation platform for Perplexity integration."""

import re
from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass, field
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LLM_HASS_API, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.llm import NO_ENTITIES_PROMPT, _get_exposed_entities
from homeassistant.util import yaml as yaml_util
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads_object

from perplexity.types import StreamChunk

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
        extra_parts: list[str] = []

        if user_input.extra_system_prompt:
            extra_parts.append(user_input.extra_system_prompt)
        extra_parts.append(ACTION_INSTRUCTIONS)

        extra_parts.append(await self._async_generate_entity_context(llm_api_ids))

        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                None,
                user_prompt,
                "\n".join(extra_parts),
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        # Buffer the stream and parse JSON so only text is visible to the user
        parsed_results: list[ParsedResponse] = []

        async def _buffer_and_parse(
            stream: AsyncIterable[StreamChunk],
        ) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
            """Buffer the full stream, parse JSON, yield only text content."""
            full_content = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta:
                    delta_content = chunk.choices[0].delta.content
                    if delta_content:
                        full_content += (
                            delta_content
                            if isinstance(delta_content, str)
                            else str(delta_content)
                        )
            parsed = _parse_json_response(full_content)
            parsed_results.append(parsed)
            yield {"role": "assistant"}
            if parsed.content:
                yield {"content": parsed.content}

        await self._async_handle_chat_log(
            chat_log,
            response_format=ACTION_RESPONSE_SCHEMA,
            stream_transform=_buffer_and_parse,
        )

        # Execute actions from the parsed response
        if parsed_results:
            for action in parsed_results[0].actions:
                await self._async_execute_action(action)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _async_generate_entity_context(self, llm_api_ids: list[str]) -> str:
        """Generate entity context for the system prompt."""
        exposed_entities = _get_exposed_entities(
            self.hass, conversation.DOMAIN, include_state=True
        )["entities"]

        if not exposed_entities:
            return NO_ENTITIES_PROMPT

        return (
            "An overview of the areas and the devices in this smart home:\n"
            + yaml_util.dump(list(exposed_entities.values()))
        )

    async def _async_execute_action(self, action: ParsedAction) -> None:
        """Execute a parsed action."""
        LOGGER.debug(
            "Executing action: %s.%s on %s with data %s",
            action.domain,
            action.service,
            action.target,
            action.data,
        )

        service_data: dict[str, Any] = {"entity_id": action.target}
        if action.data:
            service_data.update(action.data)
        await self.hass.services.async_call(
            action.domain,
            action.service,
            service_data,
            blocking=True,
        )
