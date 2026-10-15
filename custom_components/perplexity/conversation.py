"""Conversation platform for Perplexity integration."""

from typing import Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LLM_HASS_API, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PerplexityConfigEntry
from .const import (
    CONF_INCLUDE_HOME_LOCATION,
    CONF_PROMPT,
    DOMAIN,
    SUBENTRY_TYPE_CONVERSATION,
)
from .entity import PerplexityEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PerplexityConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    for subentry in config_entry.get_subentries_of_type(SUBENTRY_TYPE_CONVERSATION):
        async_add_entities(
            [PerplexityConversationEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class PerplexityConversationEntity(PerplexityEntity, conversation.ConversationEntity):
    """Perplexity conversation agent."""

    _attr_name = None
    _attr_supports_streaming = True

    def __init__(self, entry: PerplexityConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the agent."""
        super().__init__(entry, subentry)
        if subentry.data.get(CONF_LLM_HASS_API):
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

        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                options.get(CONF_LLM_HASS_API),
                options.get(CONF_PROMPT),
                self._build_extra_system_prompt(user_input.extra_system_prompt),
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        await self._async_handle_chat_log(chat_log)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    def _build_extra_system_prompt(
        self, original_extra_prompt: str | None
    ) -> str | None:
        """Build extra system prompt with optional home location."""
        parts: list[str] = []

        if location_prompt := self._get_home_location_prompt():
            parts.append(location_prompt)

        if original_extra_prompt:
            parts.append(original_extra_prompt)

        return "\n".join(parts) if parts else None

    def _get_home_location_prompt(self) -> str | None:
        """Get a prompt with home location information."""
        if not self.subentry.data.get(CONF_INCLUDE_HOME_LOCATION):
            return None

        location_parts: list[str] = []

        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        if latitude is not None and longitude is not None:
            location_parts.append(
                f"Coordinates: {round(latitude, 3)},{round(longitude, 3)}"
            )

        if country := self.hass.config.country:
            location_parts.append(f"Country: {country}")

        if not location_parts:
            return None

        return "User's home location information:\n" + "\n".join(location_parts)
