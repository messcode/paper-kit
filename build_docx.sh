#!/usr/bin/env sh
# Thin wrapper for Linux / macOS / Git Bash. The real logic lives in paperkit.py.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -n "${PAPERKIT_PYTHON:-}" ]; then
    PY="$PAPERKIT_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi
exec "$PY" "$HERE/paperkit.py" build "$@"
