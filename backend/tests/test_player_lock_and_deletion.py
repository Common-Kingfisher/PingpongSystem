"""针对性缺陷修复测试：选手名单锁定（409）与赛事删除（级联、404、无孤儿）。

对应验收 Case 1~6。
"""

import os
import sqlite3


def _create_tournament(client, n_players=5):
    resp = client.post(
        "/api/tournaments",
        json={
            "name": "修复验证赛",
            "date": "2025-06-01",
            "table_count": 6,
            "group_count": 4,
            "qualify_per_group": 2,
        },
    )
    tid = resp.json()["id"]
    for i in range(1, n_players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i}"})
    return tid


def _to_group_stage(client, tid):
    resp = client.post(f"/api/tournaments/{tid}/auto-group")
    assert resp.status_code == 200
    resp = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert resp.status_code == 200
    assert resp.json()["tournament"]["stage"] == "GROUP_STAGE"


# Case 1：REGISTRATION 阶段可添加选手
def test_case1_add_player_when_registration(client):
    tid = _create_tournament(client)
    resp = client.post(f"/api/tournaments/{tid}/players", json={"name": "新选手"})
    assert resp.status_code == 201


# Case 2：GROUP_STAGE 添加选手 → 409（而非 500）
def test_case2_add_player_group_stage_409(client):
    tid = _create_tournament(client)
    _to_group_stage(client, tid)
    resp = client.post(f"/api/tournaments/{tid}/players", json={"name": "新选手"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "赛事已进入比赛阶段，选手名单已锁定"


# Case 3：GROUP_STAGE 修改选手 → 409
def test_case3_update_player_group_stage_409(client):
    tid = _create_tournament(client)
    _to_group_stage(client, tid)
    pid = client.get(f"/api/tournaments/{tid}/players").json()[0]["id"]
    resp = client.patch(f"/api/tournaments/{tid}/players/{pid}", json={"name": "改名"})
    assert resp.status_code == 409


# Case 4：GROUP_STAGE 删除选手 → 409
def test_case4_delete_player_group_stage_409(client):
    tid = _create_tournament(client)
    _to_group_stage(client, tid)
    pid = client.get(f"/api/tournaments/{tid}/players").json()[0]["id"]
    resp = client.delete(f"/api/tournaments/{tid}/players/{pid}")
    assert resp.status_code == 409


# Case 5：删除赛事 → 级联删除全部关联数据，无孤儿
def test_case5_delete_tournament_cascades_no_orphans(client):
    tid = _create_tournament(client, n_players=8)
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    # 录入部分比分，产生 results
    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    tables = client.get(f"/api/tournaments/{tid}/dashboard").json()["tables"]
    for i, m in enumerate(matches[:3]):
        client.post(f"/api/matches/{m['id']}/assign-table", json={"table_id": tables[i]["id"]})
        client.post(f"/api/matches/{m['id']}/score", json={"player_a_score": 3, "player_b_score": 1})

    resp = client.delete(f"/api/tournaments/{tid}")
    assert resp.status_code == 204

    # 直接查库确认无孤儿（client 夹具通过 DEMO_DB_PATH 指向临时库）
    dbpath = os.environ["DEMO_DB_PATH"]
    conn = sqlite3.connect(dbpath)
    try:
        for table in ("players", "groups", "matches", "tables"):
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE tournament_id = ?", (tid,)
            ).fetchone()[0]
            assert cnt == 0, f"{table} 表存在孤儿数据 {cnt} 条"
        assert conn.execute(
            "SELECT COUNT(*) FROM tournaments WHERE id = ?", (tid,)
        ).fetchone()[0] == 0
    finally:
        conn.close()

    # 子资源不可达
    assert client.get(f"/api/tournaments/{tid}").status_code == 404
    assert client.get(f"/api/tournaments/{tid}/players").status_code == 404


# Case 6：删除不存在赛事 → 404
def test_case6_delete_nonexistent_tournament_404(client):
    resp = client.delete("/api/tournaments/99999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "赛事不存在"
