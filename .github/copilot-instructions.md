# Instructions for AI Agents (Copilot, Claude, Codex)

## Repository context
- This repository contains a custom Home Assistant integration for Perplexity.
- The main integration logic lives in `custom_components/perplexity/`.

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
- Use the local venv in `./venv`.
- Activate with: `source venv/bin/activate`.
- `scripts/setup-local-env.sh` creates the venv (requires `python3.14`) and installs dev dependencies.

## Tests
- Tests live in `tests/`.
- Test snapshots are in `tests/snapshots/`.
- Run tests with `pytest` using the active venv.

## Linting and types
- `ruff` is the project's linter and formatter.
- `ty` is the type-annotation checker.
- Prefer fixing root causes over silencing rules.

## Home Assistant guidelines (condensed, apply in this repo)
- I/O must be asynchronous. For blocking work use `hass.async_add_executor_job`.
- Avoid blocking the event loop and `time.sleep()`. Use `asyncio.sleep()` and `gather()` instead of awaiting in loops.
- Handle errors with precise HA exceptions (`ConfigEntryNotReady`, `ConfigEntryAuthFailed`, `HomeAssistantError`). Avoid bare `except` outside config flow and background tasks.
- Logs: no trailing periods, no sensitive data, and use lazy logging (`%s`).
- User-facing text must be American English, friendly, second person. Use sentence case and backticks for file/field names.
- Docstrings are required for functions/methods. File headers should briefly describe the integration.
- If using `runtime_data`, type the `ConfigEntry` with an alias and store non-persisted data in `entry.runtime_data`.
- For config changes or repairs, follow HA patterns for config flow, diagnostics, and repairs, and keep translations updated.

## Code reviews
- After starting a review, do not `amend`, `squash`, or `rebase`.
