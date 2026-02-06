"""Tests for db.py - database connection and initialization (PostgreSQL)."""

import os
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
import pytest

import db

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://localhost:5432/polybet_test"
)


class TestGetConnection:
    def test_returns_connection(self, _test_db):
        with patch.object(db, 'DATABASE_URL', TEST_DATABASE_URL), \
             patch.object(db, '_pool', None):
            conn = db.get_connection()
            assert conn is not None
            db.return_connection(conn)
            db.close_pool()

    def test_dict_row_factory(self, _test_db):
        with patch.object(db, 'DATABASE_URL', TEST_DATABASE_URL), \
             patch.object(db, '_pool', None):
            conn = db.get_connection()
            row = conn.execute("SELECT 1 AS val").fetchone()
            assert row["val"] == 1
            db.return_connection(conn)
            db.close_pool()


class TestReturnConnection:
    def test_return_connection(self, _test_db):
        with patch.object(db, 'DATABASE_URL', TEST_DATABASE_URL), \
             patch.object(db, '_pool', None):
            conn = db.get_connection()
            db.return_connection(conn)  # Should not raise
            db.close_pool()


class TestClosePool:
    def test_close_pool(self, _test_db):
        with patch.object(db, 'DATABASE_URL', TEST_DATABASE_URL), \
             patch.object(db, '_pool', None):
            conn = db.get_connection()
            db.return_connection(conn)
            db.close_pool()
            assert db._pool is None

    def test_close_pool_when_none(self):
        with patch.object(db, '_pool', None):
            db.close_pool()  # Should not raise
            assert db._pool is None


class TestCreateIndexes:
    def test_creates_indexes(self, test_conn):
        db.create_indexes(test_conn)

        indexes = test_conn.execute("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public'
        """).fetchall()
        index_names = [i["indexname"] for i in indexes]

        assert "idx_markets_closed_volume" in index_names
        assert "idx_events_created" in index_names
        assert "idx_events_closed_volume" in index_names
        assert "idx_snapshots_fetched" in index_names

    def test_idempotent(self, test_conn):
        """Calling create_indexes twice should not fail."""
        db.create_indexes(test_conn)
        db.create_indexes(test_conn)  # Should not raise


class TestCreateTagTable:
    def test_creates_tag_table(self, test_conn):
        test_conn.execute("DROP TABLE IF EXISTS event_tags")
        test_conn.commit()

        db.create_tag_table(test_conn)

        rows = test_conn.execute("SELECT COUNT(*) AS cnt FROM event_tags").fetchone()
        assert rows["cnt"] > 0

    def test_tag_table_has_correct_data(self, test_conn):
        test_conn.execute("DROP TABLE IF EXISTS event_tags")
        test_conn.commit()

        db.create_tag_table(test_conn)

        politics = test_conn.execute(
            "SELECT * FROM event_tags WHERE tag_slug = 'politics'"
        ).fetchall()
        assert len(politics) > 0
        assert politics[0]["tag_label"] == "Politics"
        assert politics[0]["event_id"] == "evt_1"

    def test_recreates_on_call(self, test_conn):
        """Calling create_tag_table twice should work (drops and recreates)."""
        db.create_tag_table(test_conn)
        count1 = test_conn.execute("SELECT COUNT(*) AS cnt FROM event_tags").fetchone()["cnt"]
        db.create_tag_table(test_conn)
        count2 = test_conn.execute("SELECT COUNT(*) AS cnt FROM event_tags").fetchone()["cnt"]
        assert count1 == count2

    def test_excludes_null_and_empty_tags(self, test_conn):
        test_conn.execute("DROP TABLE IF EXISTS event_tags")
        test_conn.commit()

        db.create_tag_table(test_conn)

        # evt_4 has "[]" and evt_5 has NULL tags - should not appear
        evt4 = test_conn.execute(
            "SELECT * FROM event_tags WHERE event_id = 'evt_4'"
        ).fetchall()
        evt5 = test_conn.execute(
            "SELECT * FROM event_tags WHERE event_id = 'evt_5'"
        ).fetchall()
        assert len(evt4) == 0
        assert len(evt5) == 0


class TestInitAnalyticsDb:
    def test_init_runs(self, _test_db):
        with patch.object(db, 'DATABASE_URL', TEST_DATABASE_URL), \
             patch.object(db, '_pool', None):
            db.init_analytics_db()  # Should not raise
            db.close_pool()
