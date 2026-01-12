"""Constants for the Perplexity integration."""

import logging

DOMAIN = "perplexity"
LOGGER = logging.getLogger(__package__)

CONF_PROMPT = "prompt"
CONF_RECOMMENDED = "recommended"

RECOMMENDED_CHAT_MODEL = "sonar"

PERPLEXITY_MODELS = {
    "sonar": "Sonar",
    "sonar-pro": "Sonar Pro",
}
