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

# Check if src/api/main.py exists
if [ ! -f src/api/main.py ]; then
    echo "ERROR: src/api/main.py not found!"
    ls -lh src/api/
    exit 2
fi

# Check permissions for main.py
if [ ! -r src/api/main.py ]; then
    echo "ERROR: src/api/main.py is not readable!"
    ls -lh src/api/
    exit 2
fi

# Print working directory and tree for debug
echo "CWD: $(pwd)"
echo "Tree under backend_api:"
ls -lahR .

# Set PYTHONPATH so uvicorn finds the package correctly (Should be the 'src' root, not 'src/api')
export PYTHONPATH=$(pwd)/src:$PYTHONPATH

# Move to API source directory explicitly
cd src/api || exit 1

echo "Launching uvicorn with: python -m uvicorn main:app --host 0.0.0.0 --port 3001 --log-level debug"
# Use the venv's Python to ensure the local environment dependencies are used (avoids 'ModuleNotFoundError')
# Capture stdout + stderr to a log file for troubleshooting
exec python -m uvicorn main:app --host 0.0.0.0 --port 3001 --log-level debug > ../../backend_api_startup.log 2>&1
