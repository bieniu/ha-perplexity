# Instructions for AI Agents (Copilot, Claude, Codex)

## Repository context

- This repository contains a custom Home Assistant integration for Perplexity
- The main integration logic lives in `custom_components/perplexity/`

## `custom_components/perplexity` structure

```text
custom_components/perplexity/
├── __init__.py          # Entry point with async_setup_entry
├── manifest.json        # Integration metadata and dependencies
├── const.py             # Domain and constants
├── config_flow.py       # UI configuration flow
├── ai_task.py           # AI Task platform
├── conversation.py      # Conversation platform
├── entity.py            # Shared Perplexity entity/request handling
├── utils.py             # Shared helper functions
├── diagnostics.py       # Diagnostics data
└── translations/        # User-facing text and translations
    ├── en.json          # English strings
    └── pl.json          # Polish strings
```

## Integration architecture notes

- `__init__.py` validates the API key, creates `AsyncPerplexity`, stores it in `entry.runtime_data`, and forwards setup to `ai_task` and `conversation`
- `config_flow.py` handles the main API key flow plus config subentries for AI Task and Conversation
- `entity.py` contains shared Perplexity request handling, streaming, structured output formatting, reasoning options, web search options, and image attachment preparation
- `conversation.py` implements the Conversation entity, optional Home Assistant control, exposed entity context, delayed actions, and timer intent handling
- `ai_task.py` implements `AITaskEntity` and returns either plain text or structured JSON data
- `const.py` is the source of truth for supported models, option keys, defaults, and action response schemas
- `translations/en.json` and `translations/pl.json` must be updated for all user-facing config flow, options flow, and exception text

## Python and environment

- Use the local venv in `./.venv`
- Activate with: `source .venv/bin/activate`
- `scripts/setup-local-env.sh` creates the venv (requires `python3.14`), installs `uv`, then installs dev dependencies from `requirements-dev.txt`
- The setup script also runs `prek install`

## Linting and types

- run `ruff check <files> --fix` to lint the code
- run `ruff format <files>` to format the code
- run `ty check <files>` to check the type annotations
- CI runs also:
  - `prek run end-of-file-fixer trailing-whitespace check-added-large-files check-yaml check-json check-toml mixed-line-ending --all-files`
- Prefer fixing root causes over silencing rules

## Home Assistant guidelines

- Target Python version: 3.14
- I/O must be asynchronous, for blocking work use `hass.async_add_executor_job`
- Avoid blocking the event loop and `time.sleep()`, use `asyncio.sleep()` and `gather()` instead of awaiting in loops
- Handle errors with precise HA exceptions (`ConfigEntryNotReady`, `ConfigEntryAuthFailed`, `HomeAssistantError`), avoid bare `except` outside config flow and background tasks
- Logs: no trailing periods, no sensitive data, and use lazy logging (`%s`)
- User-facing text must be American English, friendly, second person, use sentence case and backticks for file/field names
- Docstrings are required for functions/methods, file headers should briefly describe the integration
- Avoid very long docstrings; prefer one-line docstrings and keep them to 3 lines at most
- If using `runtime_data`, type the `ConfigEntry` with an alias and store non-persisted data in `entry.runtime_data`
- For config changes or repairs, follow HA patterns for config flow, diagnostics, and repairs, and keep translations updated

## Reference implementations and docs

Use these as references for current Home Assistant patterns. Prefer official docs for API contracts and use core integrations as examples, not as code to copy blindly. Links to the `dev` branch are intentionally current; compare with the target Home Assistant version when investigating regressions.

- Conversation entity docs: https://developers.home-assistant.io/docs/core/entity/conversation/
- AI Task entity docs: https://developers.home-assistant.io/docs/core/entity/ai-task/
- OpenRouter integration: https://github.com/home-assistant/core/tree/dev/homeassistant/components/open_router/
- Anthropic integration: https://github.com/home-assistant/core/tree/dev/homeassistant/components/anthropic/
- Google Generative AI integration: https://github.com/home-assistant/core/tree/dev/homeassistant/components/google_generative_ai_conversation
- OpenAI integration: https://github.com/home-assistant/core/tree/dev/homeassistant/components/openai_conversation

## Testing

- Location: `tests/`.
- Test snapshots location: `tests/snapshots/`.
- Run tests with `pytest` using the active venv
- Update snapshots with `pytest --snapshot-update` or a narrower command such as `pytest tests/test_conversation.py --snapshot-update`
- Best Practices:
  - Use pytest fixtures from `pytest_homeassistant_custom_component.common`
  - Mock all external dependencies and APIs
  - Use snapshots for complex data structures
  - Follow existing test patterns
  - Never access `hass.data` directly - use fixtures and proper integration setup instead
  - Test through integration setup - don't test entities in isolation
  - Mock - use fixtures with realistic JSON data
Best Practices for Config Flow Testing:
- 100% coverage required: all supported config flow paths must be tested
- Test Scenarios:
  - Supported flow initiation methods, including user, reauth, reconfigure, and subentry flows
  - Successful configuration paths
  - Error recovery scenarios
  - Prevention of duplicate entries
  - Flow completion after errors

## Code reviews

- After starting a review, do not `amend`, `squash`, or `rebase`.
