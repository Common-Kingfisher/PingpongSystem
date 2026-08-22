"""分组服务/API 测试：均衡分配、不重不漏、重分组覆盖、解除分组、删除守卫、阶段守卫。"""

import random
from collections import Counter

import pytest

from app import repository as repo
from app.services import groups as groups_service


def _create_tournament(client, n_players=24):
    resp = client.post(
        "/api/tournaments",
        json={
            "name": "分组测试赛",
            "date": "2025-06-01",
            "table_count": 6,
            "group_count": 4,
            "qualify_per_group": 2,
        },
    )
    tid = resp.json()["id"]
    for i in range(1, n_players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    return tid


# ------------------------------------------------------------ domain/service

def test_auto_group_service_persists(conn):
    t = repo.create_tournament(conn, "T", "2025-06-01", 6, 4, 2)
    for i in range(1, 25):
        repo.add_player(conn, t["id"], f"选手{i:02d}", None)

    result = groups_service.auto_group_tournament(conn, t["id"], random.Random(5))
    assert len(result) == 4
    assert sorted(len(g["players"]) for g in result) == [6, 6, 6, 6]
    assert [g["name"] for g in result] == ["A组", "B组", "C组", "D组"]

    # 数据库中已落库：每人有且仅有一个组，每组 6 人
    players = repo.list_players(conn, t["id"])
    group_ids = [p["group_id"] for p in players]
    assert all(gid is not None for gid in group_ids)
    assert sorted(Counter(group_ids).values()) == [6, 6, 6, 6]


def test_auto_group_rejected_when_not_registration(conn):
    t = repo.create_tournament(conn, "T", "2025-06-01", 6, 4, 2)
    repo.update_tournament_stage(conn, t["id"], "GROUP_STAGE")
    with pytest.raises(groups_service.TournamentStageError):
        groups_service.auto_group_tournament(conn, t["id"])


def test_ungroup_clears_groups(conn):
    t = repo.create_tournament(conn, "T", "2025-06-01", 6, 4, 2)
    for i in range(1, 9):
        repo.add_player(conn, t["id"], f"选手{i}", None)
    groups_service.auto_group_tournament(conn, t["id"])
    groups_service.ungroup_tournament(conn, t["id"])
    assert repo.list_groups(conn, t["id"]) == []
    assert all(p["group_id"] is None for p in repo.list_players(conn, t["id"]))


# ---------------------------------------------------------------------- API

def test_auto_group_api_distributes_evenly(client):
    tid = _create_tournament(client)
    resp = client.post(f"/api/tournaments/{tid}/auto-group")
    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert [g["name"] for g in groups] == ["A组", "B组", "C组", "D组"]
    assert sorted(len(g["players"]) for g in groups) == [6, 6, 6, 6]
    # 不重不漏
    all_ids = [p["id"] for g in groups for p in g["players"]]
    assert len(all_ids) == 24
    assert len(set(all_ids)) == 24


def test_get_groups_before_grouping_is_empty(client):
    tid = _create_tournament(client, n_players=3)
    resp = client.get(f"/api/tournaments/{tid}/groups")
    assert resp.status_code == 200
    assert resp.json() == {"groups": []}


def test_regroup_overwrites_old_groups(client):
    tid = _create_tournament(client)
    client.post(f"/api/tournaments/{tid}/auto-group")
    resp = client.post(f"/api/tournaments/{tid}/auto-group")
    assert resp.status_code == 200
    all_ids = [p["id"] for g in resp.json()["groups"] for p in g["players"]]
    assert len(set(all_ids)) == 24


def test_ungroup_api(client):
    tid = _create_tournament(client, n_players=5)
    client.post(f"/api/tournaments/{tid}/auto-group")
    resp = client.post(f"/api/tournaments/{tid}/ungroup")
    assert resp.status_code == 204
    assert client.get(f"/api/tournaments/{tid}/groups").json() == {"groups": []}


def test_delete_grouped_player_rejected(client):
    tid = _create_tournament(client, n_players=5)
    client.post(f"/api/tournaments/{tid}/auto-group")
    pid = client.get(f"/api/tournaments/{tid}/players").json()[0]["id"]
    resp = client.delete(f"/api/tournaments/{tid}/players/{pid}")
    assert resp.status_code == 409
    assert "已分组" in resp.json()["detail"]


def test_delete_player_after_ungroup_ok(client):
    tid = _create_tournament(client, n_players=5)
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/ungroup")
    pid = client.get(f"/api/tournaments/{tid}/players").json()[0]["id"]
    resp = client.delete(f"/api/tournaments/{tid}/players/{pid}")
    assert resp.status_code == 204


def test_auto_group_missing_tournament(client):
    resp = client.post("/api/tournaments/999/auto-group")
    assert resp.status_code == 404
