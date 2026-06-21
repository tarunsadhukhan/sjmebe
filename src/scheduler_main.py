"""scheduler_main.py — Standalone bio-attendance scheduler service.

Runs the automated hourly bio-attendance pipeline (APScheduler) in its OWN
process, completely separate from the main API (src/main.py).

Why a separate process?
-----------------------
The pipeline does heavy SYNCHRONOUS work — pure-Python pymysql/pyodbc queries
and row-by-row loops over thousands of punch rows. Running it inside the main
API process holds the GIL while it works, freezing every API request/page until
the run finishes. Hosting it here as a separate OS process gives full isolation:
the pipeline can churn without ever touching the main app's event loop.

Config is read from env/database.env (loaded on import of bio_att_scheduler):
  BIO_ATT_AUTO_ENABLED, BIO_ATT_AUTO_TENANT, BIO_ATT_AUTO_BRANCH,
  BIO_ATT_AUTO_COMPANY_ID, BIO_ATT_AUTO_INTERVAL_MIN

Run it (separate terminal / service), single worker:
  uvicorn src.scheduler_main:app --host 0.0.0.0 --port 48480
or directly:
  python -m src.scheduler_main

IMPORTANT: run exactly ONE instance (single worker, no --reload in production).
Each instance starts its own scheduler; the pipeline's MySQL named lock guards
against overlap, but a single worker keeps things simplest.
"""

import asyncio
import logging

from fastapi import FastAPI

# Importing the pipeline module triggers env/database.env loading (see
# bio_att_scheduler.py module bootstrap) so BIO_ATT_AUTO_* vars are available.
from src.hrms.bio_att_auto_pipeline import (
    start_scheduler,
    stop_scheduler,
    _read_config,
    _scheduled_job,
)
from src.hrms import bio_att_auto_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_main")

app = FastAPI(title="Vowerp3b Bio-Attendance Scheduler")


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Scheduler service starting up...")
    try:
        scheduler = start_scheduler()
        if scheduler is None:
            logger.warning(
                "Scheduler did NOT start — BIO_ATT_AUTO_ENABLED is off or config "
                "is incomplete. Service is up but idle."
            )
    except Exception:
        logger.exception("Failed to start bio_att_auto scheduler")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Scheduler service shutting down...")
    try:
        stop_scheduler()
    except Exception:
        logger.exception("Failed to stop bio_att_auto scheduler")


@app.get("/health")
async def health() -> dict:
    """Report whether the scheduler is running and its active config."""
    cfg = _read_config()
    running = bio_att_auto_pipeline._scheduler is not None
    return {
        "service": "bio_att_scheduler",
        "scheduler_running": running,
        "enabled": cfg is not None,
        "config": cfg,
    }


@app.post("/run-now")
async def run_now() -> dict:
    """Trigger one pipeline pass immediately, off the event loop.

    Useful for verification without waiting for the next interval. The job runs
    in a worker thread so this endpoint returns as soon as the run completes
    without blocking the scheduler's own loop. Honours the same single-run MySQL
    lock as the scheduled job, so it is safe to call alongside a scheduled tick.
    """
    cfg = _read_config()
    if cfg is None:
        return {"triggered": False, "reason": "disabled_or_misconfigured"}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _scheduled_job)
    return {"triggered": True}


if __name__ == "__main__":
    import uvicorn

    # Single worker, no reload: exactly one scheduler instance.
    uvicorn.run("src.scheduler_main:app", host="0.0.0.0", port=48480, reload=False)
