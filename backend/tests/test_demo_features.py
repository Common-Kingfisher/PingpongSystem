"""Demo 功能测试：一键生成演示选手、一键模拟剩余小组赛。"""


def _create(client, n_players=0, group_count=4, qualify=2, table_count=6):
    tid = client.post(
        "/api/tournaments",
        json={"name": "Demo功能", "date": "2025-06-01", "table_count": table_count, "group_count": group_count, "qualify_per_group": qualify},
    ).json()["id"]
    for i in range(1, n_players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    return tid


def test_demo_generate_players_with_seeds(client):
    tid = _create(client)
    resp = client.post(
        f"/api/tournaments/{tid}/demo/generate-players",
        json={"count": 16, "with_seeds": True},
    )
    assert resp.status_code == 200
    players = resp.json()
    assert len(players) == 16
    assert players[0]["name"] == "选手01"
    assert players[0]["college"] in ("计算机学院", "自动化学院", "机械学院", "电子信息学院")
    # 前 4 名自动设为种子
    seed_nos = sorted(p["seed_no"] for p in players if p["seed_no"] is not None)
    assert seed_nos == [1, 2, 3, 4]
    seeded = [p["name"] for p in players if p["seed_no"] is not None]
    assert seeded == ["选手01", "选手02", "选手03", "选手04"]


def test_demo_generate_players_respects_group_count(client):
    tid = _create(client, group_count=2)
    resp = client.post(
        f"/api/tournaments/{tid}/demo/generate-players",
        json={"count": 8, "with_seeds": True},
    )
    assert resp.status_code == 200
    seed_nos = sorted(p["seed_no"] for p in resp.json() if p["seed_no"] is not None)
    assert seed_nos == [1, 2]  # 2 个小组最多 2 名种子


def test_demo_generate_players_appends_existing(client):
    tid = _create(client, n_players=5)
    resp = client.post(
        f"/api/tournaments/{tid}/demo/generate-players",
        json={"count": 3, "with_seeds": False},
    )
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "选手06" in names and "选手08" in names  # 追加在现有 5 名之后


def test_demo_generate_players_locked_after_stage(client):
    tid = _create(client, n_players=8, group_count=2)
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    resp = client.post(f"/api/tournaments/{tid}/demo/generate-players", json={"count": 8, "with_seeds": True})
    assert resp.status_code == 409


def test_demo_finish_group_stage(client):
    tid = _create(client, n_players=8, group_count=2, table_count=4)
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    resp = client.post(f"/api/tournaments/{tid}/demo/finish-group-stage")
    assert resp.status_code == 200
    assert resp.json()["finished"] == 12  # 2 组 × 4 人 = 12 场

    matches = client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()
    assert all(m["status"] == "FINISHED" for m in matches)
    # 排名已重算且无并列歧义（随机比分也可能产生并列，这里只验证已结束）
    rankings = client.get(f"/api/tournaments/{tid}/rankings").json()
    assert all(g["finished_matches"] == g["total_matches"] for g in rankings["rankings"])
    # 全部结束后可生成淘汰赛（若晋级无歧义）
    resp = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert resp.status_code in (200, 409)  # 409 仅当随机比分造成晋级线并列


def test_demo_finish_group_stage_only_in_group_stage(client):
    tid = _create(client)
    resp = client.post(f"/api/tournaments/{tid}/demo/finish-group-stage")
    assert resp.status_code == 409
