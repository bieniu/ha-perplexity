# Instructions for AI Agents (Copilot, Claude, Codex)

## Repository context
- This repository contains a custom Home Assistant integration for Perplexity
- The main integration logic lives in `custom_components/perplexity/`

## `custom_components/perplexity` structure
```
custom_components/perplexity/
├── __init__.py          # Entry point with async_setup_entry
├── manifest.json        # Integration metadata and dependencies
├── const.py             # Domain and constants
├── config_flow.py       # UI configuration flow
├── ai_task.py           # AI Task platform
├── conversation.py      # Conversation platform
├── entity.py            # Base entity class (if shared patterns)
├── diagnostics.py       # Diagnostics data
└── translations/        # User-facing text and translations
    ├── en.json          # English strings
    └── pl.json          # Polish strings
```

## Python and environment
- Use the local venv in `./venv`
- Activate with: `source venv/bin/activate`
- `scripts/setup-local-env.sh` creates the venv (requires `python3.14`), installs `uv`, then installs dev dependencies from `requirements-dev.txt`
- The setup script also runs `prek install`

## Linting and types
- run `ruff check <files> --fix` to lint the code
- run `ruff format <files>` to format the code
- run `ty check <files>` to check the type annotations
- Prefer fixing root causes over silencing rules

## Home Assistant guidelines
- Target Python version: 3.14
- I/O must be asynchronous, for blocking work use `hass.async_add_executor_job`
- Avoid blocking the event loop and `time.sleep()`, use `asyncio.sleep()` and `gather()` instead of awaiting in loops
- Handle errors with precise HA exceptions (`ConfigEntryNotReady`, `ConfigEntryAuthFailed`, `HomeAssistantError`), avoid bare `except` outside config flow and background tasks
- Logs: no trailing periods, no sensitive data, and use lazy logging (`%s`)
- User-facing text must be American English, friendly, second person, use sentence case and backticks for file/field names
- Docstrings are required for functions/methods, file headers should briefly describe the integration
- If using `runtime_data`, type the `ConfigEntry` with an alias and store non-persisted data in `entry.runtime_data`
- For config changes or repairs, follow HA patterns for config flow, diagnostics, and repairs, and keep translations updated
- Similar integrations:
  - homeassistant.components.anthropic
  - homeassistant.components.google_generative_ai_conversation
  - homeassistant.components.open_router
  - homeassistant.components.openai_conversation

## Testing
- Location: `tests/`.
- Test snapshots location: `tests/snapshots/`.
- Run tests with `pytest` using the active venv
- Best Practices:
  - Use pytest fixtures from `pytest_homeassistant_custom_component.common`
  - Mock all external dependencies and APIs
  - Use snapshots for complex data structures
  - Follow existing test patterns
  - Never access `hass.data` directly - use fixtures and proper integration setup instead
  - Test through integration setup - don't test entities in isolation
  - Mock - use fixtures with realistic JSON data
Best Practices for Config Flow Testing:
- 100% coverage required: all config flow paths must be tested
- Test Scenarios:
  - All flow initiation methods (user, discovery, import)
  - Successful configuration paths
  - Error recovery scenarios
  - Prevention of duplicate entries
  - Flow completion after errors

## Code reviews
- After starting a review, do not `amend`, `squash`, or `rebase`.
