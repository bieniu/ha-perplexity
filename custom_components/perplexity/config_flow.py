"""Config flow for Perplexity integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError

from .const import (
    CONF_REASONING_EFFORT,
    DEFAULT_REASONING_EFFORT,
    DOMAIN,
    LOGGER,
    PERPLEXITY_MODELS,
    REASONING_EFFORT_OPTIONS,
    REASONING_MODELS,
    RECOMMENDED_CHAT_MODEL,
)

DESCRIPTION_PLACEHOLDERS = {"api_key_url": "https://www.perplexity.ai/account/api/keys"}


class PerplexityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Perplexity."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            "ai_task_data": PerplexityAITaskFlowHandler,
        }

    async def _validate_input(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate the user input allows us to connect."""
        errors: dict[str, str] = {}
        try:
            client = AsyncPerplexity(
                api_key=user_input[CONF_API_KEY],
                http_client=get_async_client(self.hass),
            )
            await client.chat.completions.create(
                model="sonar",
                messages=[{"role": "user", "content": "hi"}],
                disable_search=True,
                max_tokens=1,
            )
        except AuthenticationError:
            errors["base"] = "invalid_auth"
        except PerplexityError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(user_input)

            errors = await self._validate_input(user_input)
            if not errors:
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
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle a reauthorization flow request."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthorization flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_input(user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_input(user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a subentry."""
        subentry = self._get_reconfigure_subentry()
        model = subentry.data.get(CONF_MODEL)

        # Only show options for reasoning models
        if model not in REASONING_MODELS:
            return self.async_abort(reason="not_reasoning_model")

        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data={**subentry.data, **user_input},
            )

        current_effort = subentry.data.get(
            CONF_REASONING_EFFORT, DEFAULT_REASONING_EFFORT
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REASONING_EFFORT, default=current_effort
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=REASONING_EFFORT_OPTIONS,
                            translation_key=CONF_REASONING_EFFORT,
                            mode=SelectSelectorMode.DROPDOWN,
                        ),
                    ),
                }
            ),
        )
