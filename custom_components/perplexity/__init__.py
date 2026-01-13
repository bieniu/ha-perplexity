"""The Perplexity integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client

from perplexity import (
    AsyncPerplexity,
    AuthenticationError,
    PerplexityError,
)

from .const import DOMAIN

PLATFORMS = [Platform.AI_TASK]

type PerplexityConfigEntry = ConfigEntry[AsyncPerplexity]


async def async_setup_entry(hass: HomeAssistant, entry: PerplexityConfigEntry) -> bool:
    """Set up Perplexity from a config entry."""
    client = AsyncPerplexity(
        api_key=entry.data[CONF_API_KEY],
        http_client=get_async_client(hass),
    )

    # Cache current platform data which gets added to each request (caching done by
    # library)
    _ = await hass.async_add_executor_job(client.platform_headers)

    try:
        await client.chat.completions.create(
            model="sonar",
            messages=[{"role": "user", "content": "hi"}],
            disable_search=True,
            max_tokens=1,
        )
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_error",
            translation_placeholders={"entry": entry.title},
        ) from err
    except PerplexityError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"entry": entry.title, "error": str(err)},
        ) from err

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: PerplexityConfigEntry
) -> None:
    """Handle update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PerplexityConfigEntry) -> bool:
    """Unload Perplexity."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
