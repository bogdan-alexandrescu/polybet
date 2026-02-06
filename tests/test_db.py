"""Tests for db.py - database connection and initialization."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import db


class TestGetConnection:
    def test_returns_connection(self, test_db_path):
        with patch.object(db, 'DB_PATH', test_db_path):
            conn = db.get_connection()
            assert conn is not None
            assert conn.row_factory == sqlite3.Row
            conn.close()

    def test_row_factory_set(self, test_db_path):
        with patch.object(db, 'DB_PATH', test_db_path):
            conn = db.get_connection()
            row = conn.execute("SELECT 1 AS val").fetchone()
            assert row["val"] == 1
            conn.close()


class TestGetRWConnection:
    def test_returns_rw_connection(self, test_db_path):
        with patch.object(db, 'DB_PATH', test_db_path):
            conn = db.get_rw_connection()
            assert conn is not None
            # Should be able to write
            conn.execute("CREATE TABLE IF NOT EXISTS test_rw (id INTEGER)")
            conn.commit()
            conn.close()


class TestCreateIndexes:
    def test_creates_indexes(self, test_db_path):
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row
        db.create_indexes(conn)

        # Check that indexes exist
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i["name"] for i in indexes]

        assert "idx_markets_closed_volume" in index_names
        assert "idx_events_created" in index_names
        assert "idx_events_closed_volume" in index_names
        assert "idx_snapshots_fetched" in index_names
        conn.close()

    def test_idempotent(self, test_db_path):
        """Calling create_indexes twice should not fail."""
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row
        db.create_indexes(conn)
        db.create_indexes(conn)  # Should not raise
        conn.close()


class TestCreateTagTable:
    def test_creates_tag_table(self, test_db_path):
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row

        # Drop existing tag table first
        conn.execute("DROP TABLE IF EXISTS event_tags")
        conn.commit()

        db.create_tag_table(conn)

        rows = conn.execute("SELECT COUNT(*) AS cnt FROM event_tags").fetchone()
        assert rows["cnt"] > 0
        conn.close()

    def test_tag_table_has_correct_data(self, test_db_path):
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row

        conn.execute("DROP TABLE IF EXISTS event_tags")
        conn.commit()

        db.create_tag_table(conn)

        # Check specific tags
        politics = conn.execute(
            "SELECT * FROM event_tags WHERE tag_slug = 'politics'"
        ).fetchall()
        assert len(politics) > 0
        assert politics[0]["tag_label"] == "Politics"
        assert politics[0]["event_id"] == "evt_1"
        conn.close()

    def test_recreates_on_call(self, test_db_path):
        """Calling create_tag_table twice should work (drops and recreates)."""
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row
        db.create_tag_table(conn)
        count1 = conn.execute("SELECT COUNT(*) FROM event_tags").fetchone()[0]
        db.create_tag_table(conn)
        count2 = conn.execute("SELECT COUNT(*) FROM event_tags").fetchone()[0]
        assert count1 == count2
        conn.close()

    def test_excludes_null_and_empty_tags(self, test_db_path):
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row

        conn.execute("DROP TABLE IF EXISTS event_tags")
        conn.commit()

        db.create_tag_table(conn)

        # evt_4 has "[]" and evt_5 has NULL tags - should not appear
        evt4 = conn.execute(
            "SELECT * FROM event_tags WHERE event_id = 'evt_4'"
        ).fetchall()
        evt5 = conn.execute(
            "SELECT * FROM event_tags WHERE event_id = 'evt_5'"
        ).fetchall()
        assert len(evt4) == 0
        assert len(evt5) == 0
        conn.close()


class TestInitAnalyticsDb:
    def test_init_runs(self, test_db_path):
        with patch.object(db, 'DB_PATH', test_db_path):
            db.init_analytics_db()  # Should not raise
