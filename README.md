# animalsketch-arena-107211-8c022944

## Backend Debugging

**Startup Log Location:**  
All logs from the backend API container's startup (including FastAPI/Python errors, import errors, and shell permission issues) will be written to:
```
backend_api/backend_api_startup.log
```
Review this log after container launch to diagnose:
- Python exceptions
- Import/module errors
- Shell script permission problems
- File/directory not found

**If the log is missing or empty:**
- Ensure your Dockerfile/compose setup invokes `backend_api/run.sh` as the entrypoint, not uvicorn directly.
- Check the script's executable permissions:  
  `chmod +x backend_api/run.sh`
- Globbing (e.g., CMD ["*.sh"]) may fail to match run.sh; use an explicit path.

**run.sh Diagnostic Output:**  
The script now emits key diagnostics to help surface entrypoint, directory, and permission issues automatically. Check the startup log for these messages.