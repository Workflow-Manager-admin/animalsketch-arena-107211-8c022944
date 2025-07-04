#!/bin/bash
###############################################################################
# Entrypoint Script: backend_api/run.sh
#
# This script ensures that when the backend_api container/image is run:
#   - All output (stdout and stderr) is captured to backend_api_startup.log,
#   - Python/FastAPI exceptions, import issues, and shell problems will be logged,
#   - Working directory and permission problems are surfaced,
#   - Diagnostics relevant for Docker/container orchestration are emitted.
#
# USAGE NOTE: This should be referenced as the Docker ENTRYPOINT or CMD,
#   and not bypassed (i.e., do not invoke uvicorn directly in Dockerfile/CMD).
#
# TROUBLESHOOTING:
#   - If backend_api_startup.log is missing, run.sh may not be invoked, permissions may be wrong,
#     or shell globbing (e.g., *.sh expansion) may hide run.sh.
#   - If log is empty, either startup failed extremely early or shell exec'ing uvicorn failed.
#   - The CWD and directory tree info will aid diagnosis.
###############################################################################

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
    echo "[ERROR] src/api/main.py not found in $(pwd)/src/api" | tee -a ../backend_api_startup.log
    ls -lh src/api/ | tee -a ../backend_api_startup.log
    exit 2
fi

# Check permissions for main.py
if [ ! -r src/api/main.py ]; then
    echo "[ERROR] src/api/main.py is not readable (permissions issue) in $(pwd)/src/api" | tee -a ../backend_api_startup.log
    ls -lh src/api/ | tee -a ../backend_api_startup.log
    exit 2
fi

# Print working directory and tree for debug (to both stderr and startup log)
echo "CWD: $(pwd)" | tee -a ../backend_api_startup.log
echo "Tree under backend_api:" | tee -a ../backend_api_startup.log
ls -lahR . | tee -a ../backend_api_startup.log

# Set PYTHONPATH so uvicorn finds the package correctly (Should be the 'src' root, not 'src/api')
export PYTHONPATH=$(pwd)/src:$PYTHONPATH

# Move to API source directory explicitly
cd src/api || { echo "[ERROR] Failed to cd to src/api in $(pwd)" | tee -a ../../backend_api_startup.log; exit 1; }

echo "Launching uvicorn with: python -m uvicorn main:app --host 0.0.0.0 --port 3001 --log-level debug" | tee -a ../../../backend_api_startup.log
# Use the venv's Python to ensure the local environment dependencies are used (avoids 'ModuleNotFoundError')
# Capture stdout + stderr to a log file for troubleshooting
exec python -m uvicorn main:app --host 0.0.0.0 --port 3001 --log-level debug > ../../backend_api_startup.log 2>&1
