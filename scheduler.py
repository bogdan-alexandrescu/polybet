"""APScheduler background job management for scheduled data refreshes."""

import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db import get_connection, return_connection
from refresh import run_refresh

_scheduler = None
_lock = threading.Lock()
JOB_ID = "polybet_refresh"


def start_scheduler():
    """Start the background scheduler, loading cron from DB settings."""
    global _scheduler
    with _lock:
        if _scheduler is not None:
            return
        _scheduler = BackgroundScheduler()
        _scheduler.start()

    # Load saved schedule from DB
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = %(key)s",
            {"key": "cron_schedule"},
        ).fetchone()
        if row:
            update_schedule(row["value"])
    except Exception:
        pass
    finally:
        return_connection(conn)


def update_schedule(cron_expr):
    """Reschedule the refresh job with a new cron expression.

    cron_expr: standard cron string, e.g. '0 */6 * * *'
    Pass empty string or None to disable.
    """
    global _scheduler
    with _lock:
        if _scheduler is None:
            return

        # Remove existing job if present
        if _scheduler.get_job(JOB_ID):
            _scheduler.remove_job(JOB_ID)

        if not cron_expr:
            return

        # Parse cron expression (minute hour day month day_of_week)
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
        _scheduler.add_job(lambda: run_refresh(source='scheduler'), trigger, id=JOB_ID, replace_existing=True)


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    with _lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
