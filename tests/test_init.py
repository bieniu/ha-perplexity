"""Tests for the Perplexity integration."""

from unittest.mock import MagicMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from perplexity import AuthenticationError, PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_async_setup_entry_success(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test successful setup entry."""
    assert mock_setup_entry.state is ConfigEntryState.LOADED
    assert mock_setup_entry.runtime_data is mock_perplexity_client


async def test_async_setup_entry_auth_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test setup entry with authentication error."""
    mock_perplexity_client.chat.completions.create.side_effect = AuthenticationError(
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
    mock_perplexity_client.chat.completions.create.side_effect = PerplexityError(
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
