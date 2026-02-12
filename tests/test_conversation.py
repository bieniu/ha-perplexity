"""Tests for the Perplexity Conversation entity."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components import conversation
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.helpers.json import json_dumps
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

CONVERSATION_ENTITY_ID = "conversation.sonar"


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


async def test_conversation_without_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
) -> None:
    """Test basic conversation without actions."""
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream("Hello! How can I help you today?")
    )

    result = await conversation.async_converse(
        hass,
        "Hello",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


async def test_conversation_with_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
    service_calls: list,
) -> None:
    """Test conversation with action execution."""
    hass.states.async_set("light.living_room", "off")

    # Mock the streaming response with JSON containing an action
    json_response = json_dumps(
        {
            "response": "I've turned on the living room light for you.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                }
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn on the living room light",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    # Verify the service was called
    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_on"
    assert service_calls[0].data.get("entity_id") == "light.living_room"

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    # Verify the response text was extracted from JSON
    assert "turned on" in result.response.speech["plain"]["speech"].lower()
