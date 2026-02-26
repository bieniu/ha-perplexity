"""Tests for the Perplexity Conversation entity."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components import conversation
from homeassistant.const import CONF_MODEL, Platform
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.helpers.json import json_dumps
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.perplexity.const import CONF_PROMPT, CONF_WEB_SEARCH, DOMAIN
from custom_components.perplexity.conversation import (
    ParsedAction,
    _parse_json_response,
)

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

        state = hass.states.get(entity_entry.entity_id)
        assert state is not None

        state_dict = state._as_dict
        for item in ("context", "last_changed", "last_reported", "last_updated"):
            state_dict.pop(item)
        assert state_dict == snapshot(name=f"{entity_entry.entity_id}-state")


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

    # Verify chat arguments
    call_args = mock_perplexity_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "sonar"
    assert call_args["disable_search"] is True
    assert call_args["stream"] is True

    messages = call_args["messages"]
    assert "script: {}" in messages[0]["content"]
    assert "calendar: {}" in messages[0]["content"]
    assert (
        "entities:\n"
        "  light.living_room:\n"
        "    names: living room\n"
        "    domain: light\n"
        "    state: 'off'"
    ) in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "Turn on the living room light"}
    assert messages[2] == {
        "role": "assistant",
        "content": "I've turned on the living room light for you.",
    }


async def test_conversation_with_actions_and_data(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
    service_calls: list,
) -> None:
    """Test conversation with action that includes extra service data."""
    hass.states.async_set("light.living_room", "off")

    json_response = json_dumps(
        {
            "response": "I've set the brightness to 128.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": {"brightness": 128},
                }
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Set the living room light to 50%",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_on"
    assert service_calls[0].data.get("entity_id") == "light.living_room"
    assert service_calls[0].data.get("brightness") == 128

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


async def test_conversation_web_search_enabled(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_stream: Callable[[str], Any],
) -> None:
    """Test conversation with web search enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        data={"api_key": "test_api_key"},
        subentries_data=[
            {
                "data": {
                    CONF_MODEL: "sonar",
                    CONF_WEB_SEARCH: True,
                    CONF_PROMPT: "You are helpful.",
                },
                "subentry_type": "conversation",
                "title": "Sonar",
                "subentry_id": "ulid-conversation-web",
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
        return_value=mock_stream("Web search result")
    )

    result = await conversation.async_converse(
        hass,
        "What is the weather?",
        None,
        Context(),
        agent_id="conversation.sonar",
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    call_kwargs = mock_perplexity_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["disable_search"] is False


async def test_conversation_with_multiple_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
    service_calls: list,
) -> None:
    """Test conversation with multiple actions in one response."""
    hass.states.async_set("light.living_room", "off")
    hass.states.async_set("light.bedroom", "off")

    json_response = json_dumps(
        {
            "response": "I've turned on both lights.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                },
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.bedroom",
                    "data": None,
                },
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn on all lights",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert len(service_calls) == 2
    assert service_calls[0].data.get("entity_id") == "light.living_room"
    assert service_calls[1].data.get("entity_id") == "light.bedroom"
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


async def test_conversation_with_null_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
    service_calls: list,
) -> None:
    """Test conversation response with null actions (no action needed)."""
    json_response = json_dumps(
        {
            "response": "The weather is sunny today.",
            "actions": None,
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "What's the weather?",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert len(service_calls) == 0
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert "sunny" in result.response.speech["plain"]["speech"].lower()


def test_parse_json_response_invalid_json_in_markdown() -> None:
    """Test parsing invalid JSON in markdown code block."""
    response = "```json\n{invalid json here}\n```"

    result = _parse_json_response(response)

    assert result.content == response
    assert result.actions == []


def test_parse_json_response_content_key_fallback() -> None:
    """Test parsing response with 'content' key instead of 'response'."""
    result = _parse_json_response('{"content": "Hello from content key"}')

    assert result.content == "Hello from content key"
    assert result.actions == []


def test_parse_json_response_non_dict_action_skipped() -> None:
    """Test that non-dict items in actions list are skipped."""
    response = json_dumps(
        {
            "response": "Test",
            "actions": [
                "not a dict",
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.test",
                    "data": None,
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert result.content == "Test"
    assert len(result.actions) == 1
    assert result.actions[0].domain == "light"


def test_parsed_action_str_without_data() -> None:
    """Test ParsedAction string representation without data."""
    action = ParsedAction(domain="light", service="turn_on", target="light.test")

    assert str(action) == "light.turn_on -> light.test ({})"


async def test_conversation_extra_system_prompt(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
) -> None:
    """Test conversation with extra system prompt in action mode."""
    json_response = json_dumps(
        {
            "response": "Done with extra prompt.",
            "actions": None,
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Hello",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
        extra_system_prompt="Extra instruction",
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


async def test_conversation_with_delayed_action(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    mock_stream: MagicMock,
    service_calls: list,
) -> None:
    """Test conversation with action that includes delayed execution."""
    hass.states.async_set("light.living_room", "on")

    json_response = json_dumps(
        {
            "response": "I'll turn off the living room light for 5 minutes.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_off",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": 300,
                }
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn off the living room light for 5 minutes",
        None,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    # No immediate actions
    assert len(service_calls) == 0

    # Fire the timer
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()

    # Delayed action executed
    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_off"
    assert service_calls[0].data.get("entity_id") == "light.living_room"
