"""SQLite 连接与建表。

- 数据库文件：默认 backend/data/demo.db，可用环境变量 DEMO_DB_PATH 覆盖（测试用）。
- 每个请求独立连接；连接上强制 PRAGMA foreign_keys = ON。
- 状态字段用 CHECK 约束兜底枚举取值；比分用 CHECK 保证非负。
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "demo.db"

# tournaments 表单独提取为常量：TEAM 事件类型需要重建旧表（SQLite 不能直接改 CHECK），
# 重建时必须以同一份 DDL 为准，避免两处 schema 漂移。
TOURNAMENTS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    table_count INTEGER NOT NULL CHECK (table_count BETWEEN 1 AND 15),
    group_count INTEGER NOT NULL CHECK (group_count BETWEEN 1 AND 26),
    qualify_per_group INTEGER NOT NULL CHECK (qualify_per_group >= 1),
    event_type TEXT NOT NULL DEFAULT 'SINGLES' CHECK (event_type IN ('SINGLES','DOUBLES','TEAM')),
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
);"""

SCHEMA = f"""
{TOURNAMENTS_TABLE_SQL}

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
    called_at TEXT,
    started_at TEXT,
    finished_at TEXT,
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

CREATE TABLE IF NOT EXISTS score_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('RECORD','REVISE')),
    before_snapshot TEXT NOT NULL,
    after_snapshot TEXT NOT NULL,
    operator_name TEXT,
    change_reason TEXT,
    request_id TEXT,
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

-- 团体赛领域模型（A3）：TeamTie 表示"A 队 vs B 队"整场对抗，TeamRubber 表示其中的一盘。
-- 队伍本身复用 entries(entry_type='TEAM') + entry_members，不再建 teams/team_members 重复名单。
-- TeamRubber.match_id 只是为 A4 的 Match adapter 预留，A3 永远保持 NULL。
CREATE TABLE IF NOT EXISTS team_ties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'GROUP' CHECK (stage IN ('GROUP','KNOCKOUT')),
    group_id INTEGER REFERENCES groups(id),
    round INTEGER NOT NULL DEFAULT 1,
    match_index INTEGER,
    entry_a_id INTEGER NOT NULL REFERENCES entries(id),
    entry_b_id INTEGER NOT NULL REFERENCES entries(id),
    team_a_score INTEGER NOT NULL DEFAULT 0 CHECK (team_a_score >= 0),
    team_b_score INTEGER NOT NULL DEFAULT 0 CHECK (team_b_score >= 0),
    winner_entry_id INTEGER REFERENCES entries(id),
    status TEXT NOT NULL DEFAULT 'WAITING' CHECK (status IN ('WAITING','PLAYING','FINISHED')),
    format_code TEXT,
    format_version INTEGER,
    format_snapshot TEXT,
    called_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS team_rubbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_tie_id INTEGER NOT NULL REFERENCES team_ties(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    rubber_type TEXT NOT NULL CHECK (rubber_type IN ('SINGLES','DOUBLES')),
    home_slots_json TEXT NOT NULL,
    away_slots_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','READY','PLAYING','FINISHED','SKIPPED')),
    match_id INTEGER REFERENCES matches(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (team_tie_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_players_tournament ON players(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_entries_tournament ON entries(tournament_id);
CREATE INDEX IF NOT EXISTS idx_entry_members_player ON entry_members(player_id);
CREATE INDEX IF NOT EXISTS idx_match_games_match ON match_games(match_id);
CREATE INDEX IF NOT EXISTS idx_score_requests_match ON score_requests(match_id);
CREATE INDEX IF NOT EXISTS idx_score_audits_match ON score_audits(match_id, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_score_audits_request
    ON score_audits(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_qualification_decisions_group ON qualification_decisions(group_id, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_qualification_decision_active
    ON qualification_decisions(group_id) WHERE invalidated_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_team_ties_tournament ON team_ties(tournament_id, id);
CREATE INDEX IF NOT EXISTS idx_team_rubbers_tie ON team_rubbers(team_tie_id, sequence);
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


def _upgrade_tournament_event_type(conn: sqlite3.Connection) -> None:
    """把旧库 tournaments.event_type 的 CHECK 升级为支持 TEAM。

    SQLite 不能直接修改 CHECK 约束，因此只能重建 tournaments 表：
      - 检测 sqlite_master 中的建表 SQL，已包含 'TEAM' 时直接跳过；
      - 重建期间关闭外键并开启 legacy_alter_table，使子表（players/entries/matches/...）
        的 `REFERENCES tournaments(id)` 保持指向同名新表，而不会被改写成旧表名；
      - 逐列动态拷贝新旧表共有列，保证不丢字段、不换 id、不重建赛事；
      - 结束后恢复 PRAGMA，调用方可再用 `PRAGMA foreign_key_check` 复核。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tournaments'"
    ).fetchone()
    table_sql = (row[0] or "") if row else ""
    if "event_type" not in table_sql or "'TEAM'" in table_sql:
        return  # 新库或已迁移过的库：什么都不做

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE tournaments RENAME TO tournaments_legacy_event_type")
        conn.executescript(TOURNAMENTS_TABLE_SQL)
        legacy_columns = [
            r[1] for r in conn.execute("PRAGMA table_info(tournaments_legacy_event_type)")
        ]
        new_columns = {r[1] for r in conn.execute("PRAGMA table_info(tournaments)")}
        shared = [c for c in legacy_columns if c in new_columns]
        column_list = ", ".join(shared)
        conn.execute(
            f"INSERT INTO tournaments ({column_list}) "
            f"SELECT {column_list} FROM tournaments_legacy_event_type"
        )
        conn.execute("DROP TABLE tournaments_legacy_event_type")
        conn.commit()
    finally:
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
            # A2 比赛时间基础：UTC SQLite 时间戳（datetime('now')，'YYYY-MM-DD HH:MM:SS'）。
            ("called_at", "TEXT"),
            ("started_at", "TEXT"),
            ("finished_at", "TEXT"),
        ):
            _add_column_if_missing(conn, "matches", column, ddl)
        # TEAM 事件类型：旧库需要重建 tournaments 表（SQLite 无法直接修改 CHECK）
        _upgrade_tournament_event_type(conn)
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
