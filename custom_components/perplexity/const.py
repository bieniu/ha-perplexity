"""Constants for the Perplexity integration."""

import logging
from typing import Any

from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm

DOMAIN = "perplexity"
LOGGER = logging.getLogger(__package__)

CONF_INCLUDE_HOME_LOCATION = "include_home_location"
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
    CONF_WEB_SEARCH: DEFAULT_WEB_SEARCH,
    CONF_INCLUDE_HOME_LOCATION: False,
}

# JSON schema for structured action response
ACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "assistant_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "The text response to show to the user",
                },
                "actions": {
                    "type": ["array", "null"],
                    "description": "List of Home Assistant actions to execute",
                    "items": {
                        "type": "object",
                        "properties": {
                            "domain": {
                                "type": "string",
                                "description": (
                                    "The domain of the service "
                                    "(e.g., light, switch, climate)"
                                ),
                            },
                            "service": {
                                "type": "string",
                                "description": (
                                    "The service to call (e.g., turn_on, turn_off)"
                                ),
                            },
                            "target": {
                                "type": "string",
                                "description": "The entity_id to target",
                            },
                            "data": {
                                "type": ["object", "null"],
                                "description": ("Additional service data parameters"),
                            },
                            "delay_seconds": {
                                "type": ["number", "null"],
                                "description": (
                                    "Delay in seconds before executing this "
                                    "action. Use null or 0 for immediate "
                                    "execution"
                                ),
                            },
                        },
                        "required": [
                            "domain",
                            "service",
                            "target",
                            "data",
                            "delay_seconds",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["response", "actions"],
            "additionalProperties": False,
        },
    },
}

# Action instructions for the system prompt
ACTION_INSTRUCTIONS = """
Control Home Assistant devices by including actions in your response.

Respond with JSON: {"response":"<text>","actions":[<action>,...]|null}
Action format: {"domain":"<str>","service":"<str>","target":"<entity_id>",\
"data":<obj>|null,"delay_seconds":<num>|null}

delay_seconds: null/0=immediate. For timed requests, use two actions:
"turn on fan for 30min" => turn_on(delay:null) + turn_off(delay:1800)
"turn off light in 10min" => turn_off(delay:600)
Time: 1min=60s, 1h=3600s.

Domains/services (data params):
climate: turn_on,turn_off,set_temperature(temperature)
cover: open_cover,close_cover,set_cover_position(position 0-100)
fan: turn_on,turn_off,set_percentage(percentage 0-100)
humidifier: turn_on,turn_off,set_humidity(humidity 0-100)
light: turn_on(brightness 0-255,color_temp,rgb_color),turn_off
lock: lock,unlock,open
media_player: media_play,media_pause,volume_set(volume_level 0-1)
scene: turn_on
script: turn_on
siren: turn_on,turn_off
switch: turn_on,turn_off
vacuum: start,pause,stop,return_to_base
valve: open_valve,close_valve
water_heater: turn_on,turn_off,set_temperature(temperature)

target=entity_id. Set data to null if not needed.
"""
