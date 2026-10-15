"""Tests for the Perplexity config flow."""

from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
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
    CONF_REASONING_EFFORT,
    DOMAIN,
    MIN_MAX_TOKENS,
    SUBENTRY_TYPE_AI_TASK,
    SUBENTRY_TYPE_CONVERSATION,
)


async def test_user_flow_success(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test successful user flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ) as mock_client:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Perplexity"
    assert result["data"] == {CONF_API_KEY: "test_api_key"}
    assert mock_client.call_args.kwargs["default_headers"] == {
        "X-Pplx-Integration": "ha-perplexity"
    }
    mock_perplexity_client.responses.create.assert_awaited_with(
        preset="fast",
        input="hi",
        max_output_tokens=MIN_MAX_TOKENS,
    )


async def test_user_flow_invalid_auth(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test user flow with invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client.responses.create.side_effect = AuthenticationError(
        "Invalid API key", response=Mock(), body=None
    )

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "invalid_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test user flow with connection error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client.responses.create.side_effect = PerplexityError(
        "Connection error"
    )

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "Unable to connect to Perplexity API: Connection error" in caplog.text


async def test_user_flow_unknown_error(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test user flow with unknown error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client.responses.create.side_effect = RuntimeError("Unknown error")

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


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


async def test_reauth_flow_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test successful reauth flow."""
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "new_api_key"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "new_api_key"
    await hass.async_block_till_done()


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reauth flow with invalid auth."""
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_perplexity_client.responses.create.side_effect = AuthenticationError(
        "Invalid API key", response=Mock(), body=None
    )

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "invalid_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test reauth flow with connection error."""
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_perplexity_client.responses.create.side_effect = PerplexityError(
        "Connection error"
    )

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "Unable to connect to Perplexity API: Connection error" in caplog.text


async def test_reauth_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reauth flow with unknown error."""
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_perplexity_client.responses.create.side_effect = RuntimeError("Unknown error")

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_reconfigure_flow_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test successful reconfigure flow."""
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "new_api_key"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "new_api_key"
    await hass.async_block_till_done()


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reconfigure flow with invalid auth."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_perplexity_client.responses.create.side_effect = AuthenticationError(
        "Invalid API key", response=Mock(), body=None
    )

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "invalid_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test reconfigure flow with connection error."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_perplexity_client.responses.create.side_effect = PerplexityError(
        "Connection error"
    )

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "Unable to connect to Perplexity API: Connection error" in caplog.text


async def test_reconfigure_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reconfigure flow with unknown error."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_perplexity_client.responses.create.side_effect = RuntimeError("Unknown error")

    with patch(
        "custom_components.perplexity.config_flow.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_get_supported_subentry_types(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test async_get_supported_subentry_types returns ai_task_data."""
    subentry_types = PerplexityConfigFlow.async_get_supported_subentry_types(
        mock_config_entry
    )
    assert SUBENTRY_TYPE_AI_TASK in subentry_types


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


async def test_get_supported_subentry_types_includes_conversation(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test async_get_supported_subentry_types returns conversation."""
    subentry_types = PerplexityConfigFlow.async_get_supported_subentry_types(
        mock_config_entry
    )
    assert SUBENTRY_TYPE_CONVERSATION in subentry_types


async def test_conversation_subentry_flow(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "medium",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Medium"
    assert result["data"][CONF_MODEL] == "medium"
    assert result["data"][CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]
    assert CONF_REASONING_EFFORT not in result["data"]


async def test_conversation_subentry_flow_without_assist(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow without LLM assist."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "fast",
            CONF_LLM_HASS_API: [],  # Explicitly deselect LLM assist
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Fast"
    assert result["data"][CONF_MODEL] == "fast"
    assert result["data"][CONF_LLM_HASS_API] == []


async def test_conversation_subentry_flow_with_prompt(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow with custom prompt."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )

    custom_prompt = "You are a helpful assistant for my smart home."
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "fast",
            CONF_PROMPT: custom_prompt,
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROMPT] == custom_prompt


async def test_conversation_subentry_reconfigure_flow(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry reconfigure flow."""
    # First create a conversation subentry
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "fast",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Find the conversation subentry
    conversation_subentry_id = None
    for subentry_id, subentry in mock_setup_entry.subentries.items():
        if subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION:
            conversation_subentry_id = subentry_id
            break

    assert conversation_subentry_id is not None

    # Reconfigure
    result = await mock_setup_entry.start_subentry_reconfigure_flow(
        hass, conversation_subentry_id
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    # Update with new model
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "medium",
            CONF_LLM_HASS_API: [],
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the update
    subentry = mock_setup_entry.subentries[conversation_subentry_id]
    assert subentry.data[CONF_MODEL] == "medium"


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


async def test_conversation_subentry_flow_reasoning_model(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow with reasoning effort."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    assert (schema := result["data_schema"]) is not None
    assert CONF_REASONING_EFFORT in schema.schema

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "high",
            CONF_LLM_HASS_API: [],
            CONF_REASONING_EFFORT: "xhigh",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "High"
    assert result["data"][CONF_MODEL] == "high"
    assert result["data"][CONF_REASONING_EFFORT] == "xhigh"


async def test_conversation_subentry_reconfigure_reasoning(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry reconfigure sets reasoning effort."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "low",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Find the new conversation subentry
    conversation_subentry_id = None
    for subentry_id, subentry in mock_setup_entry.subentries.items():
        if (
            subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION
            and subentry.data.get(CONF_MODEL) == "low"
        ):
            conversation_subentry_id = subentry_id
            break

    assert conversation_subentry_id is not None

    result = await mock_setup_entry.start_subentry_reconfigure_flow(
        hass, conversation_subentry_id
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "low",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
            CONF_REASONING_EFFORT: "high",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = mock_setup_entry.subentries[conversation_subentry_id]
    assert subentry.data[CONF_REASONING_EFFORT] == "high"
