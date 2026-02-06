"""Database connection and initialization for Polybet analytics."""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "polybet.db"


def get_connection():
    """Get a read-only SQLite connection with optimized settings."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-65536")  # 64MB cache
    conn.execute("PRAGMA mmap_size=1073741824")  # 1GB mmap
    conn.execute("PRAGMA query_only=ON")
    return conn


def get_rw_connection():
    """Get a read-write connection for initialization tasks."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_indexes(conn):
    """Create analytics indexes if they don't exist."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_markets_closed_volume ON markets(closed, volume DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_events_closed_volume ON events(closed, volume DESC)",
        "CREATE INDEX IF NOT EXISTS idx_snapshots_fetched ON price_snapshots(fetched_at)",
    ]
    for sql in indexes:
        conn.execute(sql)
    conn.commit()


def create_tag_table(conn):
    """Create and populate the materialized event_tags table."""
    conn.execute("DROP TABLE IF EXISTS event_tags")
    conn.execute("""
        CREATE TABLE event_tags (
            event_id TEXT,
            tag_label TEXT,
            tag_slug TEXT
        )
    """)
    conn.execute("""
        INSERT INTO event_tags (event_id, tag_label, tag_slug)
        SELECT e.id,
               json_extract(t.value, '$.label'),
               json_extract(t.value, '$.slug')
        FROM events e, json_each(e.tags) t
        WHERE e.tags IS NOT NULL AND e.tags != '[]'
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_event_tags_slug ON event_tags(tag_slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_event_tags_event ON event_tags(event_id)")
    conn.commit()


def init_analytics_db():
    """Run all startup initialization (indexes + tag table)."""
    conn = get_rw_connection()
    try:
        print("Creating analytics indexes...")
        t0 = time.time()
        create_indexes(conn)
        print(f"  Indexes created in {time.time() - t0:.1f}s")

        print("Building materialized tag table...")
        t0 = time.time()
        create_tag_table(conn)
        count = conn.execute("SELECT COUNT(*) FROM event_tags").fetchone()[0]
        print(f"  Tag table populated with {count:,} rows in {time.time() - t0:.1f}s")
    finally:
        conn.close()
