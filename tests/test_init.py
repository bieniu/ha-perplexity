"""Tests for the Perplexity integration."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_MODEL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from perplexity import AuthenticationError, PerplexityError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

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
    mock_perplexity_class: MagicMock,
) -> None:
    """Test successful setup entry."""
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is mock_perplexity_client
    assert mock_perplexity_class.call_args.kwargs["default_headers"] == {
        "X-Pplx-Integration": "ha-perplexity"
    }
    mock_perplexity_client.responses.create.assert_awaited_once_with(
        preset="fast",
        input="hi",
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
    """Test v1 subentries get presets and lose the web search option."""
    legacy = {
        "ulid-sonar": (
            SUBENTRY_TYPE_AI_TASK,
            {CONF_MODEL: "sonar", "web_search": True},
        ),
        "ulid-sonar-pro": (
            SUBENTRY_TYPE_CONVERSATION,
            {
                CONF_MODEL: "sonar-pro",
                CONF_REASONING_EFFORT: "high",
                "web_search": False,
            },
        ),
        "ulid-sonar-reasoning-pro": (
            SUBENTRY_TYPE_AI_TASK,
            {CONF_MODEL: "sonar-reasoning-pro", CONF_REASONING_EFFORT: "high"},
        ),
        "ulid-unknown": (
            SUBENTRY_TYPE_AI_TASK,
            {CONF_MODEL: "unknown-model", "web_search": True},
        ),
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

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert {
        subentry_id: dict(subentry.data)
        for subentry_id, subentry in entry.subentries.items()
    } == {
        "ulid-sonar": {CONF_MODEL: "fast"},
        "ulid-sonar-pro": {CONF_MODEL: "fast", CONF_REASONING_EFFORT: "high"},
        "ulid-sonar-reasoning-pro": {
            CONF_MODEL: "low",
            CONF_REASONING_EFFORT: "high",
        },
        "ulid-unknown": {CONF_MODEL: "unknown-model"},
    }
    # Titles are user-visible names and stay untouched
    assert entry.subentries["ulid-sonar"].title == "ulid-sonar"


@pytest.mark.parametrize("platform", [Platform.AI_TASK, Platform.CONVERSATION])
async def test_platform_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    snapshot: SnapshotAssertion,
    platform: Platform,
) -> None:
    """Test the entity registry entry and state of each platform."""
    with patch("custom_components.perplexity.PLATFORMS", [platform]):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    entity_entries = er.async_entries_for_config_entry(
        er.async_get(hass), mock_config_entry.entry_id
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
