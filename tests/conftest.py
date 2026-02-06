"""Shared fixtures for Polybet test suite (PostgreSQL)."""

import json
import os
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://localhost:5432/polybet_test"
)


def create_test_db(conn):
    """Create test tables and populate with realistic sample data."""
    # Drop existing tables in reverse dependency order
    conn.execute("DROP TABLE IF EXISTS price_snapshots CASCADE")
    conn.execute("DROP TABLE IF EXISTS markets CASCADE")
    conn.execute("DROP TABLE IF EXISTS event_tags CASCADE")
    conn.execute("DROP TABLE IF EXISTS events CASCADE")
    conn.execute("DROP TABLE IF EXISTS settings CASCADE")
    conn.commit()

    conn.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY, ticker TEXT, slug TEXT, title TEXT,
            description TEXT, start_date TEXT, end_date TEXT,
            active INTEGER, closed INTEGER, neg_risk INTEGER,
            liquidity REAL, volume REAL, volume_24hr REAL,
            volume_1wk REAL, volume_1mo REAL, volume_1yr REAL,
            open_interest INTEGER, comment_count INTEGER,
            tags TEXT, created_at TEXT, updated_at TEXT,
            first_seen TEXT NOT NULL, last_synced TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE markets (
            id TEXT PRIMARY KEY, event_id TEXT REFERENCES events(id),
            question TEXT, slug TEXT, condition_id TEXT,
            description TEXT, group_item_title TEXT,
            outcomes TEXT, outcome_prices TEXT,
            volume REAL, volume_clob REAL, volume_1wk REAL,
            volume_1mo REAL, volume_1yr REAL, liquidity REAL,
            spread REAL, best_ask REAL, last_trade_price REAL,
            one_day_change REAL, one_week_change REAL,
            one_month_change REAL, start_date TEXT, end_date TEXT,
            active INTEGER, closed INTEGER, neg_risk INTEGER,
            clob_token_ids TEXT, accepting_orders INTEGER,
            created_at TEXT, updated_at TEXT,
            first_seen TEXT NOT NULL, last_synced TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE price_snapshots (
            id SERIAL PRIMARY KEY,
            market_id TEXT NOT NULL REFERENCES markets(id),
            outcome_prices TEXT, volume REAL, liquidity REAL,
            spread REAL, best_ask REAL, last_trade_price REAL,
            fetched_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.execute("""
        CREATE INDEX idx_snapshots_market ON price_snapshots(market_id, fetched_at)
    """)
    conn.execute("""
        CREATE INDEX idx_markets_event ON markets(event_id)
    """)
    conn.commit()

    # Insert sample events
    events = [
        ("evt_1", "POLITICS", "us-election", "Will candidate X win?",
         "Election market", "2024-01-01T00:00:00Z", "2024-11-01T00:00:00Z",
         1, 0, 0, 500000.0, 2000000.0, 50000.0, 200000.0, 500000.0, 1800000.0,
         100, 50,
         json.dumps([{"label": "Politics", "slug": "politics"}, {"label": "Elections", "slug": "elections"}]),
         "2024-01-15T00:00:00Z", "2024-06-01T00:00:00Z",
         "2024-01-15T00:00:00Z", "2024-06-01T00:00:00Z"),
        ("evt_2", "CRYPTO", "btc-price", "Will BTC reach $100k?",
         "Crypto market", "2024-03-01T00:00:00Z", "2024-12-31T00:00:00Z",
         1, 0, 0, 300000.0, 1500000.0, 30000.0, 150000.0, 400000.0, 1400000.0,
         80, 30,
         json.dumps([{"label": "Crypto Prices", "slug": "crypto-prices"}]),
         "2024-03-10T00:00:00Z", "2024-06-01T00:00:00Z",
         "2024-03-10T00:00:00Z", "2024-06-01T00:00:00Z"),
        ("evt_3", "SPORTS", "super-bowl", "Super Bowl winner",
         "Sports event", "2024-01-01T00:00:00Z", "2024-02-15T00:00:00Z",
         0, 1, 0, 0.0, 800000.0, 0.0, 0.0, 0.0, 800000.0,
         0, 20,
         json.dumps([{"label": "Sports", "slug": "sports"}, {"label": "Football", "slug": "football"}]),
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z",
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z"),
        ("evt_4", "EMPTY", "empty-event", "Empty tags event",
         "No tags", None, None, 0, 1, 0, 0.0, 100.0, 0.0, 0.0, 0.0, 100.0,
         0, 0, "[]",
         "2024-05-01T00:00:00Z", "2024-05-01T00:00:00Z",
         "2024-05-01T00:00:00Z", "2024-05-01T00:00:00Z"),
        ("evt_5", "NULLTAGS", "null-tags", "Null tags event",
         "No tags at all", None, None, 0, 1, 0, 0.0, 50.0, 0.0, 0.0, 0.0, 50.0,
         0, 0, None,
         "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
         "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ]

    for e in events:
        conn.execute("""
            INSERT INTO events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, e)

    # Insert sample markets
    markets = [
        # Open market with good data
        ("mkt_1", "evt_1", "Will X win the election?", "x-election", "cond1",
         "Election market", "Candidate X",
         json.dumps(["Yes", "No"]), json.dumps(["0.65", "0.35"]),
         1500000.0, 1400000.0, 150000.0, 400000.0, 1400000.0,
         250000.0, 0.03, 0.66, 0.65, 0.05, 0.10, 0.15,
         "2024-01-15T00:00:00Z", "2024-11-01T00:00:00Z",
         1, 0, 0, json.dumps(["token1", "token2"]), 1,
         "2024-01-15T00:00:00Z", "2024-06-01T00:00:00Z",
         "2024-01-15T00:00:00Z", "2024-06-01T00:00:00Z"),
        # Another open market
        ("mkt_2", "evt_1", "Will Y win the election?", "y-election", "cond2",
         "Election market", "Candidate Y",
         json.dumps(["Yes", "No"]), json.dumps(["0.35", "0.65"]),
         800000.0, 750000.0, 80000.0, 200000.0, 750000.0,
         180000.0, 0.04, 0.36, 0.35, -0.05, -0.10, -0.15,
         "2024-01-15T00:00:00Z", "2024-11-01T00:00:00Z",
         1, 0, 0, json.dumps(["token3", "token4"]), 1,
         "2024-01-15T00:00:00Z", "2024-06-01T00:00:00Z",
         "2024-01-15T00:00:00Z", "2024-06-01T00:00:00Z"),
        # BTC market (open)
        ("mkt_3", "evt_2", "BTC above $100k by Dec 2024?", "btc-100k", "cond3",
         "Bitcoin price market", None,
         json.dumps(["Up", "Down"]), json.dumps(["0.40", "0.60"]),
         1200000.0, 1100000.0, 100000.0, 300000.0, 1100000.0,
         200000.0, 0.02, 0.41, 0.40, 0.02, -0.03, 0.08,
         "2024-03-10T00:00:00Z", "2024-12-31T00:00:00Z",
         1, 0, 0, None, 1,
         "2024-03-10T00:00:00Z", "2024-06-01T00:00:00Z",
         "2024-03-10T00:00:00Z", "2024-06-01T00:00:00Z"),
        # Resolved Yes market
        ("mkt_4", "evt_3", "Will Team A win Super Bowl?", "team-a-sb", "cond4",
         "Super Bowl", "Team A",
         json.dumps(["Yes", "No"]), json.dumps(["0.98", "0.02"]),
         600000.0, 550000.0, 0.0, 0.0, 550000.0,
         0.0, 0.0, 0.99, 0.98, 0.0, 0.0, 0.0,
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z",
         0, 1, 0, None, 0,
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z",
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z"),
        # Resolved No market
        ("mkt_5", "evt_3", "Will Team B win Super Bowl?", "team-b-sb", "cond5",
         "Super Bowl", "Team B",
         json.dumps(["Yes", "No"]), json.dumps(["0.02", "0.98"]),
         400000.0, 380000.0, 0.0, 0.0, 380000.0,
         0.0, 0.0, 0.01, 0.02, 0.0, 0.0, 0.0,
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z",
         0, 1, 0, None, 0,
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z",
         "2023-09-01T00:00:00Z", "2024-02-15T00:00:00Z"),
        # Resolved ambiguous market
        ("mkt_6", "evt_4", "Ambiguous market", "ambiguous", "cond6",
         "Test", None,
         json.dumps(["Yes", "No"]), json.dumps(["0.50", "0.50"]),
         100.0, 90.0, 0.0, 0.0, 90.0,
         0.0, 0.0, 0.51, 0.50, 0.0, 0.0, 0.0,
         None, None,
         0, 1, 0, None, 0,
         "2024-05-01T00:00:00Z", "2024-05-01T00:00:00Z",
         "2024-05-01T00:00:00Z", "2024-05-01T00:00:00Z"),
        # Market with zero/null volume
        ("mkt_7", "evt_5", "Zero volume market", "zero-vol", "cond7",
         "Test", None,
         json.dumps(["Yes", "No"]), json.dumps(["0.50", "0.50"]),
         0.0, 0.0, 0.0, 0.0, 0.0,
         0.0, None, None, None, None, None, None,
         None, None,
         0, 1, 0, None, 0,
         "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
         "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ]

    for m in markets:
        conn.execute("""
            INSERT INTO markets VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, m)

    # Insert price snapshots
    snapshots = [
        ("mkt_1", json.dumps(["0.55", "0.45"]), 1000000.0, 200000.0, 0.03, 0.56, 0.55, "2024-02-01T00:00:00Z"),
        ("mkt_1", json.dumps(["0.60", "0.40"]), 1200000.0, 220000.0, 0.03, 0.61, 0.60, "2024-03-01T00:00:00Z"),
        ("mkt_1", json.dumps(["0.65", "0.35"]), 1500000.0, 250000.0, 0.03, 0.66, 0.65, "2024-06-01T00:00:00Z"),
        ("mkt_3", json.dumps(["0.30", "0.70"]), 800000.0, 150000.0, 0.02, 0.31, 0.30, "2024-04-01T00:00:00Z"),
        ("mkt_3", json.dumps(["0.40", "0.60"]), 1200000.0, 200000.0, 0.02, 0.41, 0.40, "2024-06-01T00:00:00Z"),
        ("mkt_4", json.dumps(["0.70", "0.30"]), 400000.0, 100000.0, 0.04, 0.71, 0.70, "2023-10-01T00:00:00Z"),
        ("mkt_4", json.dumps(["0.98", "0.02"]), 600000.0, 0.0, 0.0, 0.99, 0.98, "2024-02-15T00:00:00Z"),
        ("mkt_5", json.dumps(["0.30", "0.70"]), 200000.0, 80000.0, 0.04, 0.31, 0.30, "2023-10-01T00:00:00Z"),
    ]

    for s in snapshots:
        conn.execute("""
            INSERT INTO price_snapshots (market_id, outcome_prices, volume, liquidity, spread, best_ask, last_trade_price, fetched_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, s)

    # Create event_tags table using PG JSON functions
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
    conn.execute("CREATE INDEX idx_event_tags_slug ON event_tags(tag_slug)")
    conn.execute("CREATE INDEX idx_event_tags_event ON event_tags(event_id)")

    conn.commit()


@pytest.fixture(scope="session")
def _test_db():
    """Create the test database once per test session."""
    conn = psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row, autocommit=False)
    create_test_db(conn)
    conn.close()


@pytest.fixture
def test_conn(_test_db):
    """Provide a connection to the test database per test."""
    conn = psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row, autocommit=False)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def test_db_path(_test_db):
    """Compatibility fixture — returns the DATABASE_URL for PG."""
    return TEST_DATABASE_URL


@pytest.fixture
def app_client(_test_db):
    """Provide a Flask test client with mocked database."""
    import db as db_module

    def mock_get_connection():
        return psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row)

    def mock_return_connection(conn):
        conn.close()

    def mock_init():
        pass

    with patch.object(db_module, 'get_connection', mock_get_connection), \
         patch.object(db_module, 'return_connection', mock_return_connection), \
         patch.object(db_module, 'init_analytics_db', mock_init), \
         patch('app.get_connection', mock_get_connection), \
         patch('app.return_connection', mock_return_connection), \
         patch('app.init_analytics_db', mock_init):
        from app import create_app
        test_app = create_app()
        test_app.config['TESTING'] = True
        with test_app.test_client() as client:
            yield client
