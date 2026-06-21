"""Entry point for the PyInstaller-compiled bio-attendance scheduler service.

Runs src/scheduler_main.py as its own process, fully separate from the main API
(run_server.py). Single worker on purpose — exactly one APScheduler instance.
"""
import uvicorn
import sys
import os

# When running as a compiled exe, anchor the working directory to the exe
# location so relative env paths (env/database.env, .env.sqlserver) resolve.
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from src.scheduler_main import app  # noqa: E402  (import after chdir)

if __name__ == "__main__":
    port = int(os.environ.get("SCHEDULER_PORT", "48480"))
    # Single worker, no reload: one scheduler instance only.
    uvicorn.run("src.scheduler_main:app", host="0.0.0.0", port=port, workers=1)
