"""Constants for the Perplexity integration."""

import logging

DOMAIN = "perplexity"
LOGGER = logging.getLogger(__package__)

CONF_REASONING_EFFORT = "reasoning_effort"

RECOMMENDED_CHAT_MODEL = "sonar"
DEFAULT_REASONING_EFFORT = "low"

PERPLEXITY_MODELS = {
    "sonar": "Sonar",
    "sonar-pro": "Sonar Pro",
    "sonar-reasoning-pro": "Sonar Reasoning Pro",
}

REASONING_MODELS = {"sonar-reasoning-pro"}

REASONING_EFFORT_OPTIONS = {
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}
