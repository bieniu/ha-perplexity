"""Config flow for Perplexity integration."""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError

from .const import (
    CONF_INCLUDE_HOME_LOCATION,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_WEB_SEARCH,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_WEB_SEARCH,
    DOMAIN,
    LOGGER,
    PERPLEXITY_MODELS,
    REASONING_EFFORT_OPTIONS,
    REASONING_MODELS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CONVERSATION_OPTIONS,
)

DESCRIPTION_PLACEHOLDERS = {"api_key_url": "https://www.perplexity.ai/account/api/keys"}


class PerplexityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Perplexity."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            "ai_task_data": PerplexityAITaskFlowHandler,
            "conversation": PerplexityConversationFlowHandler,
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
        entry_data: Mapping[str, Any],
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

        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data={**subentry.data, **user_input},
            )

        current_web_search = subentry.data.get(CONF_WEB_SEARCH, DEFAULT_WEB_SEARCH)

        schema: dict[vol.Marker, Any] = {
            vol.Required(CONF_WEB_SEARCH, default=current_web_search): bool,
        }

        # Add reasoning effort option only for reasoning models
        if model in REASONING_MODELS:
            current_reasoning_effort = subentry.data.get(
                CONF_REASONING_EFFORT, DEFAULT_REASONING_EFFORT
            )
            schema.update(
                {
                    vol.Required(
                        CONF_REASONING_EFFORT, default=current_reasoning_effort
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=REASONING_EFFORT_OPTIONS,
                            translation_key=CONF_REASONING_EFFORT,
                            mode=SelectSelectorMode.DROPDOWN,
                        ),
                    )
                }
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(schema),
        )


class PerplexityConversationFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for Perplexity conversation agent."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        super().__init__()
        self.options: dict[str, Any] = {}

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == SOURCE_USER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """User flow to create a conversation agent subentry."""
        self.options = RECOMMENDED_CONVERSATION_OPTIONS.copy()
        return await self.async_step_init(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a conversation agent subentry."""
        self.options = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_init(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage conversation agent configuration."""
        if self._get_entry().state != ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)
            if self._is_new:
                return self.async_create_entry(
                    title=PERPLEXITY_MODELS[user_input[CONF_MODEL]], data=user_input
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        hass_apis: list[SelectOptionDict] = [
            SelectOptionDict(
                label=api.name,
                value=api.id,
            )
            for api in llm.async_get_apis(self.hass)
        ]

        if suggested_llm_apis := self.options.get(CONF_LLM_HASS_API):
            valid_api_ids = {api["value"] for api in hass_apis}
            self.options[CONF_LLM_HASS_API] = [
                api for api in suggested_llm_apis if api in valid_api_ids
            ]

        model = self.options.get(CONF_MODEL, RECOMMENDED_CHAT_MODEL)

        schema: dict[vol.Marker, Any] = {
            vol.Required(
                CONF_MODEL,
                default=model,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=model_id, label=name)
                        for model_id, name in PERPLEXITY_MODELS.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                ),
            ),
            vol.Optional(
                CONF_PROMPT,
                description={
                    "suggested_value": self.options.get(
                        CONF_PROMPT,
                        RECOMMENDED_CONVERSATION_OPTIONS[CONF_PROMPT],
                    )
                },
            ): TemplateSelector(),
            vol.Optional(
                CONF_LLM_HASS_API,
                default=self.options.get(
                    CONF_LLM_HASS_API,
                    RECOMMENDED_CONVERSATION_OPTIONS[CONF_LLM_HASS_API],
                ),
            ): SelectSelector(SelectSelectorConfig(options=hass_apis, multiple=True)),
            vol.Required(
                CONF_WEB_SEARCH,
                default=self.options.get(
                    CONF_WEB_SEARCH,
                    RECOMMENDED_CONVERSATION_OPTIONS[CONF_WEB_SEARCH],
                ),
            ): bool,
            vol.Required(
                CONF_INCLUDE_HOME_LOCATION,
                default=self.options.get(
                    CONF_INCLUDE_HOME_LOCATION,
                    RECOMMENDED_CONVERSATION_OPTIONS[CONF_INCLUDE_HOME_LOCATION],
                ),
            ): bool,
        }

        if model in REASONING_MODELS:
            schema[
                vol.Required(
                    CONF_REASONING_EFFORT,
                    default=self.options.get(
                        CONF_REASONING_EFFORT, DEFAULT_REASONING_EFFORT
                    ),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=REASONING_EFFORT_OPTIONS,
                    translation_key=CONF_REASONING_EFFORT,
                    mode=SelectSelectorMode.DROPDOWN,
                ),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
        )
