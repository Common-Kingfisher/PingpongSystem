"""种子选手功能测试：分散到不同小组、数量上限、阶段锁定。"""

import random

from app.domain.grouping import auto_group


def _seed_groups(ids, group_count, seeds):
    return auto_group(ids, group_count, random.Random(1), seeds)


def test_four_seeds_dispersed_across_four_groups():
    ids = list(range(1, 17))  # 16 人
    seeds = [1, 2, 3, 4]
    groups = _seed_groups(ids, 4, seeds)
    # 每个种子在不同组
    positions = {}
    for gi, g in enumerate(groups):
        for pid in g:
            if pid in seeds:
                positions[pid] = gi
    assert len(positions) == 4
    assert len(set(positions.values())) == 4
    # 人数均衡
    sizes = sorted(len(g) for g in groups)
    assert max(sizes) - min(sizes) <= 1
    # 不丢不重复
    assert sorted(pid for g in groups for pid in g) == ids


def test_two_seeds_dispersed_and_balanced():
    ids = list(range(1, 17))  # 16 人
    seeds = [1, 2]
    groups = _seed_groups(ids, 4, seeds)
    positions = {}
    for gi, g in enumerate(groups):
        for pid in g:
            if pid in seeds:
                positions[pid] = gi
    assert len(set(positions.values())) == 2
    sizes = sorted(len(g) for g in groups)
    assert max(sizes) - min(sizes) <= 1
    assert sorted(pid for g in groups for pid in g) == ids


def test_no_seeds_same_as_before():
    ids = list(range(1, 17))
    groups = _seed_groups(ids, 4, [])
    assert sorted(pid for g in groups for pid in g) == ids
    assert sorted(len(g) for g in groups) == [4, 4, 4, 4]


def _create(client, n=8, groups=2):
    tid = client.post(
        "/api/tournaments",
        json={"name": "种子测试", "date": "2025-06-01", "table_count": 4, "group_count": groups, "qualify_per_group": 2},
    ).json()["id"]
    for i in range(1, n + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    return tid


def test_seed_api_disperses_on_auto_group(client):
    tid = _create(client, 8, 2)
    players = client.get(f"/api/tournaments/{tid}/players").json()
    # 选手01、选手02 设为 1、2 号种子
    p1 = next(p for p in players if p["name"] == "选手01")["id"]
    p2 = next(p for p in players if p["name"] == "选手02")["id"]
    resp = client.put(f"/api/tournaments/{tid}/seeds", json={"player_ids": [p1, p2]})
    assert resp.status_code == 200
    data = {p["id"]: p for p in resp.json()}
    assert data[p1]["seed_no"] == 1
    assert data[p2]["seed_no"] == 2

    client.post(f"/api/tournaments/{tid}/auto-group")
    groups = client.get(f"/api/tournaments/{tid}/groups").json()["groups"]
    assert len(groups) == 2
    g0_ids = {p["id"] for p in groups[0]["players"]}
    g1_ids = {p["id"] for p in groups[1]["players"]}
    assert (p1 in g0_ids) != (p1 in g1_ids)
    assert (p2 in g0_ids) != (p2 in g1_ids)
    assert (p1 in g0_ids and p2 in g0_ids) is False  # 不在同一组


def test_seeds_exceed_group_count_409(client):
    tid = _create(client, 8, 2)
    players = client.get(f"/api/tournaments/{tid}/players").json()
    ids = [p["id"] for p in players[:3]]
    resp = client.put(f"/api/tournaments/{tid}/seeds", json={"player_ids": ids})
    assert resp.status_code == 409
    assert "最多" in resp.json()["detail"]


def test_seeds_locked_after_group_stage(client):
    tid = _create(client, 8, 2)
    players = client.get(f"/api/tournaments/{tid}/players").json()
    p1 = players[0]["id"]
    client.put(f"/api/tournaments/{tid}/seeds", json={"player_ids": [p1]})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    resp = client.put(f"/api/tournaments/{tid}/seeds", json={"player_ids": [p1]})
    assert resp.status_code == 409
    assert "锁定" in resp.json()["detail"]
