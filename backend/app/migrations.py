"""SQLite 版本化迁移。

D2 只引入最小可用框架：迁移按整数版本顺序执行，每个版本独立事务，
成功后写入 ``schema_migrations``。已有数据库首次接入时先登记版本 1
作为当前 master 基线，再执行后续增量迁移。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable


VERSION_1_DESCRIPTION = "master baseline"
VERSION_2_DESCRIPTION = "auth_users_and_admins"
VERSION_3_DESCRIPTION = "bootstrap_state_and_user_profile"
VERSION_4_DESCRIPTION = "tournament_format_config"


MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


VERSION_2_SQL = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL COLLATE NOCASE UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        system_role TEXT NOT NULL
            CHECK (system_role IN ('SYSTEM_ADMIN','EVENT_ADMIN')),
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('OWNER','ADMIN','OPERATOR','VIEWER')),
        created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        revoked_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (user_id, tournament_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_sessions_user
        ON user_sessions(user_id, expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_sessions_active
        ON user_sessions(token_hash, revoked_at, expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tournament_admins_user
        ON tournament_admins(user_id, tournament_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tournament_admins_tournament
        ON tournament_admins(tournament_id, role)
    """,
)



VERSION_3_SQL = (
    """
    CREATE TABLE IF NOT EXISTS system_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        bootstrap_completed INTEGER NOT NULL DEFAULT 0
            CHECK (bootstrap_completed IN (0, 1)),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    INSERT OR IGNORE INTO system_state (id, bootstrap_completed)
    VALUES (1, 0)
    """,
)


def _migration_1(_: sqlite3.Connection) -> None:
    """master 基线不重复建表，只负责在旧库中登记版本。"""


def _add_owner_user_column(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
    if "owner_user_id" not in columns:
        conn.execute(
            "ALTER TABLE tournaments "
            "ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"
        )


def _migration_2(conn: sqlite3.Connection) -> None:
    for statement in VERSION_2_SQL:
        conn.execute(statement)
    _add_owner_user_column(conn)



def _add_user_column_if_missing(
    conn: sqlite3.Connection, column: str, ddl: str
) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if column not in columns:
        conn.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")


def _migration_3(conn: sqlite3.Connection) -> None:
    """持久化 bootstrap 状态，并补齐用户可选资料字段。"""
    for statement in VERSION_3_SQL:
        conn.execute(statement)
    _add_user_column_if_missing(conn, "phone", "TEXT")
    _add_user_column_if_missing(conn, "note", "TEXT")


def _migration_4(conn: sqlite3.Connection) -> None:
    """为锦标赛补齐赛制配置列；历史数据保持 NULL。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
    column_ddl = (
        (
            "format_code",
            "TEXT CHECK (format_code IS NULL OR format_code IN "
            "('ROUND_ROBIN','SINGLE_ELIMINATION','GROUP_KNOCKOUT'))",
        ),
        ("rule_config", "TEXT"),
        (
            "rule_version",
            "INTEGER CHECK (rule_version IS NULL OR rule_version >= 1)",
        ),
    )
    for column, ddl in column_ddl:
        if column not in columns:
            conn.execute(f"ALTER TABLE tournaments ADD COLUMN {column} {ddl}")


MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, VERSION_1_DESCRIPTION, _migration_1),
    (2, VERSION_2_DESCRIPTION, _migration_2),
    (3, VERSION_3_DESCRIPTION, _migration_3),
    (4, VERSION_4_DESCRIPTION, _migration_4),
)


def _current_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _record_version(conn: sqlite3.Connection, version: int, name: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
        (version, name),
    )


def apply_migrations(conn: sqlite3.Connection) -> tuple[int, ...]:
    """按版本顺序执行未应用迁移，返回本次实际执行的版本号。"""
    conn.execute(MIGRATION_TABLE_SQL)
    current = _current_version(conn)
    if current is None:
        # 旧库没有迁移表，但已经经过 init_db 的 master schema 初始化。
        conn.execute("BEGIN IMMEDIATE")
        try:
            _record_version(conn, 1, VERSION_1_DESCRIPTION)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        current = 1
    conn.commit()

    applied: list[int] = []
    for version, name, migration in MIGRATIONS:
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration(conn)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"迁移 {version} 后外键校验失败: {violations[:3]}")
            _record_version(conn, version, name)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(f"迁移版本 {version}（{name}）失败") from exc
        applied.append(version)
        current = version
    return tuple(applied)
