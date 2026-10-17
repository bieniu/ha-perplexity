"""Base entity for Perplexity."""

import base64
import json
import re
from collections.abc import AsyncGenerator, AsyncIterable, Callable, Iterable
from mimetypes import guess_file_type
from pathlib import Path
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps
from probatio import to_openapi

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError
from perplexity.types import ResponseStreamChunk

from . import PerplexityConfigEntry
from .const import (
    CONF_REASONING_EFFORT,
    DOMAIN,
    LOGGER,
    WEB_SEARCH_ADDITIONAL_INSTRUCTION,
)

# Max number of back and forth with the LLM to generate a response
MAX_TOOL_ITERATIONS = 10

# The API rejects custom tools using the names of its built-in tools
RESERVED_TOOL_NAMES = {"web_search"}


def _api_error(entry_title: str, error: str) -> HomeAssistantError:
    """Build the translated API error."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="api_error",
        translation_placeholders={"entry": entry_title, "error": error},
    )


def _adjust_schema(schema: dict[str, Any]) -> None:
    """Adjust the schema to be compatible with Perplexity API."""
    schema_type = schema.get("type")
    if schema_type == "object":
        if "properties" not in schema:
            return

        if "required" not in schema:
            schema["required"] = []

        # Ensure all properties are required
        for prop, prop_info in schema["properties"].items():
            _adjust_schema(prop_info)
            if prop not in schema["required"]:
                # Combinators like anyOf carry no type to make nullable
                if "type" in prop_info:
                    prop_info["type"] = [prop_info["type"], "null"]
                schema["required"].append(prop)

    elif schema_type == "array":
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


def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> dict[str, Any]:
    """Format a Home Assistant tool as an Agent API function tool."""
    schema = to_openapi(
        tool.parameters, custom_serializer=custom_serializer, openapi_version="3.1.0"
    )
    # Function schemas do not accept combinators at the top level
    unsupported_keys = {"oneOf", "anyOf", "allOf", "enum", "not"}
    schema = {k: v for k, v in schema.items() if k not in unsupported_keys}

    result: dict[str, Any] = {
        "type": "function",
        "name": tool.name,
        "parameters": schema,
        "strict": False,
    }
    if tool.description:
        result["description"] = tool.description
    return result


def _convert_content_to_input(
    chat_content: Iterable[conversation.Content],
) -> list[dict[str, Any]]:
    """Convert chat log content to Agent API input items."""
    items: list[dict[str, Any]] = []
    # Thinking models need their signature echoed on the call and its result
    signatures: dict[str, str] = {}

    for content in chat_content:
        if isinstance(content, conversation.ToolResultContent):
            output = {
                "type": "function_call_output",
                "call_id": content.tool_call_id,
                "name": content.tool_name,
                "output": json_dumps(
                    {"data": content.result.data, "error": content.result.error}
                ),
            }
            if signature := signatures.get(content.tool_call_id):
                output["thought_signature"] = signature
            items.append(output)
            continue

        # System content is sent as instructions
        if content.role == "system":
            continue

        # Attachments are added to this item later, even without text
        if content.content or (
            isinstance(content, conversation.UserContent) and content.attachments
        ):
            items.append(
                {"type": "message", "role": content.role, "content": content.content}
            )

        if isinstance(content, conversation.AssistantContent) and content.tool_calls:
            # Other agents may store any native data, only ours is a signature map
            if isinstance(content.native, dict):
                signatures.update(content.native)
            for tool_call in content.tool_calls:
                call = {
                    "type": "function_call",
                    "call_id": tool_call.id,
                    "name": tool_call.tool_name,
                    "arguments": json_dumps(tool_call.tool_args),
                }
                if signature := signatures.get(tool_call.id):
                    call["thought_signature"] = signature
                items.append(call)

    return items


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


def _decode_tool_arguments(arguments: str | None, entry_title: str) -> dict[str, Any]:
    """Decode tool call arguments, which are empty for parameterless tools."""
    try:
        tool_args = json.loads(arguments or "{}")
    except json.JSONDecodeError as err:
        raise _api_error(entry_title, f"invalid tool arguments: {err}") from err
    if not isinstance(tool_args, dict):
        raise _api_error(entry_title, "tool arguments are not an object")
    return tool_args


async def _async_iter_events(
    stream: AsyncIterable[ResponseStreamChunk], entry_title: str
) -> AsyncGenerator[ResponseStreamChunk]:
    """Yield stream events, raising on failed or truncated responses."""
    try:
        async for chunk in stream:
            if chunk.type == "response.failed":
                raise _api_error(entry_title, chunk.error.message)
            if chunk.type == "response.completed":
                # Failed and cancelled runs can still end with this event
                status = _field(chunk.response, "status")
                if status == "incomplete":
                    raise _incomplete_error(entry_title, chunk.response)
                if status not in (None, "completed", "requires_action"):
                    error = _field(_field(chunk.response, "error"), "message")
                    raise _api_error(entry_title, error or f"response {status}")
                continue
            # The SDK union lacks these terminals, so they arrive loosely typed
            event_type: str = chunk.type
            if event_type == "response.incomplete":
                raise _incomplete_error(entry_title, _field(chunk, "response"))
            if event_type in ("response.cancelled", "error"):
                error = _field(_field(chunk, "error"), "message")
                raise _api_error(entry_title, error or event_type)
            yield chunk
    except PerplexityError as err:
        raise _api_error(entry_title, str(err)) from err


async def _transform_stream(
    stream: AsyncIterable[ResponseStreamChunk], entry_title: str
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform the Perplexity stream to delta content."""
    role_open = False

    # The SDK leaves an output item as a raw dict when its generated model does
    # not validate (a message streamed with `content: null`), so read via _field
    async for chunk in _async_iter_events(stream, entry_title):
        if chunk.type == "response.output_item.added":
            if _field(chunk.item, "type") == "message" and not role_open:
                # Consecutive message items must share one content, HA reads
                # only the last one
                yield {"role": "assistant"}
                role_open = True
        elif chunk.type == "response.output_text.delta":
            # The voice pipeline ignores text until a role has been announced
            if not role_open:
                yield {"role": "assistant"}
                role_open = True
            yield {"content": chunk.delta}
        elif (
            chunk.type == "response.output_item.done"
            and _field(chunk.item, "type") == "function_call"
        ):
            item = chunk.item
            call_id = _field(item, "call_id")
            # One delta per call, so HA never sees two signatures in one content
            delta: conversation.AssistantContentDeltaDict = {
                "role": "assistant",
                "tool_calls": [
                    llm.ToolInput(
                        id=call_id,
                        tool_name=_field(item, "name"),
                        tool_args=_decode_tool_arguments(
                            _field(item, "arguments"), entry_title
                        ),
                    )
                ],
            }
            if signature := _field(item, "thought_signature"):
                delta["native"] = {call_id: signature}
            yield delta
            role_open = False


def _prepare_files_for_prompt(
    files: list[tuple[Path, str | None]],
) -> list[dict[str, Any]]:
    """Prepare files for the prompt; the caller must ensure they are allowed."""
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

        base64_file = base64.b64encode(file_path.read_bytes()).decode("utf-8")
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
    ) -> None:
        """Generate an answer for the chat log."""
        model_args: dict[str, Any] = {"preset": self.model, "stream": True}

        if CONF_REASONING_EFFORT in self.subentry.data:
            model_args["reasoning"] = {
                "effort": self.subentry.data[CONF_REASONING_EFFORT]
            }

        instructions = [
            content.content
            for content in chat_log.content
            if isinstance(content, conversation.SystemContent) and content.content
        ]
        # Presets always search the web and the API offers no way to turn it off
        instructions.append(WEB_SEARCH_ADDITIONAL_INSTRUCTION)
        model_args["instructions"] = "\n".join(instructions)

        if chat_log.llm_api:
            tools: list[dict[str, Any]] = []
            for tool in chat_log.llm_api.tools:
                if tool.name in RESERVED_TOOL_NAMES:
                    LOGGER.debug(
                        "Skipping tool %s, the name is reserved by the Perplexity API",
                        tool.name,
                    )
                    continue
                tools.append(_format_tool(tool, chat_log.llm_api.custom_serializer))
            if tools:
                model_args["tools"] = tools

        model_args["input"] = _convert_content_to_input(chat_log.content)

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
            files = await self.hass.async_add_executor_job(
                _prepare_files_for_prompt,
                [(a.path, a.mime_type) for a in last_content.attachments],
            )
            text_parts = (
                [{"type": "input_text", "text": last_message["content"]}]
                if last_message["content"]
                else []
            )
            last_message["content"] = [*text_parts, *files]

        if structure:
            model_args["response_format"] = _format_structured_output(
                structure_name or "response", structure, chat_log.llm_api
            )

        client: AsyncPerplexity = self.entry.runtime_data

        # To prevent infinite loops, we limit the number of iterations
        for _iteration in range(MAX_TOOL_ITERATIONS):
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

            model_args["input"].extend(
                _convert_content_to_input(
                    [
                        content
                        async for content in chat_log.async_add_delta_content_stream(
                            self.entity_id,
                            _transform_stream(stream, self.entry.title),
                        )
                    ]
                )
            )

            if not chat_log.unresponded_tool_results:
                break
