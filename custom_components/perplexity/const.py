"""Constants for the Perplexity integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.helpers import llm

DOMAIN = "perplexity"
LOGGER = logging.getLogger(__package__)

CONF_INCLUDE_HOME_LOCATION = "include_home_location"
CONF_REASONING_EFFORT = "reasoning_effort"

RECOMMENDED_CHAT_MODEL = "fast"
MIN_MAX_TOKENS = 16

INTEGRATION_HEADERS = {"X-Pplx-Integration": "ha-perplexity"}

PERPLEXITY_MODELS = {"fast": "Fast", "low": "Low", "medium": "Medium", "high": "High"}

# Mapping from Perplexity's migrate-sonar-to-agent-api skill (models-and-presets.md)
LEGACY_MODEL_TO_PRESET = {
    "sonar": "fast",
    "sonar-pro": "fast",
    "sonar-reasoning-pro": "low",
}

REASONING_EFFORT_OPTIONS = ["minimal", "low", "medium", "high", "xhigh"]

WEB_SEARCH_ADDITIONAL_INSTRUCTION = "Do not include citations in your response."

SUBENTRY_TYPE_AI_TASK = "ai_task_data"
SUBENTRY_TYPE_CONVERSATION = "conversation"

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
    CONF_INCLUDE_HOME_LOCATION: False,
}
