"""Constants for the Perplexity integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm

DOMAIN = "perplexity"
LOGGER = logging.getLogger(__package__)

CONF_REASONING_EFFORT = "reasoning_effort"
CONF_WEB_SEARCH = "web_search"
CONF_PROMPT = "prompt"

RECOMMENDED_CHAT_MODEL = "sonar"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_WEB_SEARCH = False

PERPLEXITY_MODELS = {
    "sonar": "Sonar",
    "sonar-pro": "Sonar Pro",
    "sonar-reasoning-pro": "Sonar Reasoning Pro",
}

REASONING_MODELS = {"sonar-reasoning-pro"}

REASONING_EFFORT_OPTIONS = ["minimal", "low", "medium", "high"]

WEB_SEARCH_ADDITIONAL_INSTRUCTION = "Do not include citations in your response."

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}
