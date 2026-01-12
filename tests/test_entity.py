"""Tests for the Perplexity entity module."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from perplexity import PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.entity import (
    _adjust_schema,
    _async_prepare_files_for_prompt,
    _convert_content_to_chat_message,
    _format_structured_output,
)


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
    schema = vol.Schema({vol.Required("key"): str})
    result = _format_structured_output("test_name", schema, None)

    assert result["type"] == "json_schema"
    assert result["json_schema"]["name"] == "test_name"
    assert result["json_schema"]["strict"] is True
    assert "schema" in result["json_schema"]


def test_format_structured_output_with_llm_api() -> None:
    """Test _format_structured_output with LLM API."""
    schema = vol.Schema({vol.Required("key"): str})
    mock_llm_api = MagicMock()
    mock_llm_api.custom_serializer = llm.selector_serializer

    result = _format_structured_output("test_name", schema, mock_llm_api)

    assert result["type"] == "json_schema"
    assert result["json_schema"]["name"] == "test_name"


def test_convert_content_system() -> None:
    """Test _convert_content_to_chat_message with system content."""
    content = conversation.SystemContent(
        content="You are a helpful assistant.",
    )

    result = _convert_content_to_chat_message(content)

    assert result["role"] == "system"
    assert result["content"] == "You are a helpful assistant."


def test_convert_content_user() -> None:
    """Test _convert_content_to_chat_message with user content."""
    content = conversation.UserContent(
        content="Hello!",
    )

    result = _convert_content_to_chat_message(content)

    assert result["role"] == "user"
    assert result["content"] == "Hello!"


def test_convert_content_assistant() -> None:
    """Test _convert_content_to_chat_message with assistant content."""
    content = conversation.AssistantContent(
        agent_id="test_agent",
        content="Hello! How can I help?",
    )

    result = _convert_content_to_chat_message(content)

    assert result["role"] == "assistant"
    assert result["content"] == "Hello! How can I help?"


def test_convert_content_unknown_role() -> None:
    """Test _convert_content_to_chat_message with unknown role."""
    content = MagicMock()
    content.role = "unknown"
    content.content = "test"

    result = _convert_content_to_chat_message(content)

    assert result is None


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
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")


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
    assert result[0]["type"] == "image_url"
    assert "base64," in result[0]["image_url"]["url"]


async def test_ai_task_api_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task with Perplexity API error."""
    mock_perplexity_client.chat.completions.create.side_effect = PerplexityError(
        "API Error"
    )

    with pytest.raises(HomeAssistantError, match="Error talking to Perplexity API"):
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.sonar",
            instructions="Test instructions",
        )
