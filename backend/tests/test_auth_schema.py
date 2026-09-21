"""D2 A2.1：认证数据模型的约束与外键。"""

from __future__ import annotations

import sqlite3

import pytest


def _insert_user(conn, username: str) -> int:
    cursor = conn.execute(
        "INSERT INTO users (username, display_name, password_hash, system_role) "
        "VALUES (?, ?, ?, 'EVENT_ADMIN')",
        (username, username, "test-hash"),
    )
    return int(cursor.lastrowid)


def _insert_tournament(conn, name: str = "约束测试赛事") -> int:
    cursor = conn.execute(
        "INSERT INTO tournaments (name, date, table_count, group_count, qualify_per_group) "
        "VALUES (?, '2026-09-21', 1, 1, 1)",
        (name,),
    )
    return int(cursor.lastrowid)


def test_username_is_unique_case_insensitively(conn):
    _insert_user(conn, "Admin")
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_user(conn, "admin")


def test_tournament_admin_is_unique_per_user_and_tournament(conn):
    user_id = _insert_user(conn, "owner")
    tournament_id = _insert_tournament(conn)
    conn.execute(
        "INSERT INTO tournament_admins "
        "(tournament_id, user_id, role, created_by_user_id) VALUES (?, ?, 'OWNER', ?)",
        (tournament_id, user_id, user_id),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tournament_admins "
            "(tournament_id, user_id, role, created_by_user_id) VALUES (?, ?, 'ADMIN', ?)",
            (tournament_id, user_id, user_id),
        )


def test_auth_tables_and_owner_column_enforce_foreign_keys(conn):
    user_id = _insert_user(conn, "valid-user")
    tournament_id = _insert_tournament(conn)
    conn.execute(
        "INSERT INTO user_sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
        (user_id, "token-hash", "2099-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO tournament_admins (tournament_id, user_id, role) "
        "VALUES (?, ?, 'OWNER')",
        (tournament_id, user_id),
    )
    conn.execute(
        "UPDATE tournaments SET owner_user_id = ? WHERE id = ?",
        (user_id, tournament_id),
    )
    conn.commit()

    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (999999, "orphan-session", "2099-01-01T00:00:00+00:00"),
        )
    conn.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tournament_admins (tournament_id, user_id, role) "
            "VALUES (?, ?, 'ADMIN')",
            (999999, user_id),
        )
    conn.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE tournaments SET owner_user_id = ? WHERE id = ?",
            (999999, tournament_id),
        )
    conn.rollback()


def test_invalid_auth_roles_are_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, system_role) "
            "VALUES ('bad-role', 'bad-role', 'hash', 'SUPER_ADMIN')"
        )

    conn.rollback()
    user_id = _insert_user(conn, "role-user")
    tournament_id = _insert_tournament(conn, "角色约束赛事")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tournament_admins (tournament_id, user_id, role) "
            "VALUES (?, ?, 'SUPER_ADMIN')",
            (tournament_id, user_id),
        )
