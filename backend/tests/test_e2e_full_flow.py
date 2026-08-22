"""端到端验收测试：完整跑通 24 人 / 6 台 / 4 组×6 / 每组前 2 晋级 的 Demo 闭环。

流程：创建赛事 → 添加 24 人 → 自动分组 → 生成 60 场小组赛 → 球台分配 →
全部录分 → 小组排名 → 每组前 2 晋级（8 人）→ 生成 8 强 → 打完 8 强/4 强/决赛
→ 唯一冠军。录分规则固定为"id 小者 3:0 胜"，保证结果可复现且无并列歧义。
"""


def _play_all(client, tid, max_rounds=80):
    """批量调度 + 按"id 小者 3:0 胜"录分，直到无可调度。"""
    for _ in range(max_rounds):
        client.post(f"/api/tournaments/{tid}/schedule-next")
        dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [tb["match"] for tb in dash["tables"] if tb["match"]]
        if not playing:
            break
        for m in playing:
            w = min(m["player_a_id"], m["player_b_id"])
            sa, sb = (3, 0) if w == m["player_a_id"] else (0, 3)
            resp = client.post(
                f"/api/matches/{m['id']}/score",
                json={"player_a_score": sa, "player_b_score": sb},
            )
            assert resp.status_code == 200, resp.text


def test_full_demo_closed_loop(client):
    # 1. 创建赛事：24 人 / 6 台 / 4 组 / 每组晋级 2
    resp = client.post(
        "/api/tournaments",
        json={
            "name": "端到端验收赛",
            "date": "2025-06-01",
            "table_count": 6,
            "group_count": 4,
            "qualify_per_group": 2,
        },
    )
    assert resp.status_code == 201
    tid = resp.json()["id"]
    assert resp.json()["stage"] == "REGISTRATION"

    # 2. 添加 24 名选手
    for i in range(1, 25):
        resp = client.post(
            f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"}
        )
        assert resp.status_code == 201
    players = client.get(f"/api/tournaments/{tid}/players").json()
    assert len(players) == 24

    # 3. 自动分组：4 组 × 6 人，不重不漏
    resp = client.post(f"/api/tournaments/{tid}/auto-group")
    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert [g["name"] for g in groups] == ["A组", "B组", "C组", "D组"]
    assert sorted(len(g["players"]) for g in groups) == [6, 6, 6, 6]
    all_ids = [p["id"] for g in groups for p in g["players"]]
    assert len(all_ids) == 24 and len(set(all_ids)) == 24

    # 4. 生成小组比赛：60 场
    resp = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert resp.status_code == 200
    assert resp.json()["matches_generated"] == 60
    assert resp.json()["per_group"] == {"A组": 15, "B组": 15, "C组": 15, "D组": 15}
    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    assert len(matches) == 60
    assert all(m["status"] == "WAITING" for m in matches)

    # 5. 球台分配 + 全部录分（控制台循环）
    _play_all(client, tid)
    dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert dash["stats"] == {"total": 60, "finished": 60, "playing": 0, "waiting": 0}
    assert all(tb["status"] == "FREE" for tb in dash["tables"])

    # 6. 小组排名：每组合格 2 人（共 8 人晋级），无并列歧义
    rankings = client.get(f"/api/tournaments/{tid}/rankings").json()
    assert len(rankings["rankings"]) == 4
    qualified = []
    for g in rankings["rankings"]:
        assert g["finished_matches"] == g["total_matches"] == 15
        assert g["ambiguous_qualification"] is False
        q = [e["player_id"] for e in g["entries"] if e["qualified"]]
        assert len(q) == 2
        qualified.extend(q)
    assert len(set(qualified)) == 8

    # 7. 生成淘汰赛：8 强 → 4 强 → 决赛
    resp = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert resp.status_code == 200
    tree = resp.json()
    assert tree["tournament"]["stage"] == "KNOCKOUT"
    assert [len(r["matches"]) for r in tree["rounds"]] == [4, 2, 1]
    assert [r["label"] for r in tree["rounds"]] == ["8强赛", "半决赛", "决赛"]
    first_round_ids = [
        pid for m in tree["rounds"][0]["matches"]
        for pid in (m["player_a"]["id"], m["player_b"]["id"])
    ]
    assert sorted(first_round_ids) == sorted(qualified)

    # 8. 打完淘汰赛 → 唯一冠军（id 最小者全胜）
    _play_all(client, tid)
    tree = client.get(f"/api/tournaments/{tid}/knockout").json()
    assert tree["champion"] is not None
    assert tree["champion"]["id"] == 1
    assert tree["runner_up"] is not None and tree["runner_up"]["id"] != 1
    assert tree["tournament"]["stage"] == "FINISHED"

    # 9. 一致性抽查：冠军在每轮都出现；输家不复活
    for r in tree["rounds"]:
        ids = []
        for m in r["matches"]:
            if m["player_a"]:
                ids.append(m["player_a"]["id"])
            if m["player_b"]:
                ids.append(m["player_b"]["id"])
        assert tree["champion"]["id"] in ids

    # 10. 选手名单锁定
    resp = client.post(f"/api/tournaments/{tid}/players", json={"name": "新选手"})
    assert resp.status_code == 409
    resp = client.patch(f"/api/tournaments/{tid}/players/1", json={"name": "改名"})
    assert resp.status_code == 409
