"""V0.2 关键业务验收：统一 Entry、逐局比分、2/1/0、排位赛与可调出线。"""


def _tournament(client, **overrides):
    body = {
        "name": "V0.2 验收赛",
        "date": "2026-09-03",
        "table_count": 4,
        "group_count": 4,
        "qualify_per_group": 2,
        "event_type": "SINGLES",
        "bronze_mode": "JOINT_BRONZE",
        "placement_mode": "COMPLETE",
        "games_to_win": 2,
        "points_to_win": 11,
    }
    body.update(overrides)
    response = client.post("/api/tournaments", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_players(client, tid, count):
    for index in range(count):
        response = client.post(
            f"/api/tournaments/{tid}/players",
            json={
                "name": f"运动员{index + 1:02d}",
                "college": f"学院{index % 4 + 1}",
                "rating_points": 1800 - index * 25,
            },
        )
        assert response.status_code == 201, response.text


def _normal_score(client, match_id):
    response = client.post(
        f"/api/matches/{match_id}/score",
        json={
            "games": [
                {"side_a_score": 11, "side_b_score": 6},
                {"side_a_score": 9, "side_b_score": 11},
                {"side_a_score": 12, "side_b_score": 10},
            ],
            "result_type": "NORMAL",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["player_a_score"] == 2
    assert response.json()["player_b_score"] == 1
    assert len(response.json()["games"]) == 3


def test_doubles_pairing_is_reproducible_and_complete(client):
    tid = _tournament(client, event_type="DOUBLES", group_count=2)
    _add_players(client, tid, 8)
    first = client.post(f"/api/tournaments/{tid}/pair-doubles", json={"pairing_seed": 42})
    assert first.status_code == 200, first.text
    assert len(first.json()["entries"]) == 4
    assert first.json()["unpaired_players"] == []
    pair_names = [entry["display_name"] for entry in first.json()["entries"]]
    second = client.post(f"/api/tournaments/{tid}/pair-doubles", json={"pairing_seed": 42})
    assert [entry["display_name"] for entry in second.json()["entries"]] == pair_names
    confirmed = client.post(f"/api/tournaments/{tid}/confirm-roster")
    assert confirmed.status_code == 200
    assert confirmed.json()["tournament"]["roster_confirmed"] is True


def test_import_preview_does_not_write_before_confirmation(client):
    tid = _tournament(client, group_count=2)
    content = "姓名,学院/单位,运动员积分,种子序号\n张三,计算机学院,1500,1\n李四,自动化学院,1450,2\n".encode("utf-8")
    preview = client.post(
        f"/api/tournaments/{tid}/players/import/preview",
        files={"file": ("players.csv", content, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 2
    assert client.get(f"/api/tournaments/{tid}/players").json() == []
    committed = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("players.csv", content, "text/csv")},
    )
    assert committed.status_code == 200
    assert len(client.get(f"/api/tournaments/{tid}/players").json()) == 2


def test_group_forfeit_uses_two_zero_points_policy(client):
    tid = _tournament(client, group_count=1, qualify_per_group=1)
    _add_players(client, tid, 2)
    client.post(f"/api/tournaments/{tid}/confirm-roster")
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    match = client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()[0]
    response = client.post(
        f"/api/matches/{match['id']}/score",
        json={"result_type": "FORFEIT", "forfeit_entry_id": match["entry_b_id"]},
    )
    assert response.status_code == 200, response.text
    assert (response.json()["player_a_score"], response.json()["player_b_score"]) == (2, 0)
    rows = client.get(f"/api/tournaments/{tid}/rankings").json()["rankings"][0]["entries"]
    assert rows[0]["match_points"] == 2
    assert rows[1]["match_points"] == 0


def test_complete_eight_entry_placement_and_champion_path(client):
    tid = _tournament(client)
    _add_players(client, tid, 8)
    client.post(f"/api/tournaments/{tid}/confirm-roster")
    groups = client.post(f"/api/tournaments/{tid}/auto-group").json()["groups"]
    assert len(groups) == 4
    changed = client.patch(
        f"/api/tournaments/{tid}/groups/{groups[0]['id']}/qualification",
        json={"qualify_count": 1},
    )
    assert changed.status_code == 200
    # 恢复为 2 人出线直接使用赛事默认值，验证接口后重新抽签以获得完整 8 人签表。
    client.post(f"/api/tournaments/{tid}/ungroup")
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    for match in client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json():
        _normal_score(client, match["id"])
    generated = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert generated.status_code == 200, generated.text
    assert [len(round_["matches"]) for round_ in generated.json()["rounds"]] == [4, 2, 1]

    for _ in range(6):
        matches = client.get(f"/api/tournaments/{tid}/matches?stage=KNOCKOUT").json()
        playable = [m for m in matches if m["status"] == "WAITING" and m["entry_a_id"] and m["entry_b_id"]]
        if not playable:
            break
        for match in playable:
            _normal_score(client, match["id"])

    tree = client.get(f"/api/tournaments/{tid}/knockout").json()
    assert tree["champion"] is not None
    assert len(tree["champion_path_match_ids"]) == 3
    ranks = [row["rank"] for row in tree["placements"]]
    assert ranks == [1, 2, 3, 3, 5, 6, 7, 8]
    assert tree["tournament"]["stage"] == "FINISHED"
