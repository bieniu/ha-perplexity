"""Tests for the Perplexity integration."""

from unittest.mock import MagicMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_MODEL
from homeassistant.core import HomeAssistant
from perplexity import AuthenticationError, PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.const import (
    CONF_REASONING_EFFORT,
    DOMAIN,
    MIN_MAX_TOKENS,
    SUBENTRY_TYPE_AI_TASK,
    SUBENTRY_TYPE_CONVERSATION,
)


async def test_async_setup_entry_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test successful setup entry."""
    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ) as mock_client:
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is mock_perplexity_client
    assert mock_client.call_args.kwargs["default_headers"] == {
        "X-Pplx-Integration": "ha-perplexity"
    }
    mock_perplexity_client.responses.create.assert_awaited_once_with(
        preset="fast",
        input="hi",
        tool_choice="none",
        max_output_tokens=MIN_MAX_TOKENS,
    )


async def test_async_setup_entry_auth_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test setup entry with authentication error."""
    mock_perplexity_client.responses.create.side_effect = AuthenticationError(
        "Invalid API key", response=Mock(), body=None
    )

    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_async_setup_entry_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test setup entry with connection error."""
    mock_perplexity_client.responses.create.side_effect = PerplexityError(
        "Connection error"
    )

    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_async_unload_entry(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test unload entry."""
    assert mock_setup_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_setup_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_setup_entry.state is ConfigEntryState.NOT_LOADED


async def test_async_update_listener(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test update listener reloads entry."""
    assert mock_setup_entry.state is ConfigEntryState.LOADED

    hass.config_entries.async_update_entry(mock_setup_entry, title="Updated Title")
    await hass.async_block_till_done()

    assert mock_setup_entry.state is ConfigEntryState.LOADED
    assert mock_setup_entry.title == "Updated Title"


async def test_migrate_entry_from_v1(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test legacy Sonar models are migrated to Agent API presets."""
    legacy = {
        "ulid-sonar": (SUBENTRY_TYPE_AI_TASK, {CONF_MODEL: "sonar"}),
        "ulid-sonar-pro": (
            SUBENTRY_TYPE_CONVERSATION,
            {CONF_MODEL: "sonar-pro", CONF_REASONING_EFFORT: "high"},
        ),
        "ulid-sonar-reasoning-pro": (
            SUBENTRY_TYPE_AI_TASK,
            {CONF_MODEL: "sonar-reasoning-pro", CONF_REASONING_EFFORT: "high"},
        ),
        "ulid-unknown": (SUBENTRY_TYPE_AI_TASK, {CONF_MODEL: "unknown-model"}),
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        version=1,
        data={CONF_API_KEY: "test_api_key"},
        subentries_data=[
            {
                "data": data,
                "subentry_type": subentry_type,
                "title": subentry_id,
                "subentry_id": subentry_id,
                "unique_id": None,
            }
            for subentry_id, (subentry_type, data) in legacy.items()
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert {
        subentry_id: dict(subentry.data)
        for subentry_id, subentry in entry.subentries.items()
    } == {
        "ulid-sonar": {CONF_MODEL: "fast"},
        "ulid-sonar-pro": {CONF_MODEL: "low", CONF_REASONING_EFFORT: "high"},
        "ulid-sonar-reasoning-pro": {
            CONF_MODEL: "low",
            CONF_REASONING_EFFORT: "high",
        },
        "ulid-unknown": {CONF_MODEL: "unknown-model"},
    }
    # Titles are user-visible names and stay untouched
    assert entry.subentries["ulid-sonar"].title == "ulid-sonar"
