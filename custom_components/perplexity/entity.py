"""Base entity for Perplexity."""

import base64
import re
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from functools import partial
from mimetypes import guess_file_type
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
import probatio
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from probatio import to_openapi

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError
from perplexity.types import ResponseStreamChunk

from . import PerplexityConfigEntry
from .const import (
    CONF_REASONING_EFFORT,
    CONF_WEB_SEARCH,
    DEFAULT_WEB_SEARCH,
    DOMAIN,
    WEB_SEARCH_ADDITIONAL_INSTRUCTION,
)


def _api_error(entry_title: str, error: str) -> HomeAssistantError:
    """Build the translated API error."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="api_error",
        translation_placeholders={"entry": entry_title, "error": error},
    )


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
    name: str, schema: probatio.Schema, llm_api: llm.APIInstance | None
) -> dict[str, str | dict[str, Any]]:
    """Format the schema to be compatible with Perplexity API."""
    # The API expects a 1-64 character name made of [A-Za-z0-9_-]
    name = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64] or "response"
    result: dict[str, str | dict[str, Any]] = {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
        },
    }
    result_schema = to_openapi(
        schema,
        custom_serializer=(
            llm_api.custom_serializer if llm_api else llm.selector_serializer
        ),
    )

    _adjust_schema(result_schema)

    result["json_schema"]["schema"] = result_schema
    return result


def _convert_content_to_input_message(
    content: conversation.Content,
) -> dict[str, Any] | None:
    """Convert user and assistant content to an Agent API input message."""
    if TYPE_CHECKING:
        assert not isinstance(content, conversation.ToolResultContent)

    if content.role in ("user", "assistant") and content.content:
        return {"type": "message", "role": content.role, "content": content.content}

    return None


def _field(obj: object, key: str) -> Any:  # noqa: ANN401
    """Return a field from a typed SDK model or a raw dict."""
    # Fields the SDK models do not declare are kept as raw dicts
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _incomplete_error(entry_title: str, response: object) -> HomeAssistantError:
    """Return the error for a response truncated before completion."""
    details = _field(response, "incomplete_details")
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="response_incomplete",
        translation_placeholders={
            "entry": entry_title,
            "reason": _field(details, "reason") or "unknown",
        },
    )


async def _async_iter_text_deltas(
    stream: AsyncIterable[ResponseStreamChunk], entry_title: str
) -> AsyncGenerator[str]:
    """Yield text deltas from the Perplexity stream."""
    try:
        async for chunk in stream:
            if chunk.type == "response.output_text.delta":
                yield chunk.delta
            elif chunk.type == "response.failed":
                raise _api_error(entry_title, chunk.error.message)
            elif chunk.type == "response.completed":
                # Failed and cancelled runs can still end with this event
                status = _field(chunk.response, "status")
                if status == "incomplete":
                    raise _incomplete_error(entry_title, chunk.response)
                if status not in (None, "completed"):
                    error = _field(_field(chunk.response, "error"), "message")
                    raise _api_error(entry_title, error or f"response {status}")
            else:
                # The SDK union lacks these terminals, so they arrive loosely typed
                event_type: str = chunk.type
                if event_type == "response.incomplete":
                    raise _incomplete_error(entry_title, _field(chunk, "response"))
                if event_type in ("response.cancelled", "error"):
                    error = _field(_field(chunk, "error"), "message")
                    raise _api_error(entry_title, error or event_type)
    except PerplexityError as err:
        raise _api_error(entry_title, str(err)) from err


async def _transform_stream(
    stream: AsyncIterable[ResponseStreamChunk], entry_title: str
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform the Perplexity stream to delta content."""
    first = True
    async for delta in _async_iter_text_deltas(stream, entry_title):
        if first:
            yield {"role": "assistant"}
            first = False
        yield {"content": delta}


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
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{base64_file}",
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
        structure: probatio.Schema | None = None,
        response_format: dict[str, Any] | None = None,
        stream_transform: Callable[
            [AsyncIterable[ResponseStreamChunk]],
            AsyncGenerator[conversation.AssistantContentDeltaDict],
        ]
        | None = None,
    ) -> None:
        """Generate an answer for the chat log."""
        web_search = self.subentry.data.get(CONF_WEB_SEARCH, DEFAULT_WEB_SEARCH)
        model_args: dict[str, Any] = {"preset": self.model, "stream": True}

        # Presets ship with web search, so tools must be disabled explicitly
        if not web_search:
            model_args["tool_choice"] = "none"

        if CONF_REASONING_EFFORT in self.subentry.data:
            model_args["reasoning"] = {
                "effort": self.subentry.data[CONF_REASONING_EFFORT]
            }

        instructions = [
            content.content
            for content in chat_log.content
            if isinstance(content, conversation.SystemContent) and content.content
        ]
        if web_search:
            instructions.append(WEB_SEARCH_ADDITIONAL_INSTRUCTION)
        if instructions:
            model_args["instructions"] = "\n".join(instructions)

        model_args["input"] = [
            m
            for content in chat_log.content
            if (m := _convert_content_to_input_message(content))
        ]

        last_content = chat_log.content[-1]

        # Handle attachments by adding them to the last user message
        if (
            isinstance(last_content, conversation.UserContent)
            and last_content.attachments
        ):
            last_message = model_args["input"][-1]

            if TYPE_CHECKING:
                assert last_message["role"] == "user"
                assert isinstance(last_message["content"], str)

            # Encode files with base64 and append them to the text prompt
            files = await _async_prepare_files_for_prompt(
                [(a.path, a.mime_type) for a in last_content.attachments],
            )
            last_message["content"] = [
                {"type": "input_text", "text": last_message["content"]},
                *files,
            ]

        if structure:
            model_args["response_format"] = _format_structured_output(
                structure_name or "response", structure, chat_log.llm_api
            )
        elif response_format:
            model_args["response_format"] = response_format

        client: AsyncPerplexity = self.entry.runtime_data

        try:
            stream = await client.responses.create(**model_args)
        except AuthenticationError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="auth_error",
                translation_placeholders={"entry": self.entry.title},
            ) from err
        except PerplexityError as err:
            raise _api_error(self.entry.title, str(err)) from err

        transform = stream_transform or partial(
            _transform_stream, entry_title=self.entry.title
        )
        async for _ in chat_log.async_add_delta_content_stream(
            self.entity_id, transform(stream)
        ):
            pass
