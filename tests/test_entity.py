"""Tests for the Perplexity entity module."""

from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import probatio
import pytest
from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from perplexity import AuthenticationError, PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.const import DOMAIN
from custom_components.perplexity.entity import (
    _adjust_schema,
    _async_iter_events,
    _async_prepare_files_for_prompt,
    _convert_content_to_input,
    _format_structured_output,
    _format_tool,
    _transform_stream,
)

from .conftest import function_call_item, message_item, output_item_events


def test_adjust_schema_object_with_properties() -> None:
    """Test _adjust_schema with object type and properties."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    _adjust_schema(schema)

    assert schema["required"] == ["name", "age"]
    assert schema["properties"]["name"]["type"] == ["string", "null"]
    assert schema["properties"]["age"]["type"] == ["integer", "null"]


def test_adjust_schema_object_without_properties() -> None:
    """Test _adjust_schema with object type but no properties."""
    schema = {"type": "object"}
    _adjust_schema(schema)

    assert "required" not in schema


def test_adjust_schema_object_with_existing_required() -> None:
    """Test _adjust_schema with object that already has required fields."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    }
    _adjust_schema(schema)

    assert "name" in schema["required"]
    assert "age" in schema["required"]
    # name was already required, so type should not be modified to include null
    assert schema["properties"]["name"]["type"] == "string"
    # age was not required, so type should be modified
    assert schema["properties"]["age"]["type"] == ["integer", "null"]


def test_adjust_schema_array_with_items() -> None:
    """Test _adjust_schema with array type and items."""
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
            },
        },
    }
    _adjust_schema(schema)

    assert schema["items"]["required"] == ["id"]


def test_adjust_schema_array_without_items() -> None:
    """Test _adjust_schema with array type but no items."""
    schema = {"type": "array"}
    _adjust_schema(schema)

    assert "items" not in schema


def test_adjust_schema_nested_objects() -> None:
    """Test _adjust_schema with nested object structures."""
    schema = {
        "type": "object",
        "properties": {
            "nested": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                },
            },
        },
    }
    _adjust_schema(schema)

    assert schema["required"] == ["nested"]
    assert schema["properties"]["nested"]["required"] == ["value"]


def test_format_structured_output_without_llm_api() -> None:
    """Test _format_structured_output without LLM API."""
    schema = probatio.Schema({probatio.Required("key"): str})
    result = _format_structured_output("test_name", schema, None)

    assert result
    assert isinstance(result["json_schema"], dict)
    assert result["json_schema"]["name"] == "test_name"
    assert result["json_schema"]["strict"] is True
    assert "schema" in result["json_schema"]


def test_format_structured_output_with_llm_api() -> None:
    """Test _format_structured_output with LLM API."""
    schema = probatio.Schema({probatio.Required("key"): str})
    mock_llm_api = MagicMock()
    mock_llm_api.custom_serializer = llm.selector_serializer

    result = _format_structured_output("test_name", schema, mock_llm_api)

    assert result["type"] == "json_schema"
    assert isinstance(result["json_schema"], dict)
    assert result["json_schema"]["name"] == "test_name"


def test_convert_content_to_input() -> None:
    """Test chat log content becomes Agent API input items in order."""
    content = [
        conversation.SystemContent(content="You are a helpful assistant."),
        conversation.UserContent(content="Turn on the light"),
        conversation.AssistantContent(
            agent_id="test_agent",
            content="Sure.",
            tool_calls=[
                llm.ToolInput(
                    id="call_1",
                    tool_name="intent__HassTurnOn",
                    tool_args={"name": "light"},
                )
            ],
            native={"call_1": "c2ln"},
        ),
        conversation.ToolResultContent(
            agent_id="test_agent",
            tool_call_id="call_1",
            tool_name="intent__HassTurnOn",
            result=llm.ToolResult(data={"speech": {}}),
        ),
        conversation.AssistantContent(agent_id="test_agent", content=None),
        conversation.AssistantContent(agent_id="test_agent", content="Done"),
    ]

    assert _convert_content_to_input(content) == [
        {"type": "message", "role": "user", "content": "Turn on the light"},
        {"type": "message", "role": "assistant", "content": "Sure."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "intent__HassTurnOn",
            "arguments": '{"name":"light"}',
            "thought_signature": "c2ln",
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "name": "intent__HassTurnOn",
            "output": '{"data":{"speech":{}},"error":false}',
            "thought_signature": "c2ln",
        },
        {"type": "message", "role": "assistant", "content": "Done"},
    ]


def test_convert_content_to_input_foreign_native() -> None:
    """Test native data of other agents is not treated as signatures."""
    content = [
        conversation.AssistantContent(
            agent_id="other_agent",
            content=None,
            tool_calls=[llm.ToolInput(id="call_1", tool_name="x", tool_args={})],
            native=object(),
        ),
        conversation.ToolResultContent(
            agent_id="other_agent",
            tool_call_id="call_1",
            tool_name="x",
            result=llm.ToolResult(data={}, error=True),
        ),
    ]

    assert _convert_content_to_input(content) == [
        {"type": "function_call", "call_id": "call_1", "name": "x", "arguments": "{}"},
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "name": "x",
            "output": '{"data":{},"error":true}',
        },
    ]


class _TimerTool(llm.Tool):
    """Tool with a top-level combinator in its schema, like HassStartTimer."""

    name = "intent__HassStartTimer"
    description = "Starts a new timer"
    parameters = probatio.Schema(
        {
            probatio.Required(probatio.Any("hours", "minutes")): int,
            probatio.Optional("name"): str,
            probatio.Optional("nested"): probatio.Any(str, int),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> llm.ToolResult:
        """Never called."""
        return llm.ToolResult(data={})


def test_format_tool() -> None:
    """Test a tool schema keeps nested but drops top-level combinators."""
    result = _format_tool(_TimerTool(), llm.selector_serializer)

    assert result["type"] == "function"
    assert result["name"] == "intent__HassStartTimer"
    assert result["description"] == "Starts a new timer"
    assert result["strict"] is False
    parameters = result["parameters"]
    assert "anyOf" not in parameters
    assert set(parameters["properties"]) == {"hours", "minutes", "name", "nested"}
    assert "anyOf" in parameters["properties"]["nested"]


def test_format_tool_without_description() -> None:
    """Test the description is omitted when the tool has none."""
    tool = _TimerTool()
    tool.description = None

    assert "description" not in _format_tool(tool, None)


def _chunk(chunk_type: str, delta: str | None = None) -> MagicMock:
    """Return a mock stream chunk."""
    return MagicMock(
        type=chunk_type, delta=delta, response=MagicMock(status="completed")
    )


async def _as_stream(chunks: Sequence[Any]) -> AsyncGenerator[Any]:
    """Yield the given chunks as an async stream."""
    for chunk in chunks:
        yield chunk


async def test_async_iter_events_skips_terminal_events() -> None:
    """Test terminal events are consumed and the rest is passed through."""
    stream = _as_stream(
        [
            _chunk("response.created"),
            _chunk("response.output_text.delta", delta="Hello"),
            _chunk("response.reasoning.started"),
            _chunk("response.completed"),
        ]
    )

    assert [c.type async for c in _async_iter_events(stream, "Perplexity")] == [
        "response.created",
        "response.output_text.delta",
        "response.reasoning.started",
    ]


_TURN_ON = function_call_item("intent__HassTurnOn", '{"name":"light"}')
_SIGNED = function_call_item(
    "llm__GetDateTime", "", call_id="call_2", thought_signature="c2ln"
)
_TURN_ON_INPUT = llm.ToolInput(
    id="call_1", tool_name="intent__HassTurnOn", tool_args={"name": "light"}
)


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (
            [
                _chunk("response.created"),
                _chunk("response.output_text.delta", delta="Hi"),
                _chunk("response.output_text.delta", delta="!"),
            ],
            [{"role": "assistant"}, {"content": "Hi"}, {"content": "!"}],
        ),
        ([_chunk("response.created"), _chunk("response.completed")], []),
        (
            [
                output_item_events(message_item())[0],
                _chunk("response.output_text.delta", delta="Hi"),
                output_item_events(message_item())[0],
                _chunk("response.output_text.delta", delta="!"),
            ],
            [{"role": "assistant"}, {"content": "Hi"}, {"content": "!"}],
        ),
        (
            [*output_item_events(_TURN_ON), _chunk("response.completed")],
            [{"role": "assistant"}, {"tool_calls": [_TURN_ON_INPUT]}],
        ),
        (
            [
                *output_item_events(_TURN_ON),
                output_item_events(message_item())[0],
                _chunk("response.output_text.delta", delta="Done"),
            ],
            [
                {"role": "assistant"},
                {"tool_calls": [_TURN_ON_INPUT]},
                {"role": "assistant"},
                {"content": "Done"},
            ],
        ),
        (
            [output_item_events(_TURN_ON)[1]],
            [{"role": "assistant"}, {"tool_calls": [_TURN_ON_INPUT]}],
        ),
        (
            [*output_item_events(_SIGNED)],
            [
                {"role": "assistant"},
                {
                    "tool_calls": [
                        llm.ToolInput(
                            id="call_2", tool_name="llm__GetDateTime", tool_args={}
                        )
                    ]
                },
                {"native": {"call_2": "c2ln"}},
            ],
        ),
    ],
)
async def test_transform_stream(
    chunks: list[Any], expected: list[dict[str, Any]]
) -> None:
    """Test output items and text deltas become chat log deltas."""
    assert [
        d async for d in _transform_stream(_as_stream(chunks), "Perplexity")
    ] == expected


@pytest.mark.parametrize(
    ("arguments", "error"),
    [("{not json", "invalid tool arguments"), ("[]", "not an object")],
)
async def test_transform_stream_invalid_arguments(arguments: str, error: str) -> None:
    """Test unusable tool arguments raise an API error."""
    stream = _as_stream(
        output_item_events(function_call_item("llm__GetDateTime", arguments))
    )

    with pytest.raises(HomeAssistantError) as exc_info:
        _ = [d async for d in _transform_stream(stream, "Perplexity")]

    assert exc_info.value.translation_key == "api_error"
    placeholders = exc_info.value.translation_placeholders
    assert placeholders is not None
    assert error in placeholders["error"]


async def test_async_prepare_files_for_prompt_file_not_exists(
    hass: HomeAssistant,
) -> None:
    """Test _async_prepare_files_for_prompt with non-existent file."""
    with pytest.raises(HomeAssistantError, match="file_not_found"):
        await _async_prepare_files_for_prompt(
            [(Path("/non/existent/file.png"), "image/png")]
        )


async def test_async_prepare_files_for_prompt_non_image(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Test _async_prepare_files_for_prompt with non-image file."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    with pytest.raises(HomeAssistantError, match="unsupported_file_type"):
        await _async_prepare_files_for_prompt([(test_file, "text/plain")])


async def test_async_prepare_files_for_prompt_success(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Test _async_prepare_files_for_prompt with valid image file."""
    # Create a minimal PNG file (1x1 pixel)
    test_file = tmp_path / "test.png"
    # Minimal PNG header
    png_data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    test_file.write_bytes(png_data)

    result = await _async_prepare_files_for_prompt([(test_file, "image/png")])

    assert len(result) == 1
    assert result[0]["type"] == "input_image"
    assert result[0]["image_url"].startswith("data:image/png;base64,")


async def test_async_prepare_files_for_prompt_auto_mime_type(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Test _async_prepare_files_for_prompt with auto-detected mime type."""
    # Create a minimal PNG file
    test_file = tmp_path / "test.png"
    png_data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    test_file.write_bytes(png_data)

    # Pass None as mime_type to trigger auto-detection
    result = await _async_prepare_files_for_prompt([(test_file, None)])

    assert len(result) == 1
    assert result[0]["type"] == "input_image"
    assert "base64," in result[0]["image_url"]


async def test_ai_task_api_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task with Perplexity API error."""
    mock_perplexity_client.responses.create.side_effect = PerplexityError("API Error")

    with pytest.raises(HomeAssistantError, match="Error talking to Perplexity API"):
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
        )


async def test_ai_task_authentication_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task with authentication error."""
    mock_perplexity_client.responses.create.side_effect = AuthenticationError(
        "Invalid API key", response=MagicMock(), body=None
    )

    with pytest.raises(HomeAssistantError, match="Authentication failed"):
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
        )

    assert mock_setup_entry.state is ConfigEntryState.LOADED

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1

    flow = flows[0]
    assert flow.get("step_id") == "reauth_confirm"
    assert flow.get("handler") == DOMAIN

    assert "context" in flow
    assert flow["context"].get("source") == SOURCE_REAUTH
    assert flow["context"].get("entry_id") == mock_setup_entry.entry_id


async def test_ai_task_requires_action_status(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test a response completed with the requires_action status is accepted."""
    stream = _as_stream(
        [
            _chunk("response.output_text.delta", delta="done"),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(status="requires_action", error=None),
            ),
        ]
    )
    mock_perplexity_client.responses.create = AsyncMock(return_value=stream)

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Test instructions",
    )

    assert result.data == "done"


@pytest.mark.parametrize(
    ("chunk", "translation_key", "placeholders"),
    [
        (
            SimpleNamespace(type="response.cancelled", error={"message": "Stopped"}),
            "api_error",
            {"entry": "Perplexity", "error": "Stopped"},
        ),
        (
            SimpleNamespace(type="response.cancelled"),
            "api_error",
            {"entry": "Perplexity", "error": "response.cancelled"},
        ),
        (
            SimpleNamespace(type="error", error={"message": "Upstream timeout"}),
            "api_error",
            {"entry": "Perplexity", "error": "Upstream timeout"},
        ),
        (
            SimpleNamespace(
                type="response.incomplete",
                response=SimpleNamespace(
                    incomplete_details={"reason": "max_output_tokens"}
                ),
            ),
            "response_incomplete",
            {"entry": "Perplexity", "reason": "max_output_tokens"},
        ),
        (
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    status="incomplete",
                    incomplete_details={"reason": "max_output_tokens"},
                ),
            ),
            "response_incomplete",
            {"entry": "Perplexity", "reason": "max_output_tokens"},
        ),
        (
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    status="failed", error=SimpleNamespace(message="Model error")
                ),
            ),
            "api_error",
            {"entry": "Perplexity", "error": "Model error"},
        ),
        (
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(status="cancelled", error=None),
            ),
            "api_error",
            {"entry": "Perplexity", "error": "response cancelled"},
        ),
    ],
)
async def test_ai_task_stream_terminal_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    chunk: SimpleNamespace,
    translation_key: str,
    placeholders: dict[str, str],
) -> None:
    """Test AI task raises on every non-successful stream terminal."""
    stream = _as_stream([_chunk("response.output_text.delta", delta="partial"), chunk])
    mock_perplexity_client.responses.create = AsyncMock(return_value=stream)

    with pytest.raises(HomeAssistantError) as exc_info:
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
        )

    assert exc_info.value.translation_key == translation_key
    assert exc_info.value.translation_placeholders == placeholders
