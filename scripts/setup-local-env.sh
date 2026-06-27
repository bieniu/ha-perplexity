#!/bin/bash

PYTHON_VERSION=3.14

if ! command -v "python$PYTHON_VERSION" >/dev/null 2>&1; then
	echo "Error: python$PYTHON_VERSION is not available in PATH" >&2
	exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
	"python$PYTHON_VERSION" -m pip install uv
fi

uv venv --python "$PYTHON_VERSION" --clear
source .venv/bin/activate
uv sync
uv run prek install
