"""AI Task integration for Perplexity."""

from __future__ import annotations

from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads

from custom_components.perplexity.const import DOMAIN

from . import PerplexityConfigEntry
from .entity import PerplexityEntity


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: PerplexityConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue

        async_add_entities(
            [PerplexityAITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class PerplexityAITaskEntity(
    ai_task.AITaskEntity,
    PerplexityEntity,
):
    """Perplexity AI Task entity."""

    _attr_name = None
    _attr_supported_features = (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
    )

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        await self._async_handle_chat_log(chat_log, task.name, task.structure)

        last_content = chat_log.content[-1]
        if not isinstance(last_content, conversation.AssistantContent):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_assistant_response",
            )

        text = last_content.content or ""

        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )
        try:
            data = json_loads(text)
        except JSON_DECODE_EXCEPTIONS as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="structured_response_error",
                translation_placeholders={"error": str(err)},
            ) from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )
