#!/bin/sh
# Register the cleanmedia package from the volume mount (deps are pre-installed
# in the Docker image so this is fast).
if [ -f /cleanmedia/pyproject.toml ]; then
    pip install --no-cache-dir --no-deps /cleanmedia 2>&1 | tail -1
fi

exec "$@"
