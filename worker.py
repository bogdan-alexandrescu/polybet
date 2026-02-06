#!/usr/bin/env python3
"""Standalone worker process for scheduled data refreshes.

Runs as a separate Railway service alongside the web process.
"""

import os
import signal
import time

from db import init_analytics_db, close_pool
from pull_markets import init_db
from db import get_connection, return_connection
from scheduler import start_scheduler, stop_scheduler

MAX_RETRIES = 10
RETRY_DELAY = 5


def wait_for_db():
    """Wait for the database to become available with retries."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            conn = get_connection()
            conn.execute("SELECT 1")
            return_connection(conn)
            print("Database connection established.")
            return
        except Exception as e:
            print(f"DB connection attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"Could not connect to database after {MAX_RETRIES} attempts")


def main():
    wait_for_db()

    # Ensure tables exist
    conn = get_connection()
    try:
        init_db(conn)
    finally:
        return_connection(conn)

    init_analytics_db()

    if os.environ.get("SCHEDULER_ENABLED", "false").lower() == "true":
        print("Starting scheduler...")
        start_scheduler()
    else:
        print("Scheduler disabled (set SCHEDULER_ENABLED=true to enable)")

    # Graceful shutdown
    def handle_signal(signum, frame):
        print("Shutting down worker...")
        stop_scheduler()
        close_pool()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print("Worker running. Waiting for scheduled jobs...")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
