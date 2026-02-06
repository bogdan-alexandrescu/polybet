#!/usr/bin/env python3
"""Pull all open markets from Polymarket and cache them in a local SQLite database.

On each run:
  - Fetches all open events/markets from the Gamma API
  - Inserts new events and markets
  - Updates existing events and markets with latest data
  - Records a price snapshot for every market (for time-series analysis)
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH = Path(__file__).parent / "polybet.db"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id              TEXT PRIMARY KEY,
            ticker          TEXT,
            slug            TEXT,
            title           TEXT,
            description     TEXT,
            start_date      TEXT,
            end_date        TEXT,
            active          INTEGER,
            closed          INTEGER,
            neg_risk        INTEGER,
            liquidity       REAL,
            volume          REAL,
            volume_24hr     REAL,
            volume_1wk      REAL,
            volume_1mo      REAL,
            volume_1yr      REAL,
            open_interest   INTEGER,
            comment_count   INTEGER,
            tags            TEXT,       -- JSON array
            created_at      TEXT,
            updated_at      TEXT,
            first_seen      TEXT NOT NULL,
            last_synced     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS markets (
            id                  TEXT PRIMARY KEY,
            event_id            TEXT REFERENCES events(id),
            question            TEXT,
            slug                TEXT,
            condition_id        TEXT,
            description         TEXT,
            group_item_title    TEXT,
            outcomes            TEXT,       -- JSON array e.g. '["Yes","No"]'
            outcome_prices      TEXT,       -- JSON array e.g. '[0.65, 0.35]'
            volume              REAL,
            volume_clob         REAL,
            volume_1wk          REAL,
            volume_1mo          REAL,
            volume_1yr          REAL,
            liquidity           REAL,
            spread              REAL,
            best_ask            REAL,
            last_trade_price    REAL,
            one_day_change      REAL,
            one_week_change     REAL,
            one_month_change    REAL,
            start_date          TEXT,
            end_date            TEXT,
            active              INTEGER,
            closed              INTEGER,
            neg_risk            INTEGER,
            clob_token_ids      TEXT,       -- JSON array
            accepting_orders    INTEGER,
            created_at          TEXT,
            updated_at          TEXT,
            first_seen          TEXT NOT NULL,
            last_synced         TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id       TEXT NOT NULL REFERENCES markets(id),
            outcome_prices  TEXT,       -- JSON array
            volume          REAL,
            liquidity       REAL,
            spread          REAL,
            best_ask        REAL,
            last_trade_price REAL,
            fetched_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_market
            ON price_snapshots(market_id, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_markets_event
            ON markets(event_id);
    """)


def upsert_event(conn, event, now):
    """Insert or update an event row. Returns True if newly inserted."""
    existing = conn.execute(
        "SELECT id FROM events WHERE id = ?", (event["id"],)
    ).fetchone()

    values = {
        "id":             event.get("id"),
        "ticker":         event.get("ticker"),
        "slug":           event.get("slug"),
        "title":          event.get("title"),
        "description":    event.get("description"),
        "start_date":     event.get("startDate"),
        "end_date":       event.get("endDate"),
        "active":         int(event.get("active", False)),
        "closed":         int(event.get("closed", False)),
        "neg_risk":       int(event.get("negRisk", False)),
        "liquidity":      event.get("liquidity"),
        "volume":         event.get("volume"),
        "volume_24hr":    event.get("volume24hr"),
        "volume_1wk":     event.get("volume1wk"),
        "volume_1mo":     event.get("volume1mo"),
        "volume_1yr":     event.get("volume1yr"),
        "open_interest":  event.get("openInterest"),
        "comment_count":  event.get("commentCount"),
        "tags":           json.dumps(event.get("tags", [])),
        "created_at":     event.get("createdAt"),
        "updated_at":     event.get("updatedAt"),
        "last_synced":    now,
    }

    if existing:
        sets = ", ".join(f"{k} = :{k}" for k in values if k != "id")
        conn.execute(f"UPDATE events SET {sets} WHERE id = :id", values)
        return False
    else:
        values["first_seen"] = now
        cols = ", ".join(values.keys())
        placeholders = ", ".join(f":{k}" for k in values)
        conn.execute(f"INSERT INTO events ({cols}) VALUES ({placeholders})", values)
        return True


def upsert_market(conn, market, event_id, now):
    """Insert or update a market row. Returns True if newly inserted."""
    existing = conn.execute(
        "SELECT id FROM markets WHERE id = ?", (market["id"],)
    ).fetchone()

    values = {
        "id":                market.get("id"),
        "event_id":          event_id,
        "question":          market.get("question"),
        "slug":              market.get("slug"),
        "condition_id":      market.get("conditionId"),
        "description":       market.get("description"),
        "group_item_title":  market.get("groupItemTitle"),
        "outcomes":          market.get("outcomes"),
        "outcome_prices":    market.get("outcomePrices"),
        "volume":            _float(market.get("volume")),
        "volume_clob":       market.get("volumeClob"),
        "volume_1wk":        market.get("volume1wk"),
        "volume_1mo":        market.get("volume1mo"),
        "volume_1yr":        market.get("volume1yr"),
        "liquidity":         market.get("liquidityClob", market.get("liquidity")),
        "spread":            market.get("spread"),
        "best_ask":          market.get("bestAsk"),
        "last_trade_price":  market.get("lastTradePrice"),
        "one_day_change":    market.get("oneDayPriceChange"),
        "one_week_change":   market.get("oneWeekPriceChange"),
        "one_month_change":  market.get("oneMonthPriceChange"),
        "start_date":        market.get("startDate"),
        "end_date":          market.get("endDate"),
        "active":            int(market.get("active", False)),
        "closed":            int(market.get("closed", False)),
        "neg_risk":          int(market.get("negRisk", False)),
        "clob_token_ids":    market.get("clobTokenIds"),
        "accepting_orders":  int(market.get("acceptingOrders", False)),
        "created_at":        market.get("createdAt"),
        "updated_at":        market.get("updatedAt"),
        "last_synced":       now,
    }

    if existing:
        sets = ", ".join(f"{k} = :{k}" for k in values if k != "id")
        conn.execute(f"UPDATE markets SET {sets} WHERE id = :id", values)
        return False
    else:
        values["first_seen"] = now
        cols = ", ".join(values.keys())
        placeholders = ", ".join(f":{k}" for k in values)
        conn.execute(f"INSERT INTO markets ({cols}) VALUES ({placeholders})", values)
        return True


def insert_snapshot(conn, market, now):
    conn.execute(
        """INSERT INTO price_snapshots
           (market_id, outcome_prices, volume, liquidity, spread, best_ask, last_trade_price, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            market.get("id"),
            market.get("outcomePrices"),
            _float(market.get("volume")),
            market.get("liquidityClob", market.get("liquidity")),
            market.get("spread"),
            market.get("bestAsk"),
            market.get("lastTradePrice"),
            now,
        ),
    )


def _float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_events(limit=100, offset=0, closed=None):
    params = {
        "order": "id",
        "ascending": "false",
        "limit": limit,
        "offset": offset,
    }
    if closed is not None:
        params["closed"] = str(closed).lower()
    resp = requests.get(f"{GAMMA_API}/events", params=params)
    resp.raise_for_status()
    return resp.json()


def fetch_all_events(page_size=100, closed=None, label=""):
    all_events = []
    offset = 0
    while True:
        events = fetch_events(limit=page_size, offset=offset, closed=closed)
        if not events:
            break
        all_events.extend(events)
        print(f"  {label}Fetched {len(all_events)} events...", flush=True)
        if len(events) < page_size:
            break
        offset += page_size
    return all_events


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)

    # Check what we already have
    prev_event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    prev_market_count = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    print(f"Database: {prev_event_count} events, {prev_market_count} markets cached")
    print()

    # Fetch open markets (always) and closed markets (only if not yet in db)
    print("Fetching open markets...")
    open_events = fetch_all_events(closed=False, label="[open] ")

    # Only fetch closed markets we haven't seen yet
    known_event_ids = set()
    if prev_event_count > 0:
        rows = conn.execute("SELECT id FROM events WHERE closed = 1").fetchall()
        known_event_ids = {r[0] for r in rows}

    print("\nFetching closed/resolved markets...")
    closed_events = fetch_all_events(closed=True, label="[closed] ")

    all_events = open_events + closed_events
    total_markets = sum(len(e.get("markets", [])) for e in all_events)
    print(f"\nAPI returned {len(all_events)} events with {total_markets} markets.")
    print(f"  ({len(open_events)} open, {len(closed_events)} closed)")
    print()

    new_events = 0
    updated_events = 0
    new_markets = 0
    updated_markets = 0
    skipped_events = 0
    snapshots = 0

    for event in all_events:
        is_closed = event.get("closed", False)

        # Skip closed events we already have (their data won't change)
        if is_closed and event.get("id") in known_event_ids:
            skipped_events += 1
            continue

        if upsert_event(conn, event, now):
            new_events += 1
        else:
            updated_events += 1

        for market in event.get("markets", []):
            if upsert_market(conn, market, event["id"], now):
                new_markets += 1
            else:
                updated_markets += 1

            # Only snapshot open markets (closed prices are frozen)
            if not is_closed:
                insert_snapshot(conn, market, now)
                snapshots += 1

    conn.commit()

    # Final counts
    total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    total_markets_db = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    total_snapshots = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]

    print(f"Events:    {new_events} new, {updated_events} updated, {skipped_events} skipped  (total in db: {total_events})")
    print(f"Markets:   {new_markets} new, {updated_markets} updated  (total in db: {total_markets_db})")
    print(f"Snapshots: {snapshots} recorded  (total in db: {total_snapshots})")
    print(f"\nDatabase saved to {DB_PATH}")

    conn.close()


if __name__ == "__main__":
    main()
