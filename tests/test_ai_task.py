"""Tests for the Perplexity AI Task entity."""

from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest
from homeassistant.components import ai_task, media_source
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from perplexity import PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.const import (
    CONF_REASONING_EFFORT,
    DOMAIN,
    SUBENTRY_TYPE_AI_TASK,
    WEB_SEARCH_ADDITIONAL_INSTRUCTION,
)

from .conftest import create_mock_stream


async def test_ai_task_generate_data_without_structure(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task generate data without structure."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("Test response")
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Test instructions",
    )

    assert result.data == "Test response"


@pytest.mark.parametrize(
    ("task_name", "expected_name"),
    [("Test task", "Test_task"), ("a" * 70, "a" * 64), ("żółw", "___w")],
)
async def test_ai_task_generate_data_with_structure(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    task_name: str,
    expected_name: str,
) -> None:
    """Test AI task generate data with structure."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream('{"key": "value"}')
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name=task_name,
        entity_id="ai_task.fast",
        instructions="Test instructions",
        structure=probatio.Schema({probatio.Required("key"): str}),
    )

    assert result.data == {"key": "value"}
    response_format = mock_perplexity_client.responses.create.call_args.kwargs[
        "response_format"
    ]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == expected_name


async def test_ai_task_generate_data_invalid_json(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task generate data with invalid JSON response."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("invalid json")
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
    ("subentry_data", "expected_reasoning"),
    [
        ({}, None),
        ({CONF_REASONING_EFFORT: "high"}, {"effort": "high"}),
        ({CONF_REASONING_EFFORT: "xhigh"}, {"effort": "xhigh"}),
    ],
)
async def test_ai_task_request_args(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    subentry_data: dict[str, Any],
    expected_reasoning: dict[str, str] | None,
) -> None:
    """Test the Agent API arguments for the reasoning options."""
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

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("Test response")
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
    assert "tool_choice" not in call_kwargs
    assert "tools" not in call_kwargs
    assert call_kwargs.get("reasoning") == expected_reasoning
    assert call_kwargs["instructions"].endswith(WEB_SEARCH_ADDITIONAL_INSTRUCTION)
    assert call_kwargs["input"][0] == {
        "type": "message",
        "role": "user",
        "content": "Test instructions",
    }


async def test_ai_task_request_args_with_llm_api(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test tools and the structure are sent together when an API is given."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream('{"name": "kitchen"}')
    )
    assist_api = next(api for api in llm.async_get_apis(hass) if api.id == "assist")

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.fast",
        instructions="Which room is this?",
        structure=probatio.Schema({probatio.Required("name"): str}),
        llm_api=assist_api,
    )

    assert result.data == {"name": "kitchen"}

    call_kwargs = mock_perplexity_client.responses.create.call_args.kwargs
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert "llm__GetDateTime" in [tool["name"] for tool in call_kwargs["tools"]]


async def _failed_stream() -> AsyncGenerator[MagicMock]:
    """Yield a partial delta, then a failed response event."""
    yield MagicMock(type="response.output_text.delta", delta="partial")
    failed = MagicMock(type="response.failed")
    failed.error.message = "Something broke"
    yield failed


async def _broken_stream() -> AsyncGenerator[MagicMock]:
    """Yield a partial delta, then fail with an SDK error."""
    yield MagicMock(type="response.output_text.delta", delta="partial")
    raise PerplexityError("Connection lost")


@pytest.mark.parametrize(
    ("stream_factory", "error"),
    [(_failed_stream, "Something broke"), (_broken_stream, "Connection lost")],
)
async def test_ai_task_stream_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    stream_factory: Callable[[], AsyncGenerator[MagicMock]],
    error: str,
) -> None:
    """Test AI task raises when the stream fails mid-response."""
    mock_perplexity_client.responses.create = AsyncMock(return_value=stream_factory())

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
        "error": error,
    }


async def test_ai_task_no_assistant_response(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test AI task raises when the stream contains no text."""

    async def _empty_stream() -> AsyncGenerator[MagicMock]:
        yield MagicMock(type="response.created")
        yield MagicMock(
            type="response.completed", response=MagicMock(status="completed")
        )

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


@pytest.mark.parametrize(
    ("instructions", "expected_text"),
    [
        ("Describe the image", [{"type": "input_text", "text": "Describe the image"}]),
        ("", []),
    ],
)
async def test_ai_task_generate_data_with_attachment(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    tmp_path: Path,
    instructions: str,
    expected_text: list[dict[str, str]],
) -> None:
    """Test image attachments are sent as Agent API input parts."""
    image = tmp_path / "image.png"
    image.write_bytes(b"fake-png")
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("A cat")
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
            instructions=instructions,
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
            *expected_text,
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,ZmFrZS1wbmc=",
            },
        ],
    }
