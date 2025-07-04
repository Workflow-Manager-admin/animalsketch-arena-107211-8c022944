#!/bin/bash
# Entrypoint script to run FastAPI backend_api via uvicorn on port 3001

cd "$(dirname "$0")/src/api" || exit 1
exec ../../venv/bin/uvicorn main:app --host 0.0.0.0 --port 3001
