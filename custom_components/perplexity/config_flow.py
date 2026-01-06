"""Config flow for Perplexity integration."""

from __future__ import annotations

import logging
from typing import Any

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_MODEL
from homeassistant.core import callback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN, PERPLEXITY_MODELS, RECOMMENDED_CHAT_MODEL

_LOGGER = logging.getLogger(__name__)


class PerplexityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Perplexity."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            "ai_task_data": PerplexityAITaskFlowHandler,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(user_input)
            client = AsyncPerplexity(
                api_key=user_input[CONF_API_KEY],
                http_client=get_async_client(self.hass),
            )
            try:
                await client.chat.completions.create(
                    model="sonar",
                    messages=[{"role": "user", "content": "ping"}],
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except PerplexityError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Perplexity",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )


class PerplexityAITaskFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for Perplexity AI task."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """User flow to create an AI task subentry."""
        if user_input is not None:
            model_id = user_input[CONF_MODEL]
            return self.async_create_entry(
                title=PERPLEXITY_MODELS[model_id], data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=RECOMMENDED_CHAT_MODEL): (
                        SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    SelectOptionDict(value=model_id, label=name)
                                    for model_id, name in PERPLEXITY_MODELS.items()
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            ),
                        )
                    ),
                }
            ),
        )
