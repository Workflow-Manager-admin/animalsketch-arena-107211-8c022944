#!/bin/bash
# Entrypoint script to run FastAPI backend_api via uvicorn on port 3001

set -ex   # Verbose output & fail-fast for easier debugging

# Ensure we are in the backend_api directory
cd "$(dirname "$0")" || exit 1

# Check if script has execute permissions, else fix
if [[ ! -x "$0" ]]; then
  chmod +x "$0"
fi

# Activate venv if it exists
if [ -d "../../venv" ]; then
    source ../../venv/bin/activate
fi

# Set PYTHONPATH so uvicorn finds the package correctly
export PYTHONPATH=$(pwd)/src/api:$PYTHONPATH

# Move to API source directory explicitly
cd src/api || exit 1

# Add verbose uvicorn logging, ensure correct module path, and fail fast on errors
exec uvicorn main:app --host 0.0.0.0 --port 3001 --log-level debug
