"""Tests for the Perplexity config flow."""

from unittest.mock import MagicMock, Mock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL, CONF_PROMPT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import llm
from perplexity import AuthenticationError, PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.config_flow import PerplexityConfigFlow
from custom_components.perplexity.const import (
    CONF_REASONING_EFFORT,
    CONF_WEB_SEARCH,
    DOMAIN,
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
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "test_api_key"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Perplexity"
    assert result["data"] == {CONF_API_KEY: "test_api_key"}


async def test_user_flow_invalid_auth(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test user flow with invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client.chat.completions.create.side_effect = AuthenticationError(
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
) -> None:
    """Test user flow with connection error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client.chat.completions.create.side_effect = PerplexityError(
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


async def test_user_flow_unknown_error(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test user flow with unknown error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client.chat.completions.create.side_effect = RuntimeError(
        "Unknown error"
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


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reauth flow with invalid auth."""
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_perplexity_client.chat.completions.create.side_effect = AuthenticationError(
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
) -> None:
    """Test reauth flow with connection error."""
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_perplexity_client.chat.completions.create.side_effect = PerplexityError(
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


async def test_reauth_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reauth flow with unknown error."""
    result = await mock_config_entry.start_reauth_flow(hass)

    mock_perplexity_client.chat.completions.create.side_effect = RuntimeError(
        "Unknown error"
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


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reconfigure flow with invalid auth."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_perplexity_client.chat.completions.create.side_effect = AuthenticationError(
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
) -> None:
    """Test reconfigure flow with connection error."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_perplexity_client.chat.completions.create.side_effect = PerplexityError(
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


async def test_reconfigure_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test reconfigure flow with unknown error."""
    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_perplexity_client.chat.completions.create.side_effect = RuntimeError(
        "Unknown error"
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
    assert result["errors"] == {"base": "unknown"}


async def test_get_supported_subentry_types(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test async_get_supported_subentry_types returns ai_task_data."""
    subentry_types = PerplexityConfigFlow.async_get_supported_subentry_types(
        mock_config_entry
    )
    assert "ai_task_data" in subentry_types


async def test_ai_task_subentry_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test AI task subentry flow."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, "ai_task_data"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MODEL: "sonar-pro"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sonar Pro"
    assert result["data"] == {CONF_MODEL: "sonar-pro"}


async def test_ai_task_subentry_options_flow_reasoning_model(
    hass: HomeAssistant,
) -> None:
    """Test AI task subentry options flow for reasoning model."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        data={"api_key": "test_api_key"},
    )
    entry.add_to_hass(hass)

    # Create a subentry with reasoning model
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "ai_task_data"),
        context={"source": SOURCE_USER},
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MODEL: "sonar-reasoning-pro"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    subentry_id = next(iter(entry.subentries.keys()))

    subentry = entry.subentries[subentry_id]
    assert subentry.data[CONF_MODEL] == "sonar-reasoning-pro"

    # Now test reconfigure flow
    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_WEB_SEARCH: True, CONF_REASONING_EFFORT: "high"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the options were saved
    subentry = entry.subentries[subentry_id]
    assert subentry.data[CONF_REASONING_EFFORT] == "high"
    assert subentry.data[CONF_WEB_SEARCH] is True


async def test_ai_task_subentry_options_flow_non_reasoning_model(
    hass: HomeAssistant,
) -> None:
    """Test AI task subentry options flow for non-reasoning model."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        data={"api_key": "test_api_key"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "ai_task_data"),
        context={"source": SOURCE_USER},
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MODEL: "sonar"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    subentry_id = next(iter(entry.subentries.keys()))

    # Now test reconfigure flow - should show web_search only
    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_WEB_SEARCH: True},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the option was saved
    subentry = entry.subentries[subentry_id]
    assert subentry.data[CONF_WEB_SEARCH] is True


async def test_get_supported_subentry_types_includes_conversation(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test async_get_supported_subentry_types returns conversation."""
    subentry_types = PerplexityConfigFlow.async_get_supported_subentry_types(
        mock_config_entry
    )
    assert "conversation" in subentry_types


async def test_conversation_subentry_flow(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar-pro",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sonar Pro"
    assert result["data"][CONF_MODEL] == "sonar-pro"
    assert result["data"][CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]


async def test_conversation_subentry_flow_without_assist(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow without LLM assist."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar",
            CONF_LLM_HASS_API: [],  # Explicitly deselect LLM assist
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sonar"
    assert result["data"][CONF_MODEL] == "sonar"
    assert CONF_LLM_HASS_API not in result["data"]


async def test_conversation_subentry_flow_with_prompt(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow with custom prompt."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )

    custom_prompt = "You are a helpful assistant for my smart home."
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar",
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
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Find the conversation subentry
    conversation_subentry_id = None
    for subentry_id, subentry in mock_setup_entry.subentries.items():
        if subentry.subentry_type == "conversation":
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
            CONF_MODEL: "sonar-pro",
            CONF_LLM_HASS_API: [],
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    # Verify the update
    subentry = mock_setup_entry.subentries[conversation_subentry_id]
    assert subentry.data[CONF_MODEL] == "sonar-pro"


async def test_conversation_subentry_flow_entry_not_loaded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow when entry is not loaded."""
    # Don't set up the entry (leave it not loaded)
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


async def test_conversation_subentry_flow_with_web_search(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow with web search enabled."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar",
            CONF_LLM_HASS_API: [],
            CONF_WEB_SEARCH: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WEB_SEARCH] is True


async def test_conversation_subentry_flow_reasoning_model(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry flow with reasoning model and effort."""
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    # Create with reasoning model (reasoning_effort not shown on initial form)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar-reasoning-pro",
            CONF_LLM_HASS_API: [],
            CONF_WEB_SEARCH: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sonar Reasoning Pro"
    assert result["data"][CONF_MODEL] == "sonar-reasoning-pro"
    assert result["data"][CONF_WEB_SEARCH] is True


async def test_conversation_subentry_reconfigure_web_search_and_reasoning(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation subentry reconfigure with web search and reasoning."""
    # Create a conversation subentry with reasoning model
    result = await hass.config_entries.subentries.async_init(
        (mock_setup_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar-reasoning-pro",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
            CONF_WEB_SEARCH: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Find the new conversation subentry
    conversation_subentry_id = None
    for subentry_id, subentry in mock_setup_entry.subentries.items():
        if (
            subentry.subentry_type == "conversation"
            and subentry.data.get(CONF_MODEL) == "sonar-reasoning-pro"
        ):
            conversation_subentry_id = subentry_id
            break

    assert conversation_subentry_id is not None

    # Reconfigure — now reasoning_effort should appear since model is known
    result = await mock_setup_entry.start_subentry_reconfigure_flow(
        hass, conversation_subentry_id
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MODEL: "sonar-reasoning-pro",
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
            CONF_WEB_SEARCH: True,
            CONF_REASONING_EFFORT: "high",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = mock_setup_entry.subentries[conversation_subentry_id]
    assert subentry.data[CONF_WEB_SEARCH] is True
    assert subentry.data[CONF_REASONING_EFFORT] == "high"
