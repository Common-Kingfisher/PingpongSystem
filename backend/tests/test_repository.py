"""repository 层测试：CRUD 往返、外键、CHECK 约束。"""

import sqlite3

import pytest

from app import repository as repo
from app.models import TableStatus, TournamentStage


def _make_tournament(conn, name="测试赛事", table_count=6, group_count=4, qualify_per_group=2):
    return repo.create_tournament(
        conn, name, "2025-06-01", table_count, group_count, qualify_per_group
    )


# ---------------------------------------------------------------- tournaments

def test_create_and_get_tournament(conn):
    t = _make_tournament(conn)
    conn.commit()
    assert t["id"] > 0
    assert t["name"] == "测试赛事"
    assert t["date"] == "2025-06-01"
    assert t["table_count"] == 6
    assert t["group_count"] == 4
    assert t["qualify_per_group"] == 2
    assert t["stage"] == TournamentStage.REGISTRATION.value

    loaded = repo.get_tournament(conn, t["id"])
    assert loaded == t


def test_list_tournaments_newest_first(conn):
    _make_tournament(conn, name="第一场")
    _make_tournament(conn, name="第二场")
    names = [t["name"] for t in repo.list_tournaments(conn)]
    assert names == ["第二场", "第一场"]


def test_get_missing_tournament_returns_none(conn):
    assert repo.get_tournament(conn, 999) is None


def test_tournament_check_table_count_range(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _make_tournament(conn, table_count=16)  # 超过 15 被 CHECK 拒绝


def test_tournament_stage_update(conn):
    t = _make_tournament(conn)
    repo.update_tournament_stage(conn, t["id"], TournamentStage.GROUP_STAGE.value)
    conn.commit()
    assert repo.get_tournament(conn, t["id"])["stage"] == "GROUP_STAGE"


# ------------------------------------------------------------------ tables

def test_create_tables_for_tournament(conn):
    t = _make_tournament(conn, table_count=6)
    tables = repo.create_tables_for_tournament(conn, t["id"], 6)
    conn.commit()
    assert len(tables) == 6
    assert [tb["name"] for tb in tables] == ["1号台", "2号台", "3号台", "4号台", "5号台", "6号台"]
    assert all(tb["status"] == TableStatus.FREE.value for tb in tables)


def test_table_status_update(conn):
    t = _make_tournament(conn, table_count=6)
    tables = repo.create_tables_for_tournament(conn, t["id"], 6)
    conn.commit()
    repo.update_table_status(conn, tables[0]["id"], TableStatus.OCCUPIED.value)
    conn.commit()
    assert repo.get_table(conn, tables[0]["id"])["status"] == "OCCUPIED"


# ------------------------------------------------------------------ players

def test_player_crud_roundtrip(conn):
    t = _make_tournament(conn)
    p = repo.add_player(conn, t["id"], "张三", "计算机学院")
    conn.commit()
    assert p["name"] == "张三"
    assert p["college"] == "计算机学院"
    assert p["group_id"] is None

    updated = repo.update_player(conn, p["id"], "张三丰", None)
    conn.commit()
    assert updated["name"] == "张三丰"
    # college 传 None 表示不修改
    assert updated["college"] == "计算机学院"

    cleared = repo.update_player(conn, p["id"], None, None)
    conn.commit()
    assert cleared["college"] == "计算机学院"  # 仍不修改，college 置空需显式传 "" 或未来支持

    listed = repo.list_players(conn, t["id"])
    assert len(listed) == 1

    assert repo.delete_player(conn, p["id"]) is True
    conn.commit()
    assert repo.list_players(conn, t["id"]) == []


def test_add_player_to_missing_tournament_fails_fk(conn):
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_player(conn, 999, "张三", None)


def test_delete_missing_player_returns_false(conn):
    assert repo.delete_player(conn, 999) is False
