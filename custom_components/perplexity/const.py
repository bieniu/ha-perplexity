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

TIMERS_UNSUPPORTED = "This device is not able to start timers."

PERPLEXITY_MODELS = {
    "sonar": "Sonar",
    "sonar-pro": "Sonar Pro",
    "sonar-reasoning-pro": "Sonar Reasoning Pro",
}

REASONING_MODELS = {"sonar-reasoning-pro"}

REASONING_EFFORT_OPTIONS = ["minimal", "low", "medium", "high"]

WEB_SEARCH_ADDITIONAL_INSTRUCTION = "Do not include citations in your response."

SUBENTRY_TYPE_AI_TASK = "ai_task_data"
SUBENTRY_TYPE_CONVERSATION = "conversation"

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
                "timer_actions": {
                    "type": ["array", "null"],
                    "description": (
                        "List of timer actions to execute "
                        "(start, cancel, cancel_all, pause, unpause, "
                        "increase, decrease, status)"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "enum": [
                                    "start",
                                    "cancel",
                                    "cancel_all",
                                    "pause",
                                    "unpause",
                                    "increase",
                                    "decrease",
                                    "status",
                                ],
                                "description": "The timer command to execute",
                            },
                            "name": {
                                "type": ["string", "null"],
                                "description": (
                                    "Optional name for the timer (e.g., pizza, eggs)"
                                ),
                            },
                            "hours": {
                                "type": ["integer", "null"],
                                "description": (
                                    "Number of hours for start/increase/"
                                    "decrease commands"
                                ),
                            },
                            "minutes": {
                                "type": ["integer", "null"],
                                "description": (
                                    "Number of minutes for start/increase/"
                                    "decrease commands"
                                ),
                            },
                            "seconds": {
                                "type": ["integer", "null"],
                                "description": (
                                    "Number of seconds for start/increase/"
                                    "decrease commands"
                                ),
                            },
                        },
                        "required": [
                            "command",
                            "name",
                            "hours",
                            "minutes",
                            "seconds",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["response", "actions", "timer_actions"],
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

Timer commands (use timer_actions array):
Format: {"command":"<str>","name":<str>|null,"hours":<int>|null,\
"minutes":<int>|null,"seconds":<int>|null}

Commands:
- start: Start a new timer. Requires at least one of hours/minutes/seconds.
Optional name for identification.
- cancel: Cancel a specific timer. Use name or hours/minutes/seconds to \
identify it.
- cancel_all: Cancel all timers. name/hours/minutes/seconds not needed.
- pause: Pause a running timer. Use name or hours/minutes/seconds to \
identify it.
- unpause: Resume a paused timer. Use name or hours/minutes/seconds to \
identify it.
- increase: Add time to a timer. Requires hours/minutes/seconds for amount \
to add. Use name to identify which timer.
- decrease: Remove time from a timer. Requires hours/minutes/seconds for \
amount to remove. Use name to identify which timer.
- status: Get timer status. Use name to filter, or leave null for all timers.

Examples:
"Set a 5 minute timer" => {"command":"start","name":null,"hours":null,\
"minutes":5,"seconds":null}
"Set a pizza timer for 12 minutes" => {"command":"start","name":"pizza",\
"hours":null,"minutes":12,"seconds":null}
"Cancel the pizza timer" => {"command":"cancel","name":"pizza","hours":null,\
"minutes":null,"seconds":null}
"Pause the timer" => {"command":"pause","name":null,"hours":null,\
"minutes":null,"seconds":null}
"Add 2 minutes to the timer" => {"command":"increase","name":null,\
"hours":null,"minutes":2,"seconds":null}
"""
