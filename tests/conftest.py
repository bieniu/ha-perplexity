"""Tests helpers for the Perplexity integration."""

from collections.abc import AsyncGenerator, Callable, Generator, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.components.conversation.const import DOMAIN as CONVERSATION_DOMAIN
from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component

# The SDK stream instantiates these, never the `perplexity.types.*` submodule classes
from perplexity.generated.api import (
    FunctionCallOutputItemOutput,
    MessageOutputItemOutput,
    OutputItemAddedEventOutput,
    OutputItemDoneEventOutput,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.amber import AmberSnapshotExtension
from syrupy.location import PyTestLocation

from custom_components.perplexity.const import (
    CONF_PROMPT,
    DOMAIN,
    SUBENTRY_TYPE_AI_TASK,
    SUBENTRY_TYPE_CONVERSATION,
)


@pytest.fixture(autouse=True)
async def setup_ha(hass: HomeAssistant) -> None:
    """Set up Home Assistant."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, CONVERSATION_DOMAIN, {})


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Mock) -> None:
    """Auto enable custom integrations."""
    return


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Mock a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        version=2,
        data={
            CONF_API_KEY: "test_api_key",
        },
        subentries_data=[
            {
                "data": {CONF_MODEL: "fast"},
                "subentry_type": SUBENTRY_TYPE_AI_TASK,
                "title": "Fast",
                "subentry_id": "ulid-ai-task",
                "unique_id": None,
            },
            {
                "data": {
                    CONF_LLM_HASS_API: ["assist"],
                    CONF_MODEL: "fast",
                    CONF_PROMPT: "instruction",
                },
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Fast",
                "subentry_id": "ulid-conversation",
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_perplexity_client() -> Generator[MagicMock]:
    """Mock the Perplexity client."""
    with patch(
        "custom_components.perplexity.AsyncPerplexity", autospec=True
    ) as mock_client:
        client = mock_client.return_value
        client.platform_headers = MagicMock(return_value={})
        client.responses = MagicMock()
        client.responses.create = AsyncMock(return_value=MagicMock())
        yield client


@pytest.fixture
async def mock_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> MockConfigEntry:
    """Set up the Perplexity integration for testing."""
    with patch(
        "custom_components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture."""
    return snapshot.use_extension(SnapshotExtension)


def function_call_item(
    name: str,
    arguments: str,
    call_id: str = "call_1",
    thought_signature: str | None = None,
) -> FunctionCallOutputItemOutput:
    """Return a function call output item as the Agent API streams it."""
    return FunctionCallOutputItemOutput(
        id=f"fc_{call_id}",
        call_id=call_id,
        name=name,
        arguments=arguments,
        status="completed",
        type="function_call",
        thought_signature=thought_signature,
    )


def message_item() -> MessageOutputItemOutput:
    """Return an assistant message output item."""
    return MessageOutputItemOutput(
        id="msg_1", content=[], role="assistant", status="in_progress", type="message"
    )


def output_item_events(
    item: FunctionCallOutputItemOutput | MessageOutputItemOutput,
) -> tuple[OutputItemAddedEventOutput, OutputItemDoneEventOutput]:
    """Return the added and done events for an output item."""
    return (
        OutputItemAddedEventOutput(
            item=item,
            output_index=0,
            sequence_number=1,
            type="response.output_item.added",
        ),
        OutputItemDoneEventOutput(
            item=item,
            output_index=0,
            sequence_number=2,
            type="response.output_item.done",
        ),
    )


async def create_mock_stream(
    content: str = "",
    tool_calls: Sequence[FunctionCallOutputItemOutput] = (),
) -> AsyncGenerator[Any]:
    """Create a mock Agent API stream yielding tool calls and then text."""
    yield MagicMock(type="response.created")
    for call in tool_calls:
        added, done = output_item_events(call)
        yield added
        yield done
    if content:
        yield output_item_events(message_item())[0]
        yield MagicMock(type="response.output_text.delta", delta=content)
    yield MagicMock(type="response.completed", response=MagicMock(status="completed"))


@pytest.fixture
def mock_stream() -> Callable[..., AsyncGenerator[Any]]:
    """Mock stream fixture."""
    return create_mock_stream


def expose_light(hass: HomeAssistant) -> list[ServiceCall]:
    """Expose a living room light to Assist and mock its turn_on service."""
    hass.states.async_set("light.living_room", "off", {"friendly_name": "Living room"})
    async_expose_entity(hass, CONVERSATION_DOMAIN, "light.living_room", True)  # noqa: FBT003
    # The intent handler refuses entities whose service is not registered
    return async_mock_service(hass, "light", "turn_on")


class SnapshotExtension(AmberSnapshotExtension):
    """Extension for Syrupy."""

    @classmethod
    def dirname(cls, *, test_location: PyTestLocation) -> str:
        """Return the directory for the snapshot files."""
        test_dir = Path(test_location.filepath).parent
        return str(test_dir.joinpath("snapshots"))
