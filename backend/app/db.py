"""SQLite 连接与建表。

- 数据库文件：默认 backend/data/demo.db，可用环境变量 DEMO_DB_PATH 覆盖（测试用）。
- 每个请求独立连接；连接上强制 PRAGMA foreign_keys = ON。
- 状态字段用 CHECK 约束兜底枚举取值；比分用 CHECK 保证非负。
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "demo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    table_count INTEGER NOT NULL CHECK (table_count BETWEEN 4 AND 8),
    group_count INTEGER NOT NULL CHECK (group_count BETWEEN 1 AND 8),
    qualify_per_group INTEGER NOT NULL CHECK (qualify_per_group >= 1),
    stage TEXT NOT NULL DEFAULT 'REGISTRATION'
        CHECK (stage IN ('REGISTRATION','GROUP_STAGE','KNOCKOUT','FINISHED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    UNIQUE (tournament_id, name)
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    college TEXT,
    group_id INTEGER REFERENCES groups(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'FREE'
        CHECK (status IN ('FREE','OCCUPIED'))
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('GROUP','KNOCKOUT')),
    group_id INTEGER REFERENCES groups(id),
    round INTEGER NOT NULL DEFAULT 1,
    match_index INTEGER,
    player_a_id INTEGER REFERENCES players(id),
    player_b_id INTEGER REFERENCES players(id),
    player_a_score INTEGER CHECK (player_a_score IS NULL OR player_a_score >= 0),
    player_b_score INTEGER CHECK (player_b_score IS NULL OR player_b_score >= 0),
    winner_id INTEGER REFERENCES players(id),
    table_id INTEGER REFERENCES tables(id),
    status TEXT NOT NULL DEFAULT 'WAITING'
        CHECK (status IN ('WAITING','PLAYING','FINISHED')),
    prev_match_a_id INTEGER REFERENCES matches(id),
    prev_match_b_id INTEGER REFERENCES matches(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_players_tournament ON players(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
"""


def _db_path() -> Path:
    override = os.environ.get("DEMO_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI 依赖：每请求一个连接，请求结束关闭。"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
