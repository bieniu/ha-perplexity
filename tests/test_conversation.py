"""Tests for the Perplexity Conversation entity."""

from unittest.mock import MagicMock, patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion


async def test_conversation_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test Conversation entity."""
    with (
        patch(
            "custom_components.perplexity.AsyncPerplexity",
            return_value=mock_perplexity_client,
        ),
        patch("custom_components.perplexity.PLATFORMS", [Platform.CONVERSATION]),
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

        state = hass.states.get(entity_entry.entity_id)._as_dict
        for item in ("context", "last_changed", "last_reported", "last_updated"):
            state.pop(item)
        assert state == snapshot(name=f"{entity_entry.entity_id}-state")
