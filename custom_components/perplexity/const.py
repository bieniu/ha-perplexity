"""Constants for the Perplexity integration."""

import logging
from typing import Any

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
    CONF_WEB_SEARCH: DEFAULT_WEB_SEARCH,
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
                                "description": "Additional service data parameters",
                            },
                        },
                        "required": ["domain", "service", "target", "data"],
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
You can control Home Assistant devices by including actions in your response.
When the user asks to control a device, include the appropriate action.

IMPORTANT: You MUST respond with a valid JSON object in this exact format:
{
    "response": "Your text response to the user",
    "actions": [
        {
            "domain": "light",
            "service": "turn_on",
            "target": "light.living_room",
            "data": {"brightness": 255}
        }
    ]
}

If no action is needed, set "actions" to null or an empty array [].

Common domains and services:
- light: turn_on (data: brightness, color_temp, rgb_color), turn_off
- switch: turn_on, turn_off
- climate: turn_on, turn_off, set_temperature (data: temperature)
- cover: open_cover, close_cover, set_cover_position (data: position [0-100])
- media_player: media_play, media_pause, volume_set (data: volume_level [0-1])
- script: turn_on (to run scripts)
- scene: turn_on (to activate scenes)
- fan: turn_on, turn_off, set_percentage (data: percentage [0-100])

Always use the entity_id as the target.
If data is not needed, set it to null.
"""
