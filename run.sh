#!/usr/bin/env bash
# Launch phonecast. All options: ./run.sh --help
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3
if [ ! -t 2 ]; then
    # Started from the application menu: keep a log for troubleshooting.
    LOG="${XDG_CACHE_HOME:-$HOME/.cache}/phonecast/phonecast.log"
    mkdir -p "$(dirname "$LOG")"
    [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 1000000 ] && mv -f "$LOG" "$LOG.old"
    exec >>"$LOG" 2>&1
    echo "=== $(date) ==="
fi
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m phonecast "$@"
