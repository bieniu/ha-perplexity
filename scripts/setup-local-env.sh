#!/bin/bash

PYTHON_VERSION=3.14

if ! command -v "python$PYTHON_VERSION" >/dev/null 2>&1; then
	echo "Error: python$PYTHON_VERSION is not available in PATH" >&2
	exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
	curl -LsSf https://astral.sh/uv/install.sh | sh
	export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

uv sync --frozen --all-groups --python=$PYTHON_VERSION
uv run prek install
