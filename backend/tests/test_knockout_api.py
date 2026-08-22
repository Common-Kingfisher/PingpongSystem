"""淘汰赛 API 端点测试。"""


def _full_group_stage(client, n_players=8, group_count=4):
    resp = client.post(
        "/api/tournaments",
        json={"name": "KO", "date": "2025-06-01", "table_count": 6, "group_count": group_count, "qualify_per_group": 2},
    )
    tid = resp.json()["id"]
    for i in range(1, n_players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    # 打完全部小组赛（id 小者 3:0 胜）
    for _ in range(50):
        client.post(f"/api/tournaments/{tid}/schedule-next")
        dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [tb["match"] for tb in dash["tables"] if tb["match"]]
        if not playing:
            break
        for m in playing:
            w = min(m["player_a_id"], m["player_b_id"])
            sa, sb = (3, 0) if w == m["player_a_id"] else (0, 3)
            client.post(f"/api/matches/{m['id']}/score", json={"player_a_score": sa, "player_b_score": sb})
    return tid


def test_generate_knockout_api(client):
    tid = _full_group_stage(client)
    resp = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tournament"]["stage"] == "KNOCKOUT"
    assert [len(r["matches"]) for r in data["rounds"]] == [4, 2, 1]
    assert [r["label"] for r in data["rounds"]] == ["8强赛", "半决赛", "决赛"]
    assert data["champion"] is None

    resp = client.get(f"/api/tournaments/{tid}/knockout")
    assert resp.status_code == 200
    assert resp.json()["tournament"]["stage"] == "KNOCKOUT"


def test_generate_knockout_before_group_stage_409(client):
    resp = client.post(
        "/api/tournaments",
        json={"name": "KO2", "date": "2025-06-01", "table_count": 6, "group_count": 4, "qualify_per_group": 2},
    )
    tid = resp.json()["id"]
    for i in range(1, 9):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    # 未生成小组赛（阶段还是 REGISTRATION）
    resp = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert resp.status_code == 409


def test_knockout_full_flow_to_champion(client):
    tid = _full_group_stage(client)
    client.post(f"/api/tournaments/{tid}/generate-knockout")
    # 打完淘汰赛
    for _ in range(50):
        client.post(f"/api/tournaments/{tid}/schedule-next")
        dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [tb["match"] for tb in dash["tables"] if tb["match"]]
        if not playing:
            break
        for m in playing:
            w = min(m["player_a_id"], m["player_b_id"])
            sa, sb = (3, 0) if w == m["player_a_id"] else (0, 3)
            client.post(f"/api/matches/{m['id']}/score", json={"player_a_score": sa, "player_b_score": sb})

    data = client.get(f"/api/tournaments/{tid}/knockout").json()
    assert data["champion"] is not None
    assert data["champion"]["id"] == 1  # id 最小者全胜
    assert data["runner_up"] is not None
    assert data["tournament"]["stage"] == "FINISHED"
    # 冠军在每轮都出现
    for r in data["rounds"]:
        ids = [m["player_a"]["id"] for m in r["matches"] if m["player_a"]] + \
              [m["player_b"]["id"] for m in r["matches"] if m["player_b"]]
        assert data["champion"]["id"] in ids
