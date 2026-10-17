"""Tests for the Perplexity Conversation entity."""

import copy
import logging
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components import conversation
from homeassistant.components.conversation.chat_log import async_get_chat_log
from homeassistant.const import (
    CONF_LLM_HASS_API,
    CONF_MODEL,
    CONF_PROMPT,
    MATCH_ALL,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent, llm
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.helpers.json import json_dumps
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.perplexity.const import (
    CONF_INCLUDE_HOME_LOCATION,
    DOMAIN,
    SUBENTRY_TYPE_CONVERSATION,
    WEB_SEARCH_ADDITIONAL_INSTRUCTION,
)
from custom_components.perplexity.entity import MAX_TOOL_ITERATIONS

from .conftest import (
    create_mock_stream,
    expose_light,
    function_call_item,
    message_item,
    output_item_events,
)

CONVERSATION_ENTITY_ID = "conversation.fast"

TURN_ON_ARGUMENTS = json_dumps(
    {"name": "living room", "domain": ["light"], "area": "", "floor": ""}
)


async def _setup_conversation_entry(
    hass: HomeAssistant, mock_perplexity_client: MagicMock, data: dict[str, Any]
) -> MockConfigEntry:
    """Set up an entry with a single conversation subentry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        version=2,
        data={"api_key": "test_api_key"},
        subentries_data=[
            {
                "data": {CONF_MODEL: "fast", **data},
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Fast",
                "subentry_id": "ulid-conversation-custom",
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


def _record_requests(
    mock_perplexity_client: MagicMock, streams: list[AsyncGenerator[Any]]
) -> list[dict[str, Any]]:
    """Serve the given streams in order and record the request arguments."""
    sent_kwargs: list[dict[str, Any]] = []

    async def _create(**kwargs: object) -> AsyncGenerator[Any]:
        sent_kwargs.append(copy.deepcopy(kwargs))
        return streams.pop(0)

    mock_perplexity_client.responses.create = AsyncMock(side_effect=_create)
    return sent_kwargs


async def _converse(hass: HomeAssistant, text: str) -> conversation.ConversationResult:
    """Send text to the conversation agent."""
    return await conversation.async_converse(
        hass, text, None, Context(), agent_id=CONVERSATION_ENTITY_ID
    )


async def test_conversation_agent_info(
    hass: HomeAssistant,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test the conversation agent supports streaming and all languages."""
    agent_info = conversation.async_get_agent_info(hass, CONVERSATION_ENTITY_ID)
    assert agent_info is not None
    assert agent_info.supports_streaming is True
    agent = conversation.async_get_agent(hass, CONVERSATION_ENTITY_ID)
    assert agent is not None
    assert agent.supported_languages == MATCH_ALL


async def test_conversation_llm_api_error(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test an unknown API id ends the turn before calling Perplexity."""
    await _setup_conversation_entry(
        hass, mock_perplexity_client, {CONF_LLM_HASS_API: ["missing_api"]}
    )
    # Setup validates the key with one request, only that call is expected
    mock_perplexity_client.responses.create.reset_mock()

    result = await _converse(hass, "Hello")

    assert result.response.response_type == intent.IntentResponseType.ERROR
    assert result.response.speech["plain"]["speech"] == "Error preparing LLM API"
    mock_perplexity_client.responses.create.assert_not_called()


async def test_conversation_text_response(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test a plain text answer is returned as speech."""
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("Hello! How can I help you today?")
    )

    result = await _converse(hass, "Hello")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert result.response.speech["plain"]["speech"] == (
        "Hello! How can I help you today?"
    )


async def test_conversation_tools_sent(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test the Assist API tools are sent as function tools."""
    expose_light(hass)
    sent_kwargs = _record_requests(mock_perplexity_client, [create_mock_stream("Hi")])

    await _converse(hass, "Hello")

    call_args = sent_kwargs[0]
    assert call_args["preset"] == "fast"
    assert "response_format" not in call_args
    assert "tool_choice" not in call_args
    tools = {tool["name"]: tool for tool in call_args["tools"]}
    assert {
        "intent__HassTurnOn",
        "homeassistant__GetLiveContext",
        "llm__GetDateTime",
    } <= set(tools)
    turn_on = tools["intent__HassTurnOn"]
    assert turn_on["type"] == "function"
    assert turn_on["strict"] is False
    assert turn_on["description"]
    assert turn_on["parameters"]["type"] == "object"
    assert "name" in turn_on["parameters"]["properties"]
    assert call_args["input"] == [
        {"type": "message", "role": "user", "content": "Hello"},
    ]


async def test_conversation_without_llm_api(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test no tools are sent and no control feature is set without an API."""
    await _setup_conversation_entry(
        hass, mock_perplexity_client, {CONF_PROMPT: "You are helpful."}
    )
    sent_kwargs = _record_requests(mock_perplexity_client, [create_mock_stream("Hi")])

    result = await _converse(hass, "Hello")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert "tools" not in sent_kwargs[0]
    state = hass.states.get(CONVERSATION_ENTITY_ID)
    assert state is not None
    assert state.attributes["supported_features"] == 0


async def test_conversation_appends_citation_instruction(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test conversation always asks presets to omit web search citations."""
    await _setup_conversation_entry(
        hass, mock_perplexity_client, {CONF_PROMPT: "You are helpful."}
    )
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("Web search result")
    )

    result = await _converse(hass, "What is the weather?")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    call_kwargs = mock_perplexity_client.responses.create.call_args.kwargs
    assert call_kwargs["instructions"].startswith("You are helpful.")
    assert call_kwargs["instructions"].endswith(WEB_SEARCH_ADDITIONAL_INSTRUCTION)


async def test_conversation_stream_failed(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test conversation raises when the stream reports a failed response."""

    async def _failed_stream() -> AsyncGenerator[MagicMock]:
        failed = MagicMock(type="response.failed")
        failed.error.message = "Something broke"
        yield failed

    mock_perplexity_client.responses.create = AsyncMock(return_value=_failed_stream())

    result = await _converse(hass, "Hello")

    assert result.response.response_type == intent.IntentResponseType.ERROR
    assert result.response.speech["plain"]["speech"] == (
        "Error talking to Perplexity API for Perplexity: Something broke"
    )


async def test_conversation_tool_call_round_trip(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test a tool call runs the intent and its result is sent back."""
    turn_on_calls = expose_light(hass)
    sent_kwargs = _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(
                tool_calls=[function_call_item("intent__HassTurnOn", TURN_ON_ARGUMENTS)]
            ),
            create_mock_stream("The living room light is on."),
        ],
    )

    result = await _converse(hass, "Turn on the living room light")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert result.response.speech["plain"]["speech"] == ("The living room light is on.")

    assert len(turn_on_calls) == 1
    assert turn_on_calls[0].data["entity_id"] == ["light.living_room"]

    assert len(sent_kwargs) == 2
    first, second = sent_kwargs
    assert second["instructions"] == first["instructions"]
    assert second["tools"] == first["tools"]
    assert second["input"][0] == first["input"][0]
    call, output = second["input"][1:]
    assert call == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "intent__HassTurnOn",
        "arguments": TURN_ON_ARGUMENTS,
    }
    assert output["type"] == "function_call_output"
    assert output["call_id"] == "call_1"
    assert output["name"] == "intent__HassTurnOn"
    assert "thought_signature" not in output
    assert '"error":false' in output["output"]
    assert '"response_type":"action_done"' in output["output"]


async def test_conversation_tool_call_error(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test a failing tool call is reported to the model, not to the user."""
    sent_kwargs = _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(tool_calls=[function_call_item("intent__Nope", "{}")]),
            create_mock_stream("I can't do that."),
        ],
    )

    result = await _converse(hass, "Do something odd")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert result.response.speech["plain"]["speech"] == "I can't do that."

    output = sent_kwargs[1]["input"][-1]
    assert output["type"] == "function_call_output"
    assert output["output"] == json_dumps(
        {
            "data": {
                "error": "HomeAssistantError",
                "error_text": 'Tool "intent__Nope" not found',
            },
            "error": True,
        }
    )


async def test_conversation_tool_loop_limit(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test a model that keeps calling tools is stopped after the limit."""
    expose_light(hass)
    sent_kwargs = _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(
                tool_calls=[
                    function_call_item(
                        "intent__HassTurnOn", TURN_ON_ARGUMENTS, call_id=f"call_{i}"
                    )
                ]
            )
            for i in range(MAX_TOOL_ITERATIONS + 1)
        ],
    )

    result = await _converse(hass, "Turn on the living room light")

    assert len(sent_kwargs) == MAX_TOOL_ITERATIONS
    assert result.response.response_type == intent.IntentResponseType.ERROR
    assert result.response.speech["plain"]["speech"] == "Unable to get response"


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ("{not json", "invalid tool arguments"),
        ("[1, 2]", "tool arguments are not an object"),
    ],
)
async def test_conversation_tool_call_invalid_arguments(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
    arguments: str,
    error: str,
) -> None:
    """Test unusable tool arguments end the turn with an API error."""
    _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(
                tool_calls=[function_call_item("llm__GetDateTime", arguments)]
            )
        ],
    )

    result = await _converse(hass, "What time is it?")

    assert result.response.response_type == intent.IntentResponseType.ERROR
    assert result.response.speech["plain"]["speech"].startswith(
        f"Error talking to Perplexity API for Perplexity: {error}"
    )


async def test_conversation_tool_call_empty_arguments(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test a parameterless tool called with empty arguments runs."""
    sent_kwargs = _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(tool_calls=[function_call_item("llm__GetDateTime", "")]),
            create_mock_stream("It is noon."),
        ],
    )

    result = await _converse(hass, "What time is it?")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    call, output = sent_kwargs[1]["input"][1:]
    assert call["arguments"] == "{}"
    assert '"error":false' in output["output"]
    assert '"weekday"' in output["output"]


async def test_conversation_tool_call_thought_signature(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test the thought signature is echoed on the call and its result."""
    expose_light(hass)
    sent_kwargs = _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(
                tool_calls=[
                    function_call_item(
                        "intent__HassTurnOn",
                        TURN_ON_ARGUMENTS,
                        thought_signature="c2ln",
                    )
                ]
            ),
            create_mock_stream("Done."),
        ],
    )

    await _converse(hass, "Turn on the living room light")

    call, output = sent_kwargs[1]["input"][1:]
    assert call["thought_signature"] == "c2ln"
    assert output["thought_signature"] == "c2ln"


async def test_conversation_tool_call_with_text(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test text after a tool call in the same response ends the turn."""
    expose_light(hass)
    sent_kwargs = _record_requests(
        mock_perplexity_client,
        [
            create_mock_stream(
                "Turning it on.",
                tool_calls=[
                    function_call_item("intent__HassTurnOn", TURN_ON_ARGUMENTS)
                ],
            )
        ],
    )

    result = await _converse(hass, "Turn on the living room light")

    assert len(sent_kwargs) == 1
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert result.response.speech["plain"]["speech"] == "Turning it on."


async def test_conversation_streams_text(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test text deltas reach the chat log before the stream ends."""
    deltas: list[dict[str, Any]] = []
    seen_before_end: list[dict[str, Any]] = []

    async def _stream() -> AsyncGenerator[Any]:
        yield MagicMock(type="response.created")
        yield MagicMock(type="response.output_text.delta", delta="Good ")
        yield MagicMock(type="response.output_text.delta", delta="morning")
        seen_before_end.extend(deltas)
        yield MagicMock(
            type="response.completed", response=MagicMock(status="completed")
        )

    mock_perplexity_client.responses.create = AsyncMock(return_value=_stream())

    def _listener(_chat_log: conversation.ChatLog, delta: dict[str, Any]) -> None:
        deltas.append(delta)

    with (
        async_get_chat_session(hass) as session,
        async_get_chat_log(hass, session, chat_log_delta_listener=_listener),
    ):
        result = await conversation.async_converse(
            hass,
            "Hello",
            session.conversation_id,
            Context(),
            agent_id=CONVERSATION_ENTITY_ID,
        )

    assert result.response.speech["plain"]["speech"] == "Good morning"
    assert seen_before_end == [
        {"role": "assistant"},
        {"content": "Good "},
        {"content": "morning"},
    ]


class _ReservedTool(llm.Tool):
    """Tool whose name collides with a Perplexity built-in tool."""

    name = "web_search"
    description = "Search the web"
    integration = DOMAIN

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> llm.ToolResult:
        """Never called."""
        return llm.ToolResult(data={})


class _EchoTool(_ReservedTool):
    """Tool with an acceptable name."""

    name = "echo"
    description = "Echo"


class _TestAPI(llm.API):
    """API exposing a reserved and a regular tool."""

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Return the API instance."""
        return llm.APIInstance(
            api=self,
            api_prompt="Test tools",
            llm_context=llm_context,
            tools=[_ReservedTool(), _EchoTool()],
        )


async def test_conversation_reserved_tool_name_skipped(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a tool named like a Perplexity built-in tool is not sent."""
    caplog.set_level(logging.DEBUG, logger="custom_components.perplexity")
    llm.async_register_api(hass, _TestAPI(hass=hass, id="test_api", name="Test"))
    await _setup_conversation_entry(
        hass, mock_perplexity_client, {CONF_LLM_HASS_API: ["test_api"]}
    )
    sent_kwargs = _record_requests(mock_perplexity_client, [create_mock_stream("Hi")])

    result = await _converse(hass, "Hello")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert [tool["name"] for tool in sent_kwargs[0]["tools"]] == ["echo"]
    assert "Skipping tool web_search" in caplog.text


async def test_conversation_extra_system_prompt(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test the extra system prompt is appended to the instructions."""
    sent_kwargs = _record_requests(
        mock_perplexity_client, [create_mock_stream("Done.")]
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
    assert "Extra instruction" in sent_kwargs[0]["instructions"]


async def test_conversation_with_home_location(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test that home location is included in the system prompt."""
    hass.config.latitude = 51.5074
    hass.config.longitude = -0.1278
    hass.config.country = "GB"

    await _setup_conversation_entry(
        hass,
        mock_perplexity_client,
        {CONF_PROMPT: "You are helpful.", CONF_INCLUDE_HOME_LOCATION: True},
    )
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("The weather in London is nice today.")
    )

    result = await _converse(hass, "What's the weather like?")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    system_content = mock_perplexity_client.responses.create.call_args.kwargs[
        "instructions"
    ]
    assert "Coordinates: 51.507,-0.128" in system_content
    assert "Country: GB" in system_content


async def test_conversation_with_home_location_no_country(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
) -> None:
    """Test home location without a configured country."""
    hass.config.latitude = 51.5074
    hass.config.longitude = -0.1278
    hass.config.country = None

    await _setup_conversation_entry(
        hass,
        mock_perplexity_client,
        {CONF_PROMPT: "You are helpful.", CONF_INCLUDE_HOME_LOCATION: True},
    )
    mock_perplexity_client.responses.create = AsyncMock(
        return_value=create_mock_stream("Nice weather.")
    )

    result = await _converse(hass, "What's the weather like?")

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    system_content = mock_perplexity_client.responses.create.call_args.kwargs[
        "instructions"
    ]
    assert "Coordinates: 51.507,-0.128" in system_content
    assert "Country:" not in system_content


async def test_conversation_message_items_concatenate(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_setup_entry: MockConfigEntry,
) -> None:
    """Test text split across two message items is one answer."""

    async def _stream() -> AsyncGenerator[Any]:
        yield output_item_events(message_item())[0]
        yield MagicMock(type="response.output_text.delta", delta="First part. ")
        yield output_item_events(message_item())[0]
        yield MagicMock(type="response.output_text.delta", delta="Second part.")
        yield MagicMock(
            type="response.completed", response=MagicMock(status="completed")
        )

    mock_perplexity_client.responses.create = AsyncMock(return_value=_stream())

    result = await _converse(hass, "Tell me more")

    assert result.response.speech["plain"]["speech"] == "First part. Second part."
