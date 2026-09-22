"""D5A 迁移 v5 的报名、组织方与场馆数据边界。"""

from __future__ import annotations

import sqlite3

import pytest

from app import db as db_module
from app.migrations import apply_migrations


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_empty_database_has_v5_registration_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "fresh.db"))
    db_module.init_db()

    conn = db_module.connect()
    try:
        assert {
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        } == {1, 2, 3, 4, 5}
        assert "registration_enabled" in _column_names(conn, "tournaments")
        assert {
            "id",
            "tournament_id",
            "name",
            "affiliation",
            "contact",
            "rating_points",
            "status",
            "confirmed_player_id",
            "confirmed_by_user_id",
            "confirmed_at",
            "created_at",
            "updated_at",
        } <= _column_names(conn, "registrations")
        assert {
            "tournament_id",
            "name",
            "contact_name",
            "contact",
            "note",
        } <= _column_names(conn, "organizations")
        assert {
            "tournament_id",
            "name",
            "address",
            "contact_name",
            "contact",
            "note",
        } <= _column_names(conn, "venues")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_v4_database_upgrades_without_enabling_registration(tmp_path, monkeypatch):
    path = tmp_path / "v4.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE tournaments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                date TEXT NOT NULL
            );
            CREATE TABLE players (id INTEGER PRIMARY KEY);
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO tournaments (id, name, date) VALUES (1, '历史赛事', '2026-01-01');
            INSERT INTO schema_migrations (version, name) VALUES
                (1, 'master baseline'),
                (2, 'auth_users_and_admins'),
                (3, 'bootstrap_state_and_user_profile'),
                (4, 'tournament_format_config');
            """
        )
        conn.commit()

        assert apply_migrations(conn) == (5,)
        assert conn.execute(
            "SELECT registration_enabled FROM tournaments WHERE id = 1"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('registrations', 'organizations', 'venues')"
        ).fetchall() != []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_registration_status_check_prevents_half_confirmed_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "constraints.db"))
    db_module.init_db()
    conn = db_module.connect()
    try:
        conn.execute(
            "INSERT INTO tournaments (name, date, table_count, group_count, "
            "qualify_per_group) VALUES ('约束赛事', '2026-01-01', 1, 1, 1)"
        )
        tournament_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO registrations "
                "(tournament_id, name, status, confirmed_at) "
                "VALUES (?, '半状态', 'CONFIRMED', datetime('now'))",
                (tournament_id,),
            )
        conn.rollback()
    finally:
        conn.close()
