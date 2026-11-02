"""Tests for the Perplexity AI Task entity."""

from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest
from homeassistant.components import ai_task, media_source
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.util.json import JsonValueType
from perplexity import AuthenticationError, PerplexityError
from perplexity._models import construct_type
from perplexity.types import DecisionCreateResponse
from pytest_homeassistant.common import MockConfigEntry

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


QUESTIONS: dict[str, ai_task.EvaluationQuestion] = {
    "rain": {"type": "noul", "instructions": "Will it rain?"},
    "sky": {
        "type": "choice",
        "instructions": "Describe the sky",
        "criteria": {"clear": "No clouds", "cloudy": "Mostly clouds"},
    },
    "severity": {
        "type": "score",
        "instructions": "How bad is the weather?",
        "criteria": ["fine", "unpleasant", "dangerous"],
    },
}

ANSWERS: dict[str, Any] = {
    "rain": {"type": "noul", "noul": 0.8},
    "sky": {
        "type": "choice",
        "choice": "cloudy",
        "confidence": 0.4,
        "probabilities": {"clear": 0.3, "cloudy": 0.7},
    },
    "severity": {
        "type": "score",
        "score": 1.1,
        "confidence": 0.5,
        "legend": {"0": "fine", "1": "unpleasant", "2": "dangerous"},
        "probabilities": {"2": 0.2, "0": 0.1, "1": 0.7},
    },
}


def _decision_response(answers: dict[str, Any]) -> DecisionCreateResponse:
    """Build an SDK decision response from raw answers."""
    return DecisionCreateResponse(
        model="pplx-decider-latest",
        usage={"input_tokens": 10, "output_tokens": 0},
        answers=answers,
    )


async def test_evaluate_answers(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test every question type is sent unchanged and converted back."""
    mock_perplexity_client.decisions.create.return_value = _decision_response(ANSWERS)

    result = await ai_task.async_evaluate(
        hass,
        task_name="Weather check",
        entity_id="ai_task.decider",
        state={"humidity": 95},
        questions=QUESTIONS,
    )

    assert result.answers == {
        "rain": ai_task.NoulAnswer(noul=0.8),
        "sky": ai_task.ChoiceAnswer(
            choice="cloudy", probabilities={"clear": 0.3, "cloudy": 0.7}
        ),
        "severity": ai_task.ScoreAnswer(score=1.1, probabilities=[0.1, 0.7, 0.2]),
    }
    mock_perplexity_client.decisions.create.assert_awaited_once_with(
        model="pplx-decider-latest", questions=QUESTIONS, state={"humidity": 95}
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Overcast", "Overcast"),
        ({"humidity": 95}, {"humidity": 95}),
        (["rain", "wind"], ["rain", "wind"]),
        (42, "42"),
        (True, "true"),
    ],
)
async def test_evaluate_state(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    state: JsonValueType,
    expected: JsonValueType,
) -> None:
    """Test scalar state is serialized, text and JSON containers pass through."""
    mock_perplexity_client.decisions.create.return_value = _decision_response(
        {"rain": ANSWERS["rain"]}
    )

    await ai_task.async_evaluate(
        hass,
        task_name="Weather check",
        entity_id="ai_task.decider",
        state=state,
        questions={"rain": QUESTIONS["rain"]},
    )

    assert mock_perplexity_client.decisions.create.call_args.kwargs["state"] == expected


@pytest.mark.parametrize(
    ("answers", "error"),
    [
        ({**ANSWERS, "extra": ANSWERS["rain"]}, "unexpected answers: extra"),
        (
            {"rain": ANSWERS["rain"], "sky": ANSWERS["sky"]},
            "missing answer for severity",
        ),
        (
            {**ANSWERS, "rain": ANSWERS["sky"]},
            "answer type choice does not match question rain",
        ),
        (
            {**ANSWERS, "sky": {**ANSWERS["sky"], "choice": "overcast"}},
            "invalid choice for sky",
        ),
        (
            {**ANSWERS, "sky": {**ANSWERS["sky"], "probabilities": {"cloudy": 1}}},
            "invalid choice for sky",
        ),
        (
            {**ANSWERS, "severity": {**ANSWERS["severity"], "probabilities": {"0": 1}}},
            "invalid score levels for severity",
        ),
        (
            {
                **ANSWERS,
                "severity": {
                    **ANSWERS["severity"],
                    "probabilities": {"0": 0.5, "1": 0.3, "2": 0.1, "3": 0.1},
                },
            },
            "invalid score levels for severity",
        ),
    ],
)
async def test_evaluate_invalid_response(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    answers: dict[str, Any],
    error: str,
) -> None:
    """Test answers HA cannot use raise a translated error."""
    mock_perplexity_client.decisions.create.return_value = _decision_response(answers)

    with pytest.raises(HomeAssistantError, match="Invalid evaluation response") as exc:
        await ai_task.async_evaluate(
            hass,
            task_name="Weather check",
            entity_id="ai_task.decider",
            state="Overcast",
            questions=QUESTIONS,
        )

    assert exc.value.translation_key == "invalid_evaluation_response"
    assert exc.value.translation_placeholders == {"entry": "Perplexity", "error": error}


async def test_evaluate_malformed_response(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test a score answer without probabilities, built the way the SDK builds it."""
    answers = {**ANSWERS, "severity": {"type": "score", "score": 1.1}}
    mock_perplexity_client.decisions.create.return_value = construct_type(
        type_=DecisionCreateResponse,
        value={"model": "pplx-decider-latest", "answers": answers, "usage": {}},
    )

    with pytest.raises(HomeAssistantError, match="Invalid evaluation response") as exc:
        await ai_task.async_evaluate(
            hass,
            task_name="Weather check",
            entity_id="ai_task.decider",
            state="Overcast",
            questions=QUESTIONS,
        )

    assert exc.value.translation_placeholders == {
        "entry": "Perplexity",
        "error": "malformed answer for severity",
    }


async def test_evaluate_auth_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test an authentication error starts reauth."""
    mock_perplexity_client.decisions.create.side_effect = AuthenticationError(
        "Invalid API key", response=MagicMock(), body=None
    )

    with pytest.raises(HomeAssistantError, match="Authentication failed") as exc:
        await ai_task.async_evaluate(
            hass,
            task_name="Weather check",
            entity_id="ai_task.decider",
            state="Overcast",
            questions=QUESTIONS,
        )

    assert exc.value.translation_key == "auth_error"
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == mock_setup_entry.entry_id


async def test_evaluate_api_error(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test an API error is translated."""
    mock_perplexity_client.decisions.create.side_effect = PerplexityError("Boom")

    with pytest.raises(
        HomeAssistantError, match="Error talking to Perplexity API"
    ) as exc:
        await ai_task.async_evaluate(
            hass,
            task_name="Weather check",
            entity_id="ai_task.decider",
            state="Overcast",
            questions=QUESTIONS,
        )

    assert exc.value.translation_key == "api_error"
    assert exc.value.translation_placeholders == {
        "entry": "Perplexity",
        "error": "Boom",
    }


IMAGE_PART = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,ZmFrZS1wbmc="},
}


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Overcast", ["Overcast", IMAGE_PART]),
        (None, [IMAGE_PART]),
        ({"humidity": 95}, [{"humidity": 95}, IMAGE_PART]),
    ],
)
async def test_evaluate_with_attachment(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    tmp_path: Path,
    state: JsonValueType,
    expected: list[Any],
) -> None:
    """Test image attachments are appended to the state as image parts."""
    image = tmp_path / "image.png"
    image.write_bytes(b"fake-png")
    mock_perplexity_client.decisions.create.return_value = _decision_response(
        {"rain": ANSWERS["rain"]}
    )

    with patch(
        "homeassistant.components.media_source.async_resolve_media",
        return_value=media_source.PlayMedia(
            url="http://example.com/image.png", mime_type="image/png", path=image
        ),
    ):
        await ai_task.async_evaluate(
            hass,
            task_name="Weather check",
            entity_id="ai_task.decider",
            state=state,
            questions={"rain": QUESTIONS["rain"]},
            attachments=[
                {
                    "media_content_id": "media-source://media/image.png",
                    "media_content_type": "image/png",
                }
            ],
        )

    assert mock_perplexity_client.decisions.create.call_args.kwargs["state"] == expected


async def test_evaluate_unsupported_attachment(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    tmp_path: Path,
) -> None:
    """Test a non-image attachment raises before the API is called."""
    document = tmp_path / "notes.txt"
    document.write_text("Overcast")

    with (
        patch(
            "homeassistant.components.media_source.async_resolve_media",
            return_value=media_source.PlayMedia(
                url="http://example.com/notes.txt",
                mime_type="text/plain",
                path=document,
            ),
        ),
        pytest.raises(HomeAssistantError) as exc,
    ):
        await ai_task.async_evaluate(
            hass,
            task_name="Weather check",
            entity_id="ai_task.decider",
            questions=QUESTIONS,
            attachments=[
                {
                    "media_content_id": "media-source://media/notes.txt",
                    "media_content_type": "text/plain",
                }
            ],
        )

    assert exc.value.translation_key == "unsupported_file_type"
    mock_perplexity_client.decisions.create.assert_not_awaited()
