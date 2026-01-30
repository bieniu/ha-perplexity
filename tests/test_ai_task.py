"""Tests for the Perplexity AI Task entity."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.components import ai_task
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.perplexity.const import CONF_WEB_SEARCH, DOMAIN


async def test_ai_task_entity(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test AI task entity."""
    entity_registry = er.async_get(hass)

    entity_entries = er.async_entries_for_config_entry(
        entity_registry, mock_setup_entry.entry_id
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


async def test_ai_task_generate_data_without_structure(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task generate data without structure."""
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream("Test response")
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.sonar",
        instructions="Test instructions",
    )

    assert result.data == "Test response"


async def test_ai_task_generate_data_with_structure(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task generate data with structure."""
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream('{"key": "value"}')
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.sonar",
        instructions="Test instructions",
        structure=vol.Schema({vol.Required("key"): str}),
    )

    assert result.data == {"key": "value"}


async def test_ai_task_generate_data_invalid_json(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task generate data with invalid JSON response."""
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream("invalid json")
    )

    with pytest.raises(
        HomeAssistantError, match="Error with Perplexity structured response"
    ):
        await ai_task.async_generate_data(
            hass,
            task_name="Test task",
            entity_id="ai_task.sonar",
            instructions="Test instructions",
            structure=vol.Schema({vol.Required("key"): str}),
        )


async def test_ai_task_web_search_disabled_by_default(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task has web search disabled by default."""
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream("Test response")
    )

    await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.sonar",
        instructions="Test instructions",
    )

    call_kwargs = mock_perplexity_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["disable_search"] is True


async def test_ai_task_web_search_enabled(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test AI task with web search enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        data={"api_key": "test_api_key"},
        subentries_data=[
            {
                "data": {CONF_MODEL: "sonar", CONF_WEB_SEARCH: True},
                "subentry_type": "ai_task_data",
                "title": "Sonar",
                "subentry_id": "ulid-ai-task-web",
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream("Test response with web search")
    )

    result = await ai_task.async_generate_data(
        hass,
        task_name="Test task",
        entity_id="ai_task.sonar",
        instructions="Test instructions",
    )

    assert result.data == "Test response with web search"

    call_kwargs = mock_perplexity_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["disable_search"] is False
