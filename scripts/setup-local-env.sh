#!/bin/bash

if command -v python3.14 >/dev/null 2>&1; then
	PYTHON_VERSION=3.14
else
	echo "Error: python3.14 is not available in PATH" >&2
	exit 1
fi

python$PYTHON_VERSION -m pip install uv --upgrade
python$PYTHON_VERSION -m uv venv venv --clear --seed --python=$PYTHON_VERSION
source venv/bin/activate
pip install uv
uv pip install -r requirements-dev.txt
prek install
