"""A3：TEAM 项目的历史数据库迁移（tournaments.event_type 与 entries.entry_type 的 CHECK 升级）。

为什么需要这个文件：SQLite 不能直接修改 CHECK 约束，只能"重命名旧表 → 建新表 → 拷数据 → 删旧表"。
这类重建最容易悄悄坏掉四件事：
  1. 子表的 `REFERENCES <表>(id)` 被 SQLite 自动改写成旧表名，重建后指向一张已删除的表；
  2. 拷贝列时漏字段 / 换 id，把历史数据弄脏（例如 #14 的退赛审计列被吞掉）；
  3. 只升级 tournaments 而漏掉 entries：旧库上"能建 TEAM 赛事、一建队伍就 IntegrityError → 500"；
  4. 新建库 DDL 与迁移 DDL 漂移。

所以这里用真实的旧库文件（v0.2 DDL，两张表的 CHECK 都没有 TEAM）走一遍 init_db()，
并额外用"已经带了退赛审计列"的旧库验证列与值原样保留。
"""

import sqlite3

import pytest

from app import db as db_module
from app import repository as repo
from app.services import entries as entries_service
from app.services import teams as teams_service

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


def _legacy_entries_sql(*, with_withdrawals: bool) -> str:
    """旧版 entries：entry_type CHECK 只有 SINGLES/DOUBLES。

    with_withdrawals=True 模拟"#14 退赛已合入、但 TEAM 还没迁移"的中间态库，
    用于验证迁移不会吞掉退赛审计列。
    """
    withdrawal_columns = (
        "    withdrawn_at TEXT,\n"
        "    withdrawn_by TEXT,\n"
        "    withdrawal_reason TEXT,\n"
        if with_withdrawals
        else ""
    )
    return f"""
CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('SINGLES','DOUBLES')),
    display_name TEXT NOT NULL,
    rating_points INTEGER NOT NULL DEFAULT 0,
    group_id INTEGER REFERENCES groups(id),
    seed_no INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
{withdrawal_columns}    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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


def _write_legacy_db(path, *, with_withdrawals: bool = False) -> None:
    """构造一个 v0.2 旧库：1 个双打赛事 + 4 名选手 + 2 个参赛实体 + 1 场小组赛。

    with_withdrawals=True 时，22 号参赛位是带完整退赛审计值的已退赛队伍式参赛位
    （status=WITHDRAWN、withdrawn_at/withdrawn_by/withdrawal_reason 都有值）。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(LEGACY_TOURNAMENTS_SQL)
        conn.executescript(_legacy_entries_sql(with_withdrawals=with_withdrawals))
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
        if with_withdrawals:
            conn.execute(
                "INSERT INTO entries (id, tournament_id, entry_type, display_name, rating_points, "
                "group_id, status, withdrawn_at, withdrawn_by, withdrawal_reason) "
                "VALUES (22, 7, 'DOUBLES', '旧三 / 旧四', 2000, 3, 'WITHDRAWN', "
                "'2025-02-02 03:04:05', '主裁甲', '整队退赛')"
            )
        else:
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


def _legacy_table_names(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE '%legacy%'")]


def test_legacy_check_rejects_team_before_migration(tmp_path):
    """先证明前提：旧 CHECK 确实写不进 TEAM（否则这些迁移就是多余的）。

    tournaments 与 entries 两张表都要验，只验一张正是本次被指出的漏迁移。
    """
    path = tmp_path / "legacy_premise.db"
    _write_legacy_db(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        assert "'TEAM'" not in _table_sql(conn, "tournaments")
        assert "'TEAM'" not in _table_sql(conn, "entries")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tournaments (name, date, table_count, group_count, qualify_per_group, event_type) "
                "VALUES ('团体赛', '2025-02-01', 4, 2, 1, 'TEAM')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO entries (tournament_id, entry_type, display_name) "
                "VALUES (7, 'TEAM', '旧库队伍')"
            )
    finally:
        conn.close()


def test_init_db_migrates_legacy_event_type_and_keeps_data(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    _write_legacy_db(path)
    monkeypatch.setenv("DEMO_DB_PATH", str(path))

    db_module.init_db()
    conn = db_module.connect()
    try:
        # 1) 两张表的 CHECK 都升级到允许 TEAM
        assert "'TEAM'" in _table_sql(conn, "tournaments")
        assert "'TEAM'" in _table_sql(conn, "entries")
        # 2) 数据与 id 原样保留
        old = repo.get_tournament(conn, 7)
        assert old is not None
        assert (old["name"], old["event_type"], old["stage"]) == ("历史双打赛", "DOUBLES", "GROUP_STAGE")
        assert old["roster_confirmed"] == 1
        assert [p["name"] for p in repo.list_players(conn, 7)] == ["旧一", "旧二", "旧三", "旧四"]
        assert repo.get_entry(conn, 21)["display_name"] == "旧一 / 旧二"
        assert len(repo.list_entry_members(conn, 22)) == 2
        assert conn.execute("SELECT COUNT(*) FROM matches WHERE tournament_id = 7").fetchone()[0] == 1
        assert conn.execute(
            "SELECT entry_a_id, entry_b_id FROM matches WHERE id = 31"
        ).fetchone()[:] == (21, 22)

        # 3) 子表外键必须仍然指向同名新表，而不是被改写成迁移用的旧表名
        for child, target in (
            ("players", "tournaments"),
            ("entries", "tournaments"),
            ("matches", "tournaments"),
            ("groups", "tournaments"),
            ("tables", "tournaments"),
            ("entry_members", "entries"),
        ):
            assert f"REFERENCES {target}(id)" in _table_sql(conn, child), child
            assert "legacy" not in _table_sql(conn, child), child
        # 4) 外键自检必须为空（重建后没有任何悬空引用）
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # 5) 迁移后才允许 TEAM
        team = repo.create_tournament(conn, "新团体赛", "2025-03-01", 4, 2, 1, event_type="TEAM")
        conn.commit()
        assert team["event_type"] == "TEAM"

        # 6) 级联删除仍然有效（重建后外键动作没丢）
        assert repo.delete_tournament(conn, 7) is True
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM players WHERE tournament_id = 7").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM matches WHERE tournament_id = 7").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM entry_members").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_legacy_db_can_create_team_entry_through_service(tmp_path, monkeypatch):
    """真实升级链路验收（Reviewer 要求）：旧库 → init_db → TEAM 赛事 → 选手 → 建队伍成功。

    走 services 而不是直接 INSERT，正是为了覆盖"旧 entries CHECK 拒绝 TEAM → 500"这条真实路径。
    """
    path = tmp_path / "legacy_team_flow.db"
    _write_legacy_db(path, with_withdrawals=True)
    monkeypatch.setenv("DEMO_DB_PATH", str(path))

    db_module.init_db()
    conn = db_module.connect()
    try:
        tid = repo.create_tournament(
            conn, "旧库升级后的团体赛", "2025-04-01", 4, 2, 1, event_type="TEAM", operation_mode="DEMO"
        )["id"]
        players = [
            repo.add_player(conn, tid, f"新选手{index}", "计算机学院", 1000 + index)
            for index in range(1, 7)
        ]
        conn.commit()

        a = teams_service.create_team_entry(
            conn, tid, "A队", [p["id"] for p in players[:3]]
        )
        b = teams_service.create_team_entry(
            conn, tid, "B队", [p["id"] for p in players[3:]]
        )
        assert (a["entry_type"], b["entry_type"]) == ("TEAM", "TEAM")
        assert repo.get_entry(conn, a["id"])["members"][0]["player_id"] == players[0]["id"]

        tournament, entries = entries_service.confirm_roster(conn, tid)
        assert tournament["roster_confirmed"] == 1
        assert {e["id"] for e in entries} == {a["id"], b["id"]}

        # 新赛事里可以自由增删队伍，旧赛事的 TEAM 相关表也在（team_ties/team_rubbers 由 SCHEMA 建）
        teams_service.delete_team_entry(conn, tid, b["id"])
        assert repo.get_entry(conn, b["id"]) is None

        # 旧数据完全没被这次真实写入影响
        assert repo.get_tournament(conn, 7)["name"] == "历史双打赛"
        assert conn.execute("SELECT COUNT(*) FROM entries WHERE id IN (21, 22)").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert _legacy_table_names(conn) == []
    finally:
        conn.close()


def test_legacy_withdrawal_audit_columns_survive_migration(tmp_path, monkeypatch):
    """#14 已合入的旧库：升级 entry_type CHECK 不能吞掉退赛审计列与取值。"""
    path = tmp_path / "legacy_withdrawals.db"
    _write_legacy_db(path, with_withdrawals=True)
    monkeypatch.setenv("DEMO_DB_PATH", str(path))

    db_module.init_db()
    conn = db_module.connect()
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
        assert {"withdrawn_at", "withdrawn_by", "withdrawal_reason"} <= columns
        rows = {
            r["id"]: (r["status"], r["withdrawn_at"], r["withdrawn_by"], r["withdrawal_reason"])
            for r in conn.execute("SELECT * FROM entries ORDER BY id")
        }
        assert rows[21] == ("ACTIVE", None, None, None)
        assert rows[22] == ("WITHDRAWN", "2025-02-02 03:04:05", "主裁甲", "整队退赛")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_migration_is_idempotent_and_leaves_no_legacy_table(tmp_path, monkeypatch):
    path = tmp_path / "legacy_twice.db"
    _write_legacy_db(path, with_withdrawals=True)
    monkeypatch.setenv("DEMO_DB_PATH", str(path))

    db_module.init_db()
    conn = db_module.connect()
    first_tournaments = _table_sql(conn, "tournaments")
    first_entries = _table_sql(conn, "entries")
    conn.close()

    db_module.init_db()
    db_module.init_db()
    conn = db_module.connect()
    try:
        assert _table_sql(conn, "tournaments") == first_tournaments
        assert _table_sql(conn, "entries") == first_entries
        assert _legacy_table_names(conn) == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert repo.get_tournament(conn, 7)["name"] == "历史双打赛"
        assert conn.execute("SELECT withdrawn_by FROM entries WHERE id = 22").fetchone()[0] == "主裁甲"
    finally:
        conn.close()


def test_migrated_schema_is_identical_to_fresh_schema(tmp_path, monkeypatch):
    """新建库 DDL 与迁移后的 DDL 必须完全一致，避免两条路径再次漂移。"""
    migrated_path = tmp_path / "migrated.db"
    _write_legacy_db(migrated_path)
    monkeypatch.setenv("DEMO_DB_PATH", str(migrated_path))
    db_module.init_db()
    conn = db_module.connect()
    migrated = {t: _table_sql(conn, t) for t in ("tournaments", "entries")}
    conn.close()

    fresh_path = tmp_path / "fresh.db"
    monkeypatch.setenv("DEMO_DB_PATH", str(fresh_path))
    db_module.init_db()
    conn = db_module.connect()
    try:
        for table in ("tournaments", "entries"):
            assert _table_sql(conn, table) == migrated[table], table
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
        assert {"withdrawn_at", "withdrawn_by", "withdrawal_reason"} <= {
            r[1] for r in conn.execute("PRAGMA table_info(entries)")
        }
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"team_ties", "team_rubbers"} <= names
        # A3 只复用 entries/entry_members，不新建 teams / team_members 名单表
        assert "teams" not in names and "team_members" not in names
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"idx_team_ties_tournament", "idx_team_rubbers_tie"} <= indexes
        # rubbers 的盘序在同一个对抗内唯一
        assert "UNIQUE (team_tie_id, sequence)" in _table_sql(conn, "team_rubbers")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
