"""A3：TEAM 事件类型的旧库迁移（tournaments.event_type 的 CHECK 升级）。

为什么需要这个文件：SQLite 不能直接修改 CHECK 约束，只能"重命名旧表 → 建新表 → 拷数据 → 删旧表"。
这类重建最容易悄悄坏掉两件事：
  1. 子表（players/entries/matches/...）的 `REFERENCES tournaments(id)` 被 SQLite 自动改写成
     旧表名，导致重建后外键指向一张已经被删掉的表；
  2. 拷贝列时漏字段 / 换 id，把历史赛事数据弄脏。
所以这里用真实的旧库文件（v0.2 的 DDL，CHECK 里没有 TEAM）走一遍 init_db()，
逐条验证：TEAM 可写入、数据与 id 不变、外键指向仍是 tournaments、foreign_key_check 为空、重复执行幂等。
"""

import sqlite3

from app import db as db_module
from app import repository as repo

# v0.2 的 tournaments：event_type 的 CHECK 只有 SINGLES / DOUBLES（这正是要迁移的对象）
LEGACY_TOURNAMENTS_SQL = """
CREATE TABLE tournaments (
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
"""

LEGACY_CHILD_SQL = """
CREATE TABLE groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    qualify_count INTEGER,
    UNIQUE (tournament_id, name)
);
CREATE TABLE players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    college TEXT,
    group_id INTEGER REFERENCES groups(id),
    seed_no INTEGER,
    rating_points INTEGER NOT NULL DEFAULT 1000 CHECK (rating_points >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('SINGLES','DOUBLES')),
    display_name TEXT NOT NULL,
    rating_points INTEGER NOT NULL DEFAULT 0,
    group_id INTEGER REFERENCES groups(id),
    seed_no INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE entry_members (
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    member_order INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (entry_id, player_id),
    UNIQUE (player_id)
);
CREATE TABLE tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'FREE' CHECK (status IN ('FREE','OCCUPIED'))
);
CREATE TABLE matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('GROUP','KNOCKOUT')),
    group_id INTEGER REFERENCES groups(id),
    round INTEGER NOT NULL DEFAULT 1,
    match_index INTEGER,
    player_a_id INTEGER REFERENCES players(id),
    player_b_id INTEGER REFERENCES players(id),
    player_a_score INTEGER,
    player_b_score INTEGER,
    winner_id INTEGER REFERENCES players(id),
    table_id INTEGER REFERENCES tables(id),
    status TEXT NOT NULL DEFAULT 'WAITING' CHECK (status IN ('WAITING','PLAYING','FINISHED')),
    entry_a_id INTEGER REFERENCES entries(id),
    entry_b_id INTEGER REFERENCES entries(id),
    winner_entry_id INTEGER REFERENCES entries(id),
    bracket TEXT NOT NULL DEFAULT 'GROUP' CHECK (bracket IN ('GROUP','MAIN','PLACEMENT'))
);
"""


def _write_legacy_db(path) -> None:
    """构造一个 v0.2 旧库：1 个双打赛事 + 4 名选手 + 2 个参赛实体 + 1 场小组赛。"""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(LEGACY_TOURNAMENTS_SQL)
        conn.executescript(LEGACY_CHILD_SQL)
        conn.execute(
            "INSERT INTO tournaments (id, name, date, table_count, group_count, qualify_per_group, "
            "event_type, stage, roster_confirmed) VALUES (7, '历史双打赛', '2025-01-01', 4, 2, 1, 'DOUBLES', 'GROUP_STAGE', 1)"
        )
        conn.execute("INSERT INTO groups (id, tournament_id, name, sort_order) VALUES (3, 7, 'A组', 0)")
        for index, name in enumerate(("旧一", "旧二", "旧三", "旧四"), start=1):
            conn.execute(
                "INSERT INTO players (id, tournament_id, name, group_id, rating_points) "
                "VALUES (?, 7, ?, 3, ?)",
                (10 + index, name, 1000 + index),
            )
        conn.execute(
            "INSERT INTO entries (id, tournament_id, entry_type, display_name, rating_points, group_id) "
            "VALUES (21, 7, 'DOUBLES', '旧一 / 旧二', 2000, 3)"
        )
        conn.execute(
            "INSERT INTO entries (id, tournament_id, entry_type, display_name, rating_points, group_id) "
            "VALUES (22, 7, 'DOUBLES', '旧三 / 旧四', 2000, 3)"
        )
        conn.execute("INSERT INTO entry_members (entry_id, player_id, member_order) VALUES (21, 11, 1)")
        conn.execute("INSERT INTO entry_members (entry_id, player_id, member_order) VALUES (21, 12, 2)")
        conn.execute("INSERT INTO entry_members (entry_id, player_id, member_order) VALUES (22, 13, 1)")
        conn.execute("INSERT INTO entry_members (entry_id, player_id, member_order) VALUES (22, 14, 2)")
        conn.execute("INSERT INTO tables (id, tournament_id, name) VALUES (5, 7, '1号台')")
        conn.execute(
            "INSERT INTO matches (id, tournament_id, stage, group_id, round, entry_a_id, entry_b_id, "
            "player_a_id, player_b_id, table_id, status) "
            "VALUES (31, 7, 'GROUP', 3, 1, 21, 22, 11, 13, 5, 'WAITING')"
        )
        conn.commit()
    finally:
        conn.close()


def _table_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return (row[0] or "") if row else ""


def test_legacy_check_rejects_team_before_migration(tmp_path):
    """先证明前提：旧 CHECK 确实写不进 TEAM（否则这个迁移就是多余的）。"""
    path = tmp_path / "legacy_premise.db"
    _write_legacy_db(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        assert "'TEAM'" not in _table_sql(conn, "tournaments")
        try:
            conn.execute(
                "INSERT INTO tournaments (name, date, table_count, group_count, qualify_per_group, event_type) "
                "VALUES ('团体赛', '2025-02-01', 4, 2, 1, 'TEAM')"
            )
            raise AssertionError("旧 CHECK 竟然允许 TEAM")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_init_db_migrates_legacy_event_type_and_keeps_data(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    _write_legacy_db(path)
    monkeypatch.setenv("DEMO_DB_PATH", str(path))

    db_module.init_db()
    conn = db_module.connect()
    try:
        table_sql = _table_sql(conn, "tournaments")
        assert "'TEAM'" in table_sql
        # 1) 数据与 id 原样保留
        old = repo.get_tournament(conn, 7)
        assert old is not None
        assert (old["name"], old["event_type"], old["stage"]) == ("历史双打赛", "DOUBLES", "GROUP_STAGE")
        assert old["roster_confirmed"] == 1
        assert [p["name"] for p in repo.list_players(conn, 7)] == ["旧一", "旧二", "旧三", "旧四"]
        assert repo.get_entry(conn, 21)["display_name"] == "旧一 / 旧二"
        assert len(repo.list_entry_members(conn, 22)) == 2
        assert conn.execute("SELECT COUNT(*) FROM matches WHERE tournament_id = 7").fetchone()[0] == 1

        # 2) 子表外键必须仍然指向 tournaments，而不是被改写成迁移用的旧表名
        for child in ("players", "entries", "matches", "groups", "tables"):
            assert "REFERENCES tournaments(id)" in _table_sql(conn, child), child
            assert "legacy" not in _table_sql(conn, child), child
        # 3) 外键自检必须为空（重建后没有任何悬空引用）
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # 4) 迁移后才允许 TEAM
        team = repo.create_tournament(conn, "新团体赛", "2025-03-01", 4, 2, 1, event_type="TEAM")
        conn.commit()
        assert team["event_type"] == "TEAM"

        # 5) 级联删除仍然有效（重建后外键动作没丢）
        assert repo.delete_tournament(conn, 7) is True
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM players WHERE tournament_id = 7").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM matches WHERE tournament_id = 7").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_migration_is_idempotent_and_leaves_no_legacy_table(tmp_path, monkeypatch):
    path = tmp_path / "legacy_twice.db"
    _write_legacy_db(path)
    monkeypatch.setenv("DEMO_DB_PATH", str(path))

    db_module.init_db()
    conn = db_module.connect()
    first_sql = _table_sql(conn, "tournaments")
    conn.close()

    db_module.init_db()
    db_module.init_db()
    conn = db_module.connect()
    try:
        assert _table_sql(conn, "tournaments") == first_sql
        leftovers = conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%legacy%'"
        ).fetchall()
        assert leftovers == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert repo.get_tournament(conn, 7)["name"] == "历史双打赛"
    finally:
        conn.close()


def test_fresh_db_has_team_event_and_team_tables(tmp_path, monkeypatch):
    """新库必须有 TEAM、team_ties、team_rubbers 与索引，且外键自检为空。"""
    path = tmp_path / "fresh.db"
    monkeypatch.setenv("DEMO_DB_PATH", str(path))
    db_module.init_db()
    conn = db_module.connect()
    try:
        assert "'TEAM'" in _table_sql(conn, "tournaments")
        assert "IN ('SINGLES','DOUBLES','TEAM')" in _table_sql(conn, "entries")
        assert "IN ('SINGLES','DOUBLES')" in _table_sql(conn, "team_rubbers")
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"team_ties", "team_rubbers"} <= names
        # A3 只复用 entries/entry_members，不新建 teams / team_members 名单表
        assert "teams" not in names and "team_members" not in names
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"idx_team_ties_tournament", "idx_team_rubbers_tie"} <= indexes
        # rubbers 的盘序在同一个对抗内唯一
        tie_uniques = _table_sql(conn, "team_rubbers")
        assert "UNIQUE (team_tie_id, sequence)" in tie_uniques
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
