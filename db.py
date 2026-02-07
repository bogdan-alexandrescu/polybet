"""Database connection pool and initialization for Polybet analytics (PostgreSQL)."""

import os
import time

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://localhost:5432/polybet"
)

_pool = None


def get_pool():
    """Return the global connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            open=True,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def get_connection():
    """Borrow a connection from the pool."""
    return get_pool().getconn()


def return_connection(conn):
    """Return a connection to the pool."""
    try:
        conn.rollback()
    except Exception:
        pass
    get_pool().putconn(conn)


def close_pool():
    """Close the connection pool (for graceful shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


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
               t.value->>'label',
               t.value->>'slug'
        FROM events e,
             jsonb_array_elements(e.tags::jsonb) AS t(value)
        WHERE e.tags IS NOT NULL AND e.tags != '[]'
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_event_tags_slug ON event_tags(tag_slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_event_tags_event ON event_tags(event_id)")
    conn.commit()


def init_analytics_db():
    """Run all startup initialization (indexes + tag table + settings table).

    Resilient to missing tables on fresh deploys — logs warnings instead of crashing.
    """
    conn = get_connection()
    try:
        # Create settings table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_jobs (
                id SERIAL PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'running',
                source TEXT NOT NULL DEFAULT 'web',
                phase TEXT NOT NULL DEFAULT '',
                total_events INT DEFAULT 0,
                processed_events INT DEFAULT 0,
                new_events INT DEFAULT 0,
                updated_events INT DEFAULT 0,
                skipped_events INT DEFAULT 0,
                new_markets INT DEFAULT 0,
                updated_markets INT DEFAULT 0,
                snapshots INT DEFAULT 0,
                error TEXT,
                cancel_requested BOOLEAN DEFAULT FALSE,
                started_at TIMESTAMP DEFAULT NOW(),
                finished_at TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_logs (
                id SERIAL PRIMARY KEY,
                job_id INT NOT NULL REFERENCES refresh_jobs(id),
                line TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_refresh_logs_job
            ON refresh_logs(job_id, id)
        """)
        conn.commit()

        # Check if core tables exist before creating indexes/tags
        has_tables = conn.execute("""
            SELECT COUNT(*) AS cnt FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name IN ('events', 'markets', 'price_snapshots')
        """).fetchone()["cnt"]

        if has_tables < 3:
            print("Core tables not yet created — skipping indexes and tag table.")
            return

        print("Creating analytics indexes...")
        t0 = time.time()
        create_indexes(conn)
        print(f"  Indexes created in {time.time() - t0:.1f}s")

        print("Building materialized tag table...")
        t0 = time.time()
        create_tag_table(conn)
        count = conn.execute("SELECT COUNT(*) AS cnt FROM event_tags").fetchone()["cnt"]
        print(f"  Tag table populated with {count:,} rows in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"Warning: init_analytics_db failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        return_connection(conn)
