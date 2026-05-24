"""Entry point for PyInstaller-compiled VoWERP3 Backend."""
import uvicorn
import sys
import os

# When running as compiled exe, set the working directory to the exe location
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from src.main import app

if __name__ == "__main__":
    workers = int(os.environ.get("UVICORN_WORKERS", "4"))
    # When --reload is desired in dev, use the CLI directly:
    #   uvicorn src.main:app --reload --workers 1 --port 8000
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, workers=workers)
