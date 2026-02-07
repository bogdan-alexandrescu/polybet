"""Refresh engine with DB-backed progress state and SSE streaming."""

import io
import json
import sys
import time
from datetime import datetime, timezone

import psycopg

from db import get_connection, return_connection, create_indexes, create_tag_table
from pull_markets import (
    fetch_all_events, init_db, upsert_event, upsert_market, insert_snapshot,
)


# ---------------------------------------------------------------------------
# DB-backed job state functions
# ---------------------------------------------------------------------------

def cleanup_orphaned_jobs():
    """Mark any 'running' jobs as 'error' on startup (they were orphaned by a restart)."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE refresh_jobs
               SET status = 'error', phase = 'error',
                   error = 'Interrupted by server restart', finished_at = NOW()
               WHERE status = 'running'"""
        )
        conn.commit()
    except Exception:
        pass
    finally:
        return_connection(conn)


def create_job(source="web"):
    """Insert a new refresh_jobs row and return the job id."""
    conn = get_connection()
    try:
        row = conn.execute(
            "INSERT INTO refresh_jobs (status, source) VALUES ('running', %(source)s) RETURNING id",
            {"source": source},
        ).fetchone()
        conn.commit()
        return row["id"]
    finally:
        return_connection(conn)


def update_job(conn, job_id, **kwargs):
    """Update columns on a refresh_jobs row (immediate commit)."""
    if not kwargs:
        return
    parts = []
    params = {"job_id": job_id}
    for key, value in kwargs.items():
        parts.append(f"{key} = %({key})s")
        params[key] = value
    conn.execute(
        f"UPDATE refresh_jobs SET {', '.join(parts)} WHERE id = %(job_id)s",
        params,
    )
    conn.commit()


def get_job(job_id=None):
    """Return the latest (or specific) refresh job as a dict, or None."""
    conn = get_connection()
    try:
        if job_id:
            row = conn.execute(
                "SELECT * FROM refresh_jobs WHERE id = %(id)s",
                {"id": job_id},
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM refresh_jobs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["running"] = result["status"] == "running"
        # Convert timestamps to ISO strings for JSON
        for ts_field in ("started_at", "finished_at"):
            if result[ts_field] is not None:
                result[ts_field] = result[ts_field].isoformat()
        return result
    finally:
        return_connection(conn)


def request_cancel(job_id=None):
    """Cancel a running job: set flag for the thread AND force status for orphaned jobs."""
    conn = get_connection()
    try:
        if job_id:
            conn.execute(
                """UPDATE refresh_jobs
                   SET cancel_requested = TRUE, status = 'cancelled',
                       phase = 'cancelled', finished_at = NOW()
                   WHERE id = %(id)s AND status = 'running'""",
                {"id": job_id},
            )
        else:
            conn.execute(
                """UPDATE refresh_jobs
                   SET cancel_requested = TRUE, status = 'cancelled',
                       phase = 'cancelled', finished_at = NOW()
                   WHERE status = 'running'"""
            )
        conn.commit()
        return True
    finally:
        return_connection(conn)


def is_cancelled(conn, job_id):
    """Fast check: is cancellation requested for this job?"""
    row = conn.execute(
        "SELECT cancel_requested FROM refresh_jobs WHERE id = %(id)s",
        {"id": job_id},
    ).fetchone()
    return row and row["cancel_requested"]


def append_log(conn, job_id, line):
    """Insert a log line for the given job (immediate commit)."""
    conn.execute(
        "INSERT INTO refresh_logs (job_id, line) VALUES (%(job_id)s, %(line)s)",
        {"job_id": job_id, "line": line},
    )
    conn.commit()


def get_logs(job_id, after_id=0):
    """Return log lines for a job after the given id."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, line FROM refresh_logs WHERE job_id = %(job_id)s AND id > %(after_id)s ORDER BY id",
            {"job_id": job_id, "after_id": after_id},
        ).fetchall()
        return [{"id": r["id"], "line": r["line"]} for r in rows]
    finally:
        return_connection(conn)


# ---------------------------------------------------------------------------
# LogCapture — tees stdout to both console and DB
# ---------------------------------------------------------------------------

class LogCapture(io.TextIOBase):
    """Wraps stdout to tee output to both console and refresh_logs table."""

    def __init__(self, original, conn, job_id):
        self._original = original
        self._conn = conn
        self._job_id = job_id
        self._buffer = ""

    def write(self, text):
        if self._original:
            self._original.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                try:
                    append_log(self._conn, self._job_id, line)
                except Exception:
                    pass
        return len(text)

    def flush(self):
        if self._original:
            self._original.flush()
        # Flush remaining buffer
        if self._buffer.strip():
            try:
                append_log(self._conn, self._job_id, self._buffer)
            except Exception:
                pass
            self._buffer = ""

    def isatty(self):
        return False


# ---------------------------------------------------------------------------
# Cleanup — free disk space before each refresh
# ---------------------------------------------------------------------------

def cleanup_old_data(conn):
    """Delete old refresh logs, old jobs, and duplicate snapshots to free disk space."""
    # Keep only the last 3 refresh jobs' logs
    cutoff = conn.execute(
        "SELECT id FROM refresh_jobs ORDER BY id DESC OFFSET 3 LIMIT 1"
    ).fetchone()
    if cutoff:
        deleted = conn.execute(
            "DELETE FROM refresh_logs WHERE job_id <= %(cutoff)s",
            {"cutoff": cutoff["id"]},
        ).rowcount
        conn.execute(
            "DELETE FROM refresh_jobs WHERE id <= %(cutoff)s AND status != 'running'",
            {"cutoff": cutoff["id"]},
        )
        conn.commit()
        if deleted:
            print(f"  Cleaned up {deleted} old log lines.")

    # Keep only the latest snapshot per market
    deleted = conn.execute("""
        DELETE FROM price_snapshots
        WHERE id NOT IN (
            SELECT DISTINCT ON (market_id) id
            FROM price_snapshots
            ORDER BY market_id, fetched_at DESC
        )
    """).rowcount
    conn.commit()
    if deleted:
        print(f"  Cleaned up {deleted} old snapshots.")

    # VACUUM to reclaim disk space
    old_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        conn.execute("VACUUM refresh_logs")
        conn.execute("VACUUM refresh_jobs")
        conn.execute("VACUUM price_snapshots")
        print("  Vacuumed tables.")
    except Exception as e:
        print(f"  VACUUM warning: {e}")
    finally:
        conn.autocommit = old_autocommit


# ---------------------------------------------------------------------------
# Main refresh function
# ---------------------------------------------------------------------------

def run_refresh(source="web"):
    """Execute a full data refresh with DB-backed progress tracking."""
    job_id = create_job(source)
    data_conn = None
    state_conn = None
    original_stdout = sys.stdout

    try:
        data_conn = get_connection()
        state_conn = get_connection()

        # Install log capture
        sys.stdout = LogCapture(original_stdout, state_conn, job_id)

        init_db(data_conn)

        # Cleanup old data to free disk space
        print("Cleaning up old data...")
        cleanup_old_data(data_conn)

        now = datetime.now(timezone.utc).isoformat()
        counters = {
            "processed_events": 0,
            "new_events": 0,
            "updated_events": 0,
            "skipped_events": 0,
            "new_markets": 0,
            "updated_markets": 0,
            "snapshots": 0,
        }
        flush_interval = 10
        data_commit_interval = 100
        total = 0

        def upsert_batch(events, known_closed_ids, counter_offset):
            """Upsert a batch of events, committing incrementally."""
            nonlocal total
            for i, event in enumerate(events):
                if is_cancelled(state_conn, job_id):
                    data_conn.commit()
                    update_job(state_conn, job_id, status="cancelled", phase="cancelled",
                               finished_at=datetime.now(timezone.utc), **counters)
                    print("Refresh cancelled.")
                    return False

                is_closed = event.get("closed", False)

                if is_closed and event.get("id") in known_closed_ids:
                    counters["skipped_events"] += 1
                    counters["processed_events"] += 1
                    if (i + 1) % flush_interval == 0:
                        update_job(state_conn, job_id, **counters)
                    continue

                upsert_event(data_conn, event, now)
                counters["new_events"] += 1

                for market in event.get("markets", []):
                    upsert_market(data_conn, market, event["id"], now)
                    counters["new_markets"] += 1

                    if not is_closed:
                        insert_snapshot(data_conn, market, now)
                        counters["snapshots"] += 1

                counters["processed_events"] += 1

                if (i + 1) % data_commit_interval == 0:
                    data_conn.commit()
                    print(f"  Committed batch: {counters['processed_events']}/{total} events...")

                if (i + 1) % flush_interval == 0:
                    update_job(state_conn, job_id, **counters)

            data_conn.commit()
            update_job(state_conn, job_id, **counters)
            return True

        # Phase 1: Fetch + upsert open events
        update_job(state_conn, job_id, phase="fetching_open")
        print("Fetching open events from Polymarket API...")
        open_events = fetch_all_events(closed=False, label="[open] ")

        if is_cancelled(state_conn, job_id):
            update_job(state_conn, job_id, status="cancelled", phase="cancelled",
                       finished_at=datetime.now(timezone.utc))
            print("Refresh cancelled.")
            return

        total = len(open_events)
        update_job(state_conn, job_id, total_events=total, phase="upserting_open")
        print(f"Upserting {len(open_events)} open events...")
        if not upsert_batch(open_events, set(), 0):
            return
        print(f"Open events committed — {counters['new_markets']} markets now visible.")

        # Phase 2: Fetch + upsert closed events
        update_job(state_conn, job_id, phase="fetching_closed")
        print("Fetching closed events from Polymarket API...")

        known_closed_ids = set()
        rows = data_conn.execute("SELECT id FROM events WHERE closed = 1").fetchall()
        known_closed_ids = {r["id"] for r in rows}

        closed_events = fetch_all_events(closed=True, label="[closed] ")

        if is_cancelled(state_conn, job_id):
            update_job(state_conn, job_id, status="cancelled", phase="cancelled",
                       finished_at=datetime.now(timezone.utc))
            print("Refresh cancelled.")
            return

        total += len(closed_events)
        update_job(state_conn, job_id, total_events=total, phase="upserting_closed")
        print(f"Upserting {len(closed_events)} closed events ({len(known_closed_ids)} already in DB, will skip)...")
        if not upsert_batch(closed_events, known_closed_ids, len(open_events)):
            return
        print(f"Done: {counters['new_events']} events, {counters['new_markets']} markets, {counters['snapshots']} snapshots.")

        # Phase 4: Rebuild tag table
        update_job(state_conn, job_id, phase="building_tags")
        print("Rebuilding indexes and tag table...")
        create_indexes(data_conn)
        create_tag_table(data_conn)

        update_job(state_conn, job_id,
                   status="done", phase="done",
                   finished_at=datetime.now(timezone.utc),
                   **counters)
        print("Refresh complete!")

    except Exception as e:
        try:
            update_job(state_conn or get_connection(), job_id,
                       status="error", phase="error",
                       error=str(e),
                       finished_at=datetime.now(timezone.utc))
        except Exception:
            pass
        print(f"Refresh error: {e}")
    finally:
        sys.stdout = original_stdout
        if data_conn is not None:
            return_connection(data_conn)
        if state_conn is not None:
            return_connection(state_conn)


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

def sse_generator(job_id=None):
    """Yield SSE events with refresh state + log lines every 0.5s."""
    last_log_id = 0

    while True:
        job = get_job(job_id)
        if not job:
            yield f"data: {json.dumps({'running': False, 'phase': ''})}\n\n"
            break

        logs = get_logs(job["id"], after_id=last_log_id)
        if logs:
            last_log_id = logs[-1]["id"]
        job["log_lines"] = logs

        yield f"data: {json.dumps(job, default=str)}\n\n"

        if not job["running"] and job["phase"] in ("done", "cancelled", "error", ""):
            break
        time.sleep(0.5)
