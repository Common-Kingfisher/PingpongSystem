"""D2 A2.1：版本化迁移框架与旧库升级。"""

from __future__ import annotations

import sqlite3

from app import db as db_module


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
        assert {"users", "user_sessions", "tournament_admins", "schema_migrations"} <= _table_names(conn)
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions == [1, 2]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
        assert "owner_user_id" in columns
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "repeat.db"))

    db_module.init_db()
    db_module.init_db()
    conn = db_module.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_legacy_database_upgrade_preserves_existing_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "legacy.db"))

    conn = db_module.connect()
    try:
        conn.executescript(db_module.TOURNAMENTS_TABLE_SQL)
        conn.executemany(
            "INSERT INTO tournaments "
            "(name, date, table_count, group_count, qualify_per_group) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("历史赛事甲", "2025-01-01", 2, 1, 1),
                ("历史赛事乙", "2025-02-01", 4, 2, 2),
            ],
        )
        conn.commit()
        assert "owner_user_id" not in {
            row[1] for row in conn.execute("PRAGMA table_info(tournaments)")
        }
    finally:
        conn.close()

    db_module.init_db()
    conn = db_module.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 2
        assert [row[0] for row in conn.execute("SELECT name FROM tournaments ORDER BY id")] == [
            "历史赛事甲",
            "历史赛事乙",
        ]
        assert "owner_user_id" in {
            row[1] for row in conn.execute("PRAGMA table_info(tournaments)")
        }
        assert [row[0] for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
