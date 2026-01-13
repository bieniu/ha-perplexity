"""Base entity for Perplexity."""

import base64
from collections.abc import AsyncGenerator
from mimetypes import guess_file_type
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
import voluptuous as vol
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps
from voluptuous_openapi import convert

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError
from perplexity.types import StreamChunk

from . import PerplexityConfigEntry
from .const import (
    CONF_REASONING_EFFORT,
    DEFAULT_REASONING_EFFORT,
    DOMAIN,
    LOGGER,
    REASONING_MODELS,
)

# Max number of back and forth with the LLM to generate a response
MAX_TOOL_ITERATIONS = 10


def _adjust_schema(schema: dict[str, Any]) -> None:
    """Adjust the schema to be compatible with Perplexity API."""
    if schema["type"] == "object":
        if "properties" not in schema:
            return

        if "required" not in schema:
            schema["required"] = []

        # Ensure all properties are required
        for prop, prop_info in schema["properties"].items():
            _adjust_schema(prop_info)
            if prop not in schema["required"]:
                prop_info["type"] = [prop_info["type"], "null"]
                schema["required"].append(prop)

    elif schema["type"] == "array":
        if "items" not in schema:
            return

        _adjust_schema(schema["items"])


def _format_structured_output(
    name: str, schema: vol.Schema, llm_api: llm.APIInstance | None
) -> dict[str, Any]:
    """Format the schema to be compatible with Perplexity API."""
    result: dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
        },
    }
    result_schema = convert(
        schema,
        custom_serializer=(
            llm_api.custom_serializer if llm_api else llm.selector_serializer
        ),
    )

    _adjust_schema(result_schema)

    result["json_schema"]["schema"] = result_schema
    return result


def _convert_content_to_chat_message(
    content: conversation.Content,
) -> dict[str, Any] | None:
    """Convert any native chat message for this agent to the native format."""
    if isinstance(content, conversation.ToolResultContent):
        return {
            "role": "tool",
            "content": json_dumps(content.tool_result),
        }

    if content.role == "system" and content.content:
        return {"role": "system", "content": content.content}

    if content.role == "user" and content.content:
        return {"role": "user", "content": content.content}

    if content.role == "assistant":
        result: dict[str, Any] = {
            "role": "assistant",
            "content": content.content,
        }
        return result
    LOGGER.warning("Could not convert message to Perplexity API: %s", content)
    return None


async def _transform_response(
    response: StreamChunk,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform the Perplexity response to a ChatLog format."""
    message = response.choices[0].message
    data: conversation.AssistantContentDeltaDict = {
        "role": "assistant",
        "content": message.content if isinstance(message.content, str) else None,
    }
    yield data


async def _async_prepare_files_for_prompt(
    files: list[tuple[Path, str | None]],
) -> list[dict[str, Any]]:
    """Prepare files for the prompt.

    Caller needs to ensure that the files are allowed.
    """
    content: list[dict[str, Any]] = []

    for file_path, mime_type in files:
        if not file_path.exists():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="file_not_found",
                translation_placeholders={"file_path": str(file_path)},
            )

        if mime_type is None:
            mime_type = guess_file_type(file_path)[0]  # noqa: PLW2901

        if not mime_type or not mime_type.startswith("image/"):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_file_type",
                translation_placeholders={"file_path": str(file_path)},
            )

        async with aiofiles.open(file_path, "rb") as f:
            file_bytes = await f.read()
        base64_file = base64.b64encode(file_bytes).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_file}"},
            }
        )

    return content


class PerplexityEntity(Entity):
    """Base entity for Perplexity."""

    _attr_has_entity_name = True

    def __init__(self, entry: PerplexityConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self.model = subentry.data[CONF_MODEL]
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure_name: str | None = None,
        structure: vol.Schema | None = None,
    ) -> None:
        """Generate an answer for the chat log."""
        model_args: dict[str, Any] = {
            "model": self.model,
            "disable_search": True,
        }

        if self.model in REASONING_MODELS:
            model_args["reasoning_effort"] = self.subentry.data.get(
                CONF_REASONING_EFFORT, DEFAULT_REASONING_EFFORT
            )

        model_args["messages"] = [
            m
            for content in chat_log.content
            if (m := _convert_content_to_chat_message(content))
        ]

        last_content = chat_log.content[-1]

        # Handle attachments by adding them to the last user message
        if (
            isinstance(last_content, conversation.UserContent)
            and last_content.attachments
        ):
            last_message = model_args["messages"][-1]

            if TYPE_CHECKING:
                assert last_message["role"] == "user"
                assert isinstance(last_message["content"], str)

            # Encode files with base64 and append them to the text prompt
            files = await _async_prepare_files_for_prompt(
                [(a.path, a.mime_type) for a in last_content.attachments],
            )
            last_message["content"] = [
                {"type": "text", "text": last_message["content"]},
                *files,
            ]

        if structure:
            model_args["response_format"] = _format_structured_output(
                structure_name or "response", structure, chat_log.llm_api
            )

        client: AsyncPerplexity = self.entry.runtime_data

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                result = await client.chat.completions.create(**model_args)
            except AuthenticationError as err:
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="auth_error",
                    translation_placeholders={"entry": self.entry.title},
                ) from err
            except PerplexityError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={
                        "entry": self.entry.title,
                        "error": str(err),
                    },
                ) from err

            model_args["messages"].extend(
                [
                    msg
                    async for content in chat_log.async_add_delta_content_stream(
                        self.entity_id, _transform_response(result)
                    )
                    if (msg := _convert_content_to_chat_message(content))
                ]
            )
            if not chat_log.unresponded_tool_results:
                break
