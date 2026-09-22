"""D2 A2.1：版本化迁移框架与旧库升级。"""

from __future__ import annotations

import sqlite3

from app import db as db_module
from app import repository as repo


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def test_empty_database_creates_auth_schema_and_records_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "empty.db"))

    db_module.init_db()
    conn = db_module.connect()
    try:
        assert {
            "users",
            "user_sessions",
            "tournament_admins",
            "system_state",
            "schema_migrations",
        } <= _table_names(conn)
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions == [1, 2, 3, 4, 5]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
        assert {
            "owner_user_id",
            "format_code",
            "rule_config",
            "rule_version",
            "registration_enabled",
        } <= columns
        assert {
            "registrations",
            "organizations",
            "venues",
        } <= _table_names(conn)
        user_columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(users)")
        }
        assert user_columns["phone"][3] == 0
        assert user_columns["note"][3] == 0
        assert conn.execute(
            "SELECT bootstrap_completed FROM system_state WHERE id = 1"
        ).fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "repeat.db"))

    db_module.init_db()
    db_module.init_db()
    conn = db_module.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 5
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_legacy_database_upgrade_preserves_existing_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "legacy.db"))

    legacy_sql = """
    CREATE TABLE tournaments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        table_count INTEGER NOT NULL CHECK (table_count BETWEEN 1 AND 15),
        group_count INTEGER NOT NULL CHECK (group_count BETWEEN 1 AND 26),
        qualify_per_group INTEGER NOT NULL CHECK (qualify_per_group >= 1),
        event_type TEXT NOT NULL DEFAULT 'SINGLES'
            CHECK (event_type IN ('SINGLES','DOUBLES','TEAM')),
        bronze_mode TEXT NOT NULL DEFAULT 'JOINT_BRONZE'
            CHECK (bronze_mode IN ('BRONZE_MATCH','JOINT_BRONZE')),
        placement_mode TEXT NOT NULL DEFAULT 'OFF'
            CHECK (placement_mode IN ('OFF','COMPLETE','TIERED')),
        games_to_win INTEGER NOT NULL DEFAULT 2 CHECK (games_to_win BETWEEN 1 AND 4),
        points_to_win INTEGER NOT NULL DEFAULT 11 CHECK (points_to_win >= 1),
        roster_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (roster_confirmed IN (0,1)),
        confirmed_at TEXT,
        operation_mode TEXT NOT NULL DEFAULT 'LIVE'
            CHECK (operation_mode IN ('LIVE','DEMO')),
        stage TEXT NOT NULL DEFAULT 'REGISTRATION'
            CHECK (stage IN ('REGISTRATION','GROUP_STAGE','KNOCKOUT','FINISHED')),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """

    conn = db_module.connect()
    try:
        conn.executescript(legacy_sql)
        conn.executemany(
            "INSERT INTO tournaments "
            "(name, date, table_count, group_count, qualify_per_group, event_type, "
            "games_to_win, points_to_win) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("历史赛事甲", "2025-01-01", 2, 1, 1, "SINGLES", 2, 11),
                ("历史赛事乙", "2025-02-01", 4, 2, 2, "DOUBLES", 3, 21),
            ],
        )
        conn.commit()
        old_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(tournaments)")
        }
        assert "owner_user_id" not in old_columns
        assert {"format_code", "rule_config", "rule_version"}.isdisjoint(old_columns)
    finally:
        conn.close()

    db_module.init_db()
    conn = db_module.connect()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
        assert {
            "owner_user_id",
            "format_code",
            "rule_config",
            "rule_version",
            "registration_enabled",
        } <= columns
        assert conn.execute(
            "SELECT COUNT(*) FROM tournaments WHERE registration_enabled = 1"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 2
        rows = conn.execute(
            "SELECT name, date, event_type, games_to_win, points_to_win, "
            "format_code, rule_config, rule_version "
            "FROM tournaments ORDER BY id"
        ).fetchall()
        assert [tuple(row[:5]) for row in rows] == [
            ("历史赛事甲", "2025-01-01", "SINGLES", 2, 11),
            ("历史赛事乙", "2025-02-01", "DOUBLES", 3, 21),
        ]
        assert [tuple(row[5:]) for row in rows] == [(None, None, None), (None, None, None)]
        assert [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ] == [1, 2, 3, 4, 5]
        assert conn.execute(
            "SELECT bootstrap_completed FROM system_state WHERE id = 1"
        ).fetchone()[0] == 0
        assert {
            row[1] for row in conn.execute("PRAGMA table_info(users)")
        } >= {"phone", "note"}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        first = repo.get_tournament(conn, 1)
        assert first is not None
        assert first["rule_config"] == {}
        assert first["format_code"] is None
        assert first["rule_version"] is None
    finally:
        conn.close()
