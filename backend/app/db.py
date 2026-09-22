"""SQLite 连接与建表。

- 数据库文件：默认 backend/data/demo.db，可用 PINGPONG_DB_PATH 覆盖；兼容旧变量 DEMO_DB_PATH（测试用）。
- 每个请求独立连接；连接上强制 PRAGMA foreign_keys = ON。
- 状态字段用 CHECK 约束兜底枚举取值；比分用 CHECK 保证非负。
"""

import os
import sqlite3
from pathlib import Path

from .migrations import apply_migrations

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
    format_code TEXT CHECK (format_code IS NULL OR format_code IN ('ROUND_ROBIN','SINGLE_ELIMINATION','GROUP_KNOCKOUT')),
    rule_config TEXT,
    rule_version INTEGER CHECK (rule_version IS NULL OR rule_version >= 1),
    stage TEXT NOT NULL DEFAULT 'REGISTRATION'
        CHECK (stage IN ('REGISTRATION','GROUP_STAGE','KNOCKOUT','FINISHED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""

# entries 表同样单独提取：TEAM 参赛实体需要重建旧表（SQLite 不能直接改 CHECK）。
# 这份 DDL 必须同时是"新建库"与"迁移"的唯一来源，否则两条路径会漂移
# （踩过的坑：只迁移 tournaments 的 event_type，旧库 entries.entry_type 的
#  CHECK 仍只有 SINGLES/DOUBLES，创建 TEAM 队伍会 IntegrityError → 500）。
ENTRIES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('SINGLES','DOUBLES','TEAM')),
    display_name TEXT NOT NULL,
    rating_points INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    group_id INTEGER REFERENCES groups(id),
    seed_no INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
    withdrawn_at TEXT,
    withdrawn_by TEXT,
    withdrawal_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""

# team_rubbers：A3 只落"骨架"（盘序 + 单打/双打 + 每边位置代号）；
# A4.1 追加"运行态"列：本盘实际参赛人（lineup binding）、盘比分、胜者与起止时间。
# 这些列不改变任何 CHECK（状态取值不变），因此旧库只需要 ADD COLUMN，不必重建表。
TEAM_RUBBER_RUNTIME_COLUMNS = (
    ("home_player_ids_json", "TEXT"),
    ("away_player_ids_json", "TEXT"),
    ("home_score", "INTEGER"),
    ("away_score", "INTEGER"),
    ("winner_entry_id", "INTEGER REFERENCES entries(id)"),
    ("started_at", "TEXT"),
    ("finished_at", "TEXT"),
)

TEAM_RUBBERS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS team_rubbers (
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
    home_player_ids_json TEXT,
    away_player_ids_json TEXT,
    home_score INTEGER,
    away_score INTEGER,
    winner_entry_id INTEGER REFERENCES entries(id),
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (team_tie_id, sequence)
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

{ENTRIES_TABLE_SQL}

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

-- 团体赛晋级确认（A6.3）：只记录"哪些队伍已被确认晋级"，是**人工/系统确认的结果**。
-- 排名事实永远从 team_ties / team_rubbers 现算（A6.2），这里**刻意不保存**
-- rank / 积分 / 排名快照，避免第二真相源；淘汰签只用"小组顺序 + 组内序号"。
CREATE TABLE IF NOT EXISTS team_qualifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    team_entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'QUALIFIED' CHECK (status IN ('QUALIFIED')),
    confirmed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tournament_id, team_entry_id)
);
CREATE INDEX IF NOT EXISTS idx_team_qualifications_tournament
    ON team_qualifications(tournament_id);

-- 团体赛领域模型（A3）：TeamTie 表示"A 队 vs B 队"整场对抗，TeamRubber 表示其中的一盘。
-- 队伍本身复用 entries(entry_type='TEAM') + entry_members，不再建 teams/team_members 重复名单。
-- TeamRubber.match_id 只是为以后的 Match adapter 预留，A4.1 仍然保持 NULL。
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

{TEAM_RUBBERS_TABLE_SQL}

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


def _rebuild_table_to_allow_team(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    new_table_sql: str,
    legacy_table: str,
) -> bool:
    """把"旧 CHECK 里没有 TEAM"的表按新版 DDL 重建（SQLite 无法直接修改 CHECK）。

    tournaments.event_type 与 entries.entry_type 共用这一套流程，确保两条迁移路径
    的安全模式完全一致，不会各自漂移：

      - 读 sqlite_master 的建表 SQL：没有该列（表还没建）或已包含 'TEAM' 时直接跳过
        （幂等：新建库、已迁移过的库都不做任何事）；
      - 重建期间 foreign_keys=OFF + legacy_alter_table=ON：既有子表的
        `REFERENCES <table>(id)` 不会被改写成旧表名，而是继续指向重建后的同名新表；
      - 只拷贝"旧表列 ∩ 新表列"（动态求交集，不写死旧列清单）：
        既兼容真正旧库（缺少后来新增的列），也兼容已经带了新列（例如退赛审计列）的库；
      - 不依赖"当前存在哪些子表"，因此旧库还没有 team_ties 之类的表也不影响；
      - 结束后恢复 PRAGMA，由调用方/测试用 `PRAGMA foreign_key_check` 复核。

    返回是否真的执行了重建。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    table_sql = (row[0] or "") if row else ""
    if column not in table_sql or "'TEAM'" in table_sql:
        return False  # 新库或已迁移过的库：什么都不做

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute(f"ALTER TABLE {table} RENAME TO {legacy_table}")
        conn.executescript(new_table_sql)
        legacy_columns = [r[1] for r in conn.execute(f"PRAGMA table_info({legacy_table})")]
        new_columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        shared = [c for c in legacy_columns if c in new_columns]
        column_list = ", ".join(shared)
        conn.execute(
            f"INSERT INTO {table} ({column_list}) SELECT {column_list} FROM {legacy_table}"
        )
        conn.execute(f"DROP TABLE {legacy_table}")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
    return True


def _upgrade_tournament_event_type(conn: sqlite3.Connection) -> None:
    """把旧库 tournaments.event_type 的 CHECK 升级为支持 TEAM。"""
    _rebuild_table_to_allow_team(
        conn, "tournaments", "event_type", TOURNAMENTS_TABLE_SQL, "tournaments_legacy_event_type"
    )


def _upgrade_entry_type_for_team(conn: sqlite3.Connection) -> None:
    """把旧库 entries.entry_type 的 CHECK 升级为支持 TEAM。

    为什么必须做：`CREATE TABLE IF NOT EXISTS entries` 不会修改已有表的 CHECK。
    只升级 tournaments 的话，旧库上"创建 TEAM 赛事成功、但 POST /teams 建队伍时
    被 entries 的旧 CHECK 拒绝"会变成 sqlite3.IntegrityError → 500。
    正确修法是真正升级约束，而不是用 try/except 把 IntegrityError 吞成 409。
    """
    _rebuild_table_to_allow_team(
        conn, "entries", "entry_type", ENTRIES_TABLE_SQL, "entries_legacy_entry_type"
    )



def _db_path() -> Path:
    override = os.environ.get("PINGPONG_DB_PATH") or os.environ.get("DEMO_DB_PATH")
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
        for column, ddl in (
            ("withdrawn_at", "TEXT"),
            ("withdrawn_by", "TEXT"),
            ("withdrawal_reason", "TEXT"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
        ):
            _add_column_if_missing(conn, "entries", column, ddl)
        # 保持旧库的可见顺序：没有显式排序值的历史 Entry 按原 id 排列。
        conn.execute("UPDATE entries SET sort_order = id WHERE sort_order = 0")
        # A4.1 团体赛 Runtime：team_rubbers 追加运行态列（lineup 绑定 / 盘比分 / 胜者 / 起止时间）。
        # 上面的 SCHEMA 已经保证该表存在（新建库直接带全部列，A3 旧库则缺这些列），
        # 因此这里只需 ADD COLUMN，不需要重建表，也不要求删除 demo.db。
        for column, ddl in TEAM_RUBBER_RUNTIME_COLUMNS:
            _add_column_if_missing(conn, "team_rubbers", column, ddl)
        # TEAM 项目：旧库的 tournaments.event_type 与 entries.entry_type 都只有
        # SINGLES/DOUBLES，SQLite 不能直接修改 CHECK，必须重建这两张表。
        # 先重建 tournaments（entries 引用它），再重建 entries（entry_members/matches/team_ties 引用它）；
        # 退赛审计列（withdrawn_*）在前面的 _add_column_if_missing 里已就位，重建时按共有列原样拷贝。
        _upgrade_tournament_event_type(conn)
        _upgrade_entry_type_for_team(conn)
        # New tables are created after legacy tables have been upgraded so their FKs target the final table.
        conn.executescript(SCHEMA)
        # D2：业务表基线完成后执行版本化增量迁移。
        apply_migrations(conn)
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
