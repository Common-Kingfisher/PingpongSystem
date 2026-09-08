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
    table_count INTEGER NOT NULL CHECK (table_count BETWEEN 1 AND 15),
    group_count INTEGER NOT NULL CHECK (group_count BETWEEN 1 AND 26),
    qualify_per_group INTEGER NOT NULL CHECK (qualify_per_group >= 1),
    event_type TEXT NOT NULL DEFAULT 'SINGLES' CHECK (event_type IN ('SINGLES','DOUBLES')),
    bronze_mode TEXT NOT NULL DEFAULT 'JOINT_BRONZE' CHECK (bronze_mode IN ('BRONZE_MATCH','JOINT_BRONZE')),
    placement_mode TEXT NOT NULL DEFAULT 'OFF' CHECK (placement_mode IN ('OFF','COMPLETE','TIERED')),
    games_to_win INTEGER NOT NULL DEFAULT 2 CHECK (games_to_win BETWEEN 1 AND 4),
    points_to_win INTEGER NOT NULL DEFAULT 11 CHECK (points_to_win >= 1),
    roster_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (roster_confirmed IN (0,1)),
    confirmed_at TEXT,
    operation_mode TEXT NOT NULL DEFAULT 'LIVE' CHECK (operation_mode IN ('LIVE','DEMO')),
    stage TEXT NOT NULL DEFAULT 'REGISTRATION'
        CHECK (stage IN ('REGISTRATION','GROUP_STAGE','KNOCKOUT','FINISHED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    qualify_count INTEGER,
    UNIQUE (tournament_id, name)
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    college TEXT,
    group_id INTEGER REFERENCES groups(id),
    seed_no INTEGER,
    rating_points INTEGER NOT NULL DEFAULT 1000 CHECK (rating_points >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('SINGLES','DOUBLES','TEAM')),
    display_name TEXT NOT NULL,
    rating_points INTEGER NOT NULL DEFAULT 0,
    group_id INTEGER REFERENCES groups(id),
    seed_no INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entry_members (
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    member_order INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (entry_id, player_id),
    UNIQUE (player_id)
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
    prev_match_a_outcome TEXT NOT NULL DEFAULT 'WINNER' CHECK (prev_match_a_outcome IN ('WINNER','LOSER')),
    prev_match_b_outcome TEXT NOT NULL DEFAULT 'WINNER' CHECK (prev_match_b_outcome IN ('WINNER','LOSER')),
    entry_a_id INTEGER REFERENCES entries(id),
    entry_b_id INTEGER REFERENCES entries(id),
    winner_entry_id INTEGER REFERENCES entries(id),
    result_type TEXT CHECK (result_type IS NULL OR result_type IN ('NORMAL','FORFEIT','WALKOVER','NO_SHOW','DISQUALIFIED')),
    forfeit_entry_id INTEGER REFERENCES entries(id),
    result_note TEXT,
    bracket TEXT NOT NULL DEFAULT 'GROUP' CHECK (bracket IN ('GROUP','MAIN','PLACEMENT')),
    placement_min INTEGER,
    placement_max INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS match_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    game_no INTEGER NOT NULL,
    side_a_score INTEGER NOT NULL CHECK (side_a_score >= 0),
    side_b_score INTEGER NOT NULL CHECK (side_b_score >= 0),
    winner_entry_id INTEGER REFERENCES entries(id),
    UNIQUE (match_id, game_no)
);

CREATE TABLE IF NOT EXISTS score_requests (
    request_id TEXT PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('RECORD','REVISE')),
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS qualification_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    selected_entry_ids TEXT NOT NULL,
    ranking_snapshot TEXT NOT NULL,
    reason TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    invalidated_at TEXT,
    invalidation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_players_tournament ON players(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_entries_tournament ON entries(tournament_id);
CREATE INDEX IF NOT EXISTS idx_entry_members_player ON entry_members(player_id);
CREATE INDEX IF NOT EXISTS idx_match_games_match ON match_games(match_id);
CREATE INDEX IF NOT EXISTS idx_score_requests_match ON score_requests(match_id);
CREATE INDEX IF NOT EXISTS idx_qualification_decisions_group ON qualification_decisions(group_id, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_qualification_decision_active
    ON qualification_decisions(group_id) WHERE invalidated_at IS NULL;
"""


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _upgrade_tournament_limits(conn: sqlite3.Connection) -> None:
    """Rebuild only the legacy tournaments table whose CHECK still caps tables at 8."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tournaments'"
    ).fetchone()
    if not row or "BETWEEN 4 AND 8" not in (row[0] or ""):
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("ALTER TABLE tournaments RENAME TO tournaments_legacy_v01")
    conn.execute(
        """CREATE TABLE tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            table_count INTEGER NOT NULL CHECK (table_count BETWEEN 1 AND 15),
            group_count INTEGER NOT NULL CHECK (group_count BETWEEN 1 AND 26),
            qualify_per_group INTEGER NOT NULL CHECK (qualify_per_group >= 1),
            stage TEXT NOT NULL DEFAULT 'REGISTRATION'
                CHECK (stage IN ('REGISTRATION','GROUP_STAGE','KNOCKOUT','FINISHED')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute(
        "INSERT INTO tournaments (id,name,date,table_count,group_count,qualify_per_group,stage,created_at) "
        "SELECT id,name,date,table_count,group_count,qualify_per_group,stage,created_at FROM tournaments_legacy_v01"
    )
    conn.execute("DROP TABLE tournaments_legacy_v01")
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")


def _db_path() -> Path:
    override = os.environ.get("DEMO_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    # check_same_thread=False：FastAPI 会把"依赖（在此创建连接）"与"端点函数（在此使用连接）"
    # 调度到线程池的不同线程执行。每个请求持有独立连接、且仅在单个请求生命周期内串行使用，
    # 不存在跨请求共享，因此关闭同线程检查。否则并发请求会间歇性抛出
    # sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _upgrade_tournament_limits(conn)
        # 轻量迁移：为旧库补充 seed_no 列（CREATE TABLE IF NOT EXISTS 不会改已有表）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(players)")]
        if "seed_no" not in cols:
            conn.execute("ALTER TABLE players ADD COLUMN seed_no INTEGER")
        _add_column_if_missing(conn, "players", "rating_points", "INTEGER NOT NULL DEFAULT 1000")
        _add_column_if_missing(conn, "groups", "qualify_count", "INTEGER")
        for column, ddl in (
            ("event_type", "TEXT NOT NULL DEFAULT 'SINGLES'"),
            ("bronze_mode", "TEXT NOT NULL DEFAULT 'JOINT_BRONZE'"),
            ("placement_mode", "TEXT NOT NULL DEFAULT 'OFF'"),
            ("games_to_win", "INTEGER NOT NULL DEFAULT 2"),
            ("points_to_win", "INTEGER NOT NULL DEFAULT 11"),
            ("roster_confirmed", "INTEGER NOT NULL DEFAULT 0"),
            ("confirmed_at", "TEXT"),
            ("operation_mode", "TEXT NOT NULL DEFAULT 'LIVE' CHECK (operation_mode IN ('LIVE','DEMO'))"),
        ):
            _add_column_if_missing(conn, "tournaments", column, ddl)
        for column, ddl in (
            ("entry_a_id", "INTEGER REFERENCES entries(id)"),
            ("entry_b_id", "INTEGER REFERENCES entries(id)"),
            ("winner_entry_id", "INTEGER REFERENCES entries(id)"),
            ("result_type", "TEXT"),
            ("forfeit_entry_id", "INTEGER REFERENCES entries(id)"),
            ("result_note", "TEXT"),
            ("bracket", "TEXT NOT NULL DEFAULT 'GROUP'"),
            ("placement_min", "INTEGER"),
            ("placement_max", "INTEGER"),
            ("prev_match_a_outcome", "TEXT NOT NULL DEFAULT 'WINNER'"),
            ("prev_match_b_outcome", "TEXT NOT NULL DEFAULT 'WINNER'"),
        ):
            _add_column_if_missing(conn, "matches", column, ddl)
        # New tables are created after legacy tables have been upgraded so their FKs target the final table.
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI 依赖：每请求一个连接，请求结束回滚未提交事务并关闭。"""
    conn = connect()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
