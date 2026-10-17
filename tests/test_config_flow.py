"""Tests for the Perplexity config flow."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL, CONF_PROMPT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import llm
from perplexity import AuthenticationError, PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.config_flow import (
    PerplexityConfigFlow,
)
from custom_components.perplexity.const import (
    CONF_INCLUDE_HOME_LOCATION,
    CONF_REASONING_EFFORT,
    DOMAIN,
    MIN_MAX_TOKENS,
    SUBENTRY_TYPE_AI_TASK,
    SUBENTRY_TYPE_CONVERSATION,
)


async def _start_user(hass: HomeAssistant, entry: MockConfigEntry) -> ConfigFlowResult:
    """Start the user flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def _start_reauth(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ConfigFlowResult:
    """Start the reauth flow."""
    return await entry.start_reauth_flow(hass)


async def _start_reconfigure(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ConfigFlowResult:
    """Start the reconfigure flow."""
    return await entry.start_reconfigure_flow(hass)


@pytest.mark.parametrize(
    ("start", "step_id", "result_type", "reason"),
    [
        (_start_user, "user", FlowResultType.CREATE_ENTRY, None),
        (_start_reauth, "reauth_confirm", FlowResultType.ABORT, "reauth_successful"),
        (
            _start_reconfigure,
            "reconfigure",
            FlowResultType.ABORT,
            "reconfigure_successful",
        ),
    ],
)
async def test_flow_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_perplexity_class: MagicMock,
    start: Callable[[HomeAssistant, MockConfigEntry], Awaitable[ConfigFlowResult]],
    step_id: str,
    result_type: FlowResultType,
    reason: str | None,
) -> None:
    """Test successful user, reauth and reconfigure flows."""
    result = await start(hass, mock_config_entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step_id

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_API_KEY: "new_api_key"},
    )
    await hass.async_block_till_done()

    assert result["type"] is result_type
    assert result.get("reason") == reason
    assert mock_perplexity_class.call_args.kwargs["default_headers"] == {
        "X-Pplx-Integration": "ha-perplexity"
    }
    mock_perplexity_client.responses.create.assert_awaited_with(
        preset="fast",
        input="hi",
        max_output_tokens=MIN_MAX_TOKENS,
    )


@pytest.mark.parametrize("start", [_start_user, _start_reauth, _start_reconfigure])
@pytest.mark.parametrize(
    ("side_effect", "expected_error", "expected_logs"),
    [
        (
            AuthenticationError("Invalid API key", response=Mock(), body=None),
            "invalid_auth",
            [],
        ),
        (
            PerplexityError("Connection error"),
            "cannot_connect",
            ["Unable to connect to Perplexity API: Connection error"],
        ),
        (RuntimeError("Unknown error"), "unknown", ["Unexpected exception"]),
    ],
)
async def test_flow_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
    start: Callable[[HomeAssistant, MockConfigEntry], Awaitable[ConfigFlowResult]],
    side_effect: Exception,
    expected_error: str,
    expected_logs: list[str],
) -> None:
    """Test user, reauth and reconfigure flows surface API errors."""
    result = await start(hass, mock_config_entry)
    mock_perplexity_client.responses.create.side_effect = side_effect

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_API_KEY: "new_api_key"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}
    logger = f"custom_components.{DOMAIN}"
    assert [r.message for r in caplog.records if r.name == logger] == expected_logs


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test user flow when already configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_API_KEY: "test_api_key"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_get_supported_subentry_types(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test async_get_supported_subentry_types returns AI task and conversation."""
    subentry_types = PerplexityConfigFlow.async_get_supported_subentry_types(
        mock_config_entry
    )
    assert set(subentry_types) == {SUBENTRY_TYPE_AI_TASK, SUBENTRY_TYPE_CONVERSATION}


async def test_ai_task_subentry_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test AI task subentry flow."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_AI_TASK),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MODEL: "medium"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Medium"
    assert result["data"] == {CONF_MODEL: "medium"}


@pytest.mark.parametrize(
    ("initial_data", "user_input", "expected_data"),
    [
        ({CONF_MODEL: "fast"}, {}, {CONF_MODEL: "fast"}),
        (
            {CONF_MODEL: "low"},
            {CONF_REASONING_EFFORT: "xhigh"},
            {CONF_MODEL: "low", CONF_REASONING_EFFORT: "xhigh"},
        ),
        (
            {CONF_MODEL: "high", CONF_REASONING_EFFORT: "high"},
            {},
            {CONF_MODEL: "high"},
        ),
    ],
)
async def test_ai_task_subentry_reconfigure_flow(
    hass: HomeAssistant,
    initial_data: dict[str, Any],
    user_input: dict[str, Any],
    expected_data: dict[str, Any],
) -> None:
    """Test AI task reconfigure stores reasoning effort only when one is chosen."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        version=2,
        data={"api_key": "test_api_key"},
        subentries_data=[
            {
                "data": initial_data,
                "subentry_type": SUBENTRY_TYPE_AI_TASK,
                "title": "AI task",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    subentry_id = next(iter(entry.subentries))

    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert (schema := result["data_schema"]) is not None
    assert CONF_REASONING_EFFORT in schema.schema

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert dict(entry.subentries[subentry_id].data) == expected_data


@pytest.mark.parametrize(
    ("user_input", "title"),
    [
        ({CONF_MODEL: "medium", CONF_LLM_HASS_API: [llm.LLM_API_ASSIST]}, "Medium"),
        ({CONF_MODEL: "fast", CONF_LLM_HASS_API: []}, "Fast"),
        (
            {
                CONF_MODEL: "fast",
                CONF_PROMPT: "You are a helpful assistant for my smart home.",
                CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
            },
            "Fast",
        ),
        (
            {
                CONF_MODEL: "high",
                CONF_LLM_HASS_API: [],
                CONF_REASONING_EFFORT: "xhigh",
            },
            "High",
        ),
    ],
)
async def test_conversation_subentry_flow(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    user_input: dict[str, Any],
    title: str,
) -> None:
    """Test conversation subentry flow stores exactly the submitted options."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert (schema := result["data_schema"]) is not None
    assert CONF_REASONING_EFFORT in schema.schema

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == title
    assert result["data"] == {**user_input, CONF_INCLUDE_HOME_LOCATION: False}


@pytest.mark.parametrize(
    "user_input",
    [
        {CONF_MODEL: "medium", CONF_LLM_HASS_API: []},
        {
            CONF_MODEL: "low",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
            CONF_REASONING_EFFORT: "high",
        },
    ],
)
async def test_conversation_subentry_reconfigure_flow(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    user_input: dict[str, Any],
) -> None:
    """Test conversation subentry reconfigure flow."""
    result = await mock_setup_entry.start_subentry_reconfigure_flow(
        hass, "ulid-conversation"
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    data = dict(mock_setup_entry.subentries["ulid-conversation"].data)
    assert data == {**user_input, CONF_INCLUDE_HOME_LOCATION: False}


async def test_conversation_subentry_flow_entry_not_loaded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow when entry is not loaded."""
    # Don't set up the entry (leave it not loaded)
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"
