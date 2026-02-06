"""Refresh engine with progress state and SSE streaming."""

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from db import get_connection, return_connection, create_indexes, create_tag_table
from pull_markets import (
    fetch_all_events, init_db, upsert_event, upsert_market, insert_snapshot,
)

_lock = threading.Lock()


@dataclass
class RefreshState:
    running: bool = False
    phase: str = ""
    total_events: int = 0
    processed_events: int = 0
    new_events: int = 0
    updated_events: int = 0
    skipped_events: int = 0
    new_markets: int = 0
    updated_markets: int = 0
    snapshots: int = 0
    error: str | None = None
    cancel_requested: bool = False
    started_at: str | None = None
    finished_at: str | None = None


_state = RefreshState()


def get_state() -> dict:
    """Return current refresh state as a dict (thread-safe snapshot)."""
    with _lock:
        return asdict(_state)


def request_cancel():
    """Request cancellation of the running refresh."""
    with _lock:
        if _state.running:
            _state.cancel_requested = True
            return True
        return False


def _update(**kwargs):
    """Update state fields under the lock."""
    with _lock:
        for k, v in kwargs.items():
            setattr(_state, k, v)


def run_refresh():
    """Execute a full data refresh with progress tracking."""
    with _lock:
        if _state.running:
            return
        # Reset state
        _state.__init__()
        _state.running = True
        _state.started_at = datetime.now(timezone.utc).isoformat()

    conn = None
    try:
        conn = get_connection()
        init_db(conn)

        # Phase 1: Fetch open events
        _update(phase="fetching_open")
        open_events = fetch_all_events(closed=False, label="[open] ")

        with _lock:
            if _state.cancel_requested:
                _state.phase = "cancelled"
                _state.running = False
                _state.finished_at = datetime.now(timezone.utc).isoformat()
                return

        # Phase 2: Fetch closed events
        _update(phase="fetching_closed")

        # Build known closed IDs to skip
        known_closed_ids = set()
        rows = conn.execute("SELECT id FROM events WHERE closed = 1").fetchall()
        known_closed_ids = {r["id"] for r in rows}

        closed_events = fetch_all_events(closed=True, label="[closed] ")

        with _lock:
            if _state.cancel_requested:
                _state.phase = "cancelled"
                _state.running = False
                _state.finished_at = datetime.now(timezone.utc).isoformat()
                return

        all_events = open_events + closed_events
        _update(total_events=len(all_events), phase="upserting")

        now = datetime.now(timezone.utc).isoformat()

        # Phase 3: Upsert events + markets
        for event in all_events:
            with _lock:
                if _state.cancel_requested:
                    _state.phase = "cancelled"
                    _state.running = False
                    _state.finished_at = datetime.now(timezone.utc).isoformat()
                    return

            is_closed = event.get("closed", False)

            # Skip closed events we already have
            if is_closed and event.get("id") in known_closed_ids:
                _update(
                    skipped_events=_state.skipped_events + 1,
                    processed_events=_state.processed_events + 1,
                )
                continue

            upsert_event(conn, event, now)
            _update(new_events=_state.new_events + 1)

            for market in event.get("markets", []):
                upsert_market(conn, market, event["id"], now)
                _update(new_markets=_state.new_markets + 1)

                if not is_closed:
                    insert_snapshot(conn, market, now)
                    _update(snapshots=_state.snapshots + 1)

            _update(processed_events=_state.processed_events + 1)

        conn.commit()

        # Phase 4: Rebuild tag table
        _update(phase="building_tags")
        create_indexes(conn)
        create_tag_table(conn)

        _update(
            phase="done",
            running=False,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        _update(
            phase="error",
            error=str(e),
            running=False,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        if conn is not None:
            return_connection(conn)


def sse_generator():
    """Yield SSE events with refresh state every 0.5s."""
    while True:
        state = get_state()
        yield f"data: {json.dumps(state)}\n\n"
        if not state["running"] and state["phase"] in ("done", "cancelled", "error", ""):
            break
        time.sleep(0.5)
