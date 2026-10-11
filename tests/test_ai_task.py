"""Tests for the Perplexity AI Task entity."""

from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest
from homeassistant.components import ai_task, media_source
from homeassistant.const import CONF_MODEL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from perplexity import PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.perplexity.const import (
    CONF_REASONING_EFFORT,
    CONF_WEB_SEARCH,
    DOMAIN,
    SUBENTRY_TYPE_AI_TASK,
    WEB_SEARCH_ADDITIONAL_INSTRUCTION,
)


async def test_ai_task_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test AI task entity."""
    with (
        patch(
            "custom_components.perplexity.AsyncPerplexity",
            return_value=mock_perplexity_client,
        ),
        patch("custom_components.perplexity.PLATFORMS", [Platform.AI_TASK]),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)

    entity_entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )

    assert len(entity_entries) == 1

    for entity_entry in entity_entries:
        entity_entry_dict = entity_entry.as_partial_dict
        for item in (
            "area_id",
            "categories",
            "config_entry_id",
            "created_at",
            "device_id",
            "hidden_by",
            "id",
            "labels",
            "modified_at",
        ):
            entity_entry_dict.pop(item)
        assert entity_entry_dict == snapshot(name=f"{entity_entry.entity_id}-entry")

        state = hass.states.get(entity_entry.entity_id)
        assert state is not None

        state_dict = state._as_dict
        for item in ("context", "last_changed", "last_reported", "last_updated"):
            state_dict.pop(item)
        assert state_dict == snapshot(name=f"{entity_entry.entity_id}-state")


async def test_ai_task_generate_data_without_structure(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task generate data without structure."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream("Test response")
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Test instructions",
    )

    assert result.data == "Test response"


async def test_ai_task_generate_data_without_structure_strips_reasoning(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task strips reasoning blocks from plain text responses."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream("<think>\nReasoning here\n</think>\n\nVisible answer")
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Test instructions",
    )

    assert result.data == "Visible answer"


async def test_ai_task_generate_data_with_structure(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task generate data with structure."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream('{"key": "value"}')
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Test instructions",
        structure=probatio.Schema({probatio.Required("key"): str}),
    )

    assert result.data == {"key": "value"}
    response_format = mock_perplexity_client.responses.create.call_args.kwargs[
        "response_format"
    ]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Test task"


async def test_ai_task_generate_data_with_structure_strips_reasoning(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task strips reasoning blocks before parsing structured data."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream('<think>\nReasoning here\n</think>\n{"key": "value"}')
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Test instructions",
        structure=probatio.Schema({probatio.Required("key"): str}),
    )

    assert result.data == {"key": "value"}


async def test_ai_task_generate_data_invalid_json(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task generate data with invalid JSON response."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream("invalid json")
    )

    with pytest.raises(
        HomeAssistantError, match="Error with Perplexity structured response"
    ):
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
            structure=probatio.Schema({probatio.Required("key"): str}),
        )


@pytest.mark.parametrize(
    ("subentry_data", "expected_tool_choice", "expected_reasoning", "citations"),
    [
        ({}, "none", None, False),
        ({CONF_WEB_SEARCH: True}, None, None, True),
        ({CONF_REASONING_EFFORT: "high"}, "none", {"effort": "high"}, False),
        (
            {CONF_WEB_SEARCH: True, CONF_REASONING_EFFORT: "xhigh"},
            None,
            {"effort": "xhigh"},
            True,
        ),
    ],
)
async def test_ai_task_request_args(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
    subentry_data: dict[str, Any],
    expected_tool_choice: str | None,
    expected_reasoning: dict[str, str] | None,
    citations: bool,
) -> None:
    """Test the Agent API arguments depend on web search and reasoning options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        version=2,
        data={"api_key": "test_api_key"},
        subentries_data=[
            {
                "data": {CONF_MODEL: "medium", **subentry_data},
                "subentry_type": SUBENTRY_TYPE_AI_TASK,
                "title": "Medium",
                "subentry_id": "ulid-ai-task",
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream("Test response")
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.medium",
        instructions="Test instructions",
    )

    assert result.data == "Test response"

    call_kwargs = mock_perplexity_client.responses.create.call_args.kwargs
    assert call_kwargs["preset"] == "medium"
    assert call_kwargs["stream"] is True
    assert call_kwargs.get("tool_choice") == expected_tool_choice
    assert call_kwargs.get("reasoning") == expected_reasoning
    assert (
        WEB_SEARCH_ADDITIONAL_INSTRUCTION in call_kwargs["instructions"]
    ) is citations
    assert call_kwargs["input"][0] == {
        "type": "message",
        "role": "user",
        "content": "Test instructions",
    }


async def test_ai_task_stream_failed(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task raises when the stream reports a failed response."""

    async def _failed_stream() -> AsyncGenerator[MagicMock]:
        yield MagicMock(type="response.output_text.delta", delta="partial")
        failed = MagicMock(type="response.failed")
        failed.error.message = "Something broke"
        yield failed

    mock_perplexity_client.responses.create = AsyncMock(return_value=_failed_stream())

    with pytest.raises(
        HomeAssistantError, match="Error talking to Perplexity API"
    ) as exc_info:
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
        )

    assert exc_info.value.translation_key == "api_error"
    assert exc_info.value.translation_placeholders == {
        "entry": "Perplexity",
        "error": "Something broke",
    }


async def test_ai_task_stream_sdk_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task raises when the SDK fails mid-stream."""

    async def _broken_stream() -> AsyncGenerator[MagicMock]:
        yield MagicMock(type="response.output_text.delta", delta="partial")
        raise PerplexityError("Connection lost")

    mock_perplexity_client.responses.create = AsyncMock(return_value=_broken_stream())

    with pytest.raises(
        HomeAssistantError, match="Error talking to Perplexity API"
    ) as exc_info:
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
        )

    assert exc_info.value.translation_key == "api_error"
    assert exc_info.value.translation_placeholders == {
        "entry": "Perplexity",
        "error": "Connection lost",
    }


async def test_ai_task_no_assistant_response(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task raises when the stream contains no text."""

    async def _empty_stream() -> AsyncGenerator[MagicMock]:
        yield MagicMock(type="response.created")
        yield MagicMock(type="response.completed")

    mock_perplexity_client.responses.create = AsyncMock(return_value=_empty_stream())

    with pytest.raises(
        HomeAssistantError,
        match="Last content in chat log is not an AssistantContent",
    ):
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Test instructions",
        )


async def test_ai_task_generate_data_with_attachment(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
    tmp_path: Path,
) -> None:
    """Test image attachments are sent as Agent API input parts."""
    image = tmp_path / "image.png"
    image.write_bytes(b"fake-png")
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=mock_stream("A cat")
    )

    with patch(
        "homeassistant.components.media_source.async_resolve_media",
        return_value=media_source.PlayMedia(
            url="http://example.com/image.png", mime_type="image/png", path=image
        ),
    ):
        result = await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.fast",
            instructions="Describe the image",
            attachments=[
                {
                    "media_content_id": "media-source://media/image.png",
                    "media_content_type": "image/png",
                }
            ],
        )

    assert result.data == "A cat"
    call_kwargs = mock_perplexity_client.responses.create.call_args.kwargs
    assert call_kwargs["input"][0] == {
        "type": "message",
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Describe the image"},
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,ZmFrZS1wbmc=",
            },
        ],
    }
