#!/usr/bin/env python3
"""Pull all open markets from Polymarket and cache them in PostgreSQL.

On each run:
  - Fetches all open events/markets from the Gamma API
  - Inserts new events and markets
  - Updates existing events and markets with latest data
  - Records a price snapshot for every market (for time-series analysis)
"""

import json
from datetime import datetime, timezone

import requests

from db import get_connection, return_connection

GAMMA_API = "https://gamma-api.polymarket.com"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(conn):
    conn.execute("""
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
            tags            TEXT,
            created_at      TEXT,
            updated_at      TEXT,
            first_seen      TEXT NOT NULL,
            last_synced     TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            id                  TEXT PRIMARY KEY,
            event_id            TEXT REFERENCES events(id),
            question            TEXT,
            slug                TEXT,
            condition_id        TEXT,
            description         TEXT,
            group_item_title    TEXT,
            outcomes            TEXT,
            outcome_prices      TEXT,
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
            clob_token_ids      TEXT,
            accepting_orders    INTEGER,
            created_at          TEXT,
            updated_at          TEXT,
            first_seen          TEXT NOT NULL,
            last_synced         TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id              SERIAL PRIMARY KEY,
            market_id       TEXT NOT NULL REFERENCES markets(id),
            outcome_prices  TEXT,
            volume          REAL,
            liquidity       REAL,
            spread          REAL,
            best_ask        REAL,
            last_trade_price REAL,
            fetched_at      TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_market
            ON price_snapshots(market_id, fetched_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_markets_event
            ON markets(event_id)
    """)
    conn.commit()


def upsert_event(conn, event, now):
    """Insert or update an event row using ON CONFLICT. Returns True if newly inserted."""
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
        "first_seen":     now,
        "last_synced":    now,
    }

    result = conn.execute("""
        INSERT INTO events (id, ticker, slug, title, description, start_date, end_date,
            active, closed, neg_risk, liquidity, volume, volume_24hr, volume_1wk,
            volume_1mo, volume_1yr, open_interest, comment_count, tags, created_at,
            updated_at, first_seen, last_synced)
        VALUES (%(id)s, %(ticker)s, %(slug)s, %(title)s, %(description)s, %(start_date)s,
            %(end_date)s, %(active)s, %(closed)s, %(neg_risk)s, %(liquidity)s, %(volume)s,
            %(volume_24hr)s, %(volume_1wk)s, %(volume_1mo)s, %(volume_1yr)s,
            %(open_interest)s, %(comment_count)s, %(tags)s, %(created_at)s,
            %(updated_at)s, %(first_seen)s, %(last_synced)s)
        ON CONFLICT (id) DO UPDATE SET
            ticker = EXCLUDED.ticker, slug = EXCLUDED.slug, title = EXCLUDED.title,
            description = EXCLUDED.description, start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date, active = EXCLUDED.active, closed = EXCLUDED.closed,
            neg_risk = EXCLUDED.neg_risk, liquidity = EXCLUDED.liquidity, volume = EXCLUDED.volume,
            volume_24hr = EXCLUDED.volume_24hr, volume_1wk = EXCLUDED.volume_1wk,
            volume_1mo = EXCLUDED.volume_1mo, volume_1yr = EXCLUDED.volume_1yr,
            open_interest = EXCLUDED.open_interest, comment_count = EXCLUDED.comment_count,
            tags = EXCLUDED.tags, created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at, last_synced = EXCLUDED.last_synced
    """, values)

    # xmax = 0 means the row was inserted (not updated)
    return result.statusmessage.startswith("INSERT") and result.rowcount == 1


def upsert_market(conn, market, event_id, now):
    """Insert or update a market row using ON CONFLICT. Returns True if newly inserted."""
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
        "first_seen":        now,
        "last_synced":       now,
    }

    conn.execute("""
        INSERT INTO markets (id, event_id, question, slug, condition_id, description,
            group_item_title, outcomes, outcome_prices, volume, volume_clob, volume_1wk,
            volume_1mo, volume_1yr, liquidity, spread, best_ask, last_trade_price,
            one_day_change, one_week_change, one_month_change, start_date, end_date,
            active, closed, neg_risk, clob_token_ids, accepting_orders, created_at,
            updated_at, first_seen, last_synced)
        VALUES (%(id)s, %(event_id)s, %(question)s, %(slug)s, %(condition_id)s,
            %(description)s, %(group_item_title)s, %(outcomes)s, %(outcome_prices)s,
            %(volume)s, %(volume_clob)s, %(volume_1wk)s, %(volume_1mo)s, %(volume_1yr)s,
            %(liquidity)s, %(spread)s, %(best_ask)s, %(last_trade_price)s,
            %(one_day_change)s, %(one_week_change)s, %(one_month_change)s,
            %(start_date)s, %(end_date)s, %(active)s, %(closed)s, %(neg_risk)s,
            %(clob_token_ids)s, %(accepting_orders)s, %(created_at)s, %(updated_at)s,
            %(first_seen)s, %(last_synced)s)
        ON CONFLICT (id) DO UPDATE SET
            event_id = EXCLUDED.event_id, question = EXCLUDED.question, slug = EXCLUDED.slug,
            condition_id = EXCLUDED.condition_id, description = EXCLUDED.description,
            group_item_title = EXCLUDED.group_item_title, outcomes = EXCLUDED.outcomes,
            outcome_prices = EXCLUDED.outcome_prices, volume = EXCLUDED.volume,
            volume_clob = EXCLUDED.volume_clob, volume_1wk = EXCLUDED.volume_1wk,
            volume_1mo = EXCLUDED.volume_1mo, volume_1yr = EXCLUDED.volume_1yr,
            liquidity = EXCLUDED.liquidity, spread = EXCLUDED.spread,
            best_ask = EXCLUDED.best_ask, last_trade_price = EXCLUDED.last_trade_price,
            one_day_change = EXCLUDED.one_day_change, one_week_change = EXCLUDED.one_week_change,
            one_month_change = EXCLUDED.one_month_change, start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date, active = EXCLUDED.active, closed = EXCLUDED.closed,
            neg_risk = EXCLUDED.neg_risk, clob_token_ids = EXCLUDED.clob_token_ids,
            accepting_orders = EXCLUDED.accepting_orders, created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at, last_synced = EXCLUDED.last_synced
    """, values)


def insert_snapshot(conn, market, now):
    conn.execute(
        """INSERT INTO price_snapshots
           (market_id, outcome_prices, volume, liquidity, spread, best_ask, last_trade_price, fetched_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
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


def iter_events(page_size=100, closed=None, label=""):
    """Yield events one page at a time to avoid loading all into memory."""
    offset = 0
    total_fetched = 0
    while True:
        events = fetch_events(limit=page_size, offset=offset, closed=closed)
        if not events:
            break
        total_fetched += len(events)
        print(f"  {label}Fetched {total_fetched} events...", flush=True)
        yield events
        if len(events) < page_size:
            break
        offset += page_size


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        init_db(conn)

        # Check what we already have
        prev_event_count = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"]
        prev_market_count = conn.execute("SELECT COUNT(*) AS cnt FROM markets").fetchone()["cnt"]
        print(f"Database: {prev_event_count} events, {prev_market_count} markets cached")
        print()

        # Fetch open markets (always) and closed markets (only if not yet in db)
        print("Fetching open markets...")
        open_events = fetch_all_events(closed=False, label="[open] ")

        # Only fetch closed markets we haven't seen yet
        known_event_ids = set()
        if prev_event_count > 0:
            rows = conn.execute("SELECT id FROM events WHERE closed = 1").fetchall()
            known_event_ids = {r["id"] for r in rows}

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

            upsert_event(conn, event, now)
            # We can't easily distinguish insert vs update with ON CONFLICT,
            # so we just count total processed
            new_events += 1

            for market in event.get("markets", []):
                upsert_market(conn, market, event["id"], now)
                new_markets += 1

                # Only snapshot open markets (closed prices are frozen)
                if not is_closed:
                    insert_snapshot(conn, market, now)
                    snapshots += 1

        conn.commit()

        # Final counts
        total_events = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"]
        total_markets_db = conn.execute("SELECT COUNT(*) AS cnt FROM markets").fetchone()["cnt"]
        total_snapshots = conn.execute("SELECT COUNT(*) AS cnt FROM price_snapshots").fetchone()["cnt"]

        print(f"Events:    {new_events} processed, {skipped_events} skipped  (total in db: {total_events})")
        print(f"Markets:   {new_markets} processed  (total in db: {total_markets_db})")
        print(f"Snapshots: {snapshots} recorded  (total in db: {total_snapshots})")
    finally:
        return_connection(conn)


if __name__ == "__main__":
    main()
