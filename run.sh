#!/usr/bin/env bash
# Launch phonecast. All options: ./run.sh --help
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m phonecast "$@"
