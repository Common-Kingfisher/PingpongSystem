"""主裁判赛前检查聚合接口。"""

from app import repository as repo


def _create(client, mode="LIVE"):
    return client.post(
        "/api/tournaments",
        json={
            "name": "赛前检查测试",
            "date": "2026-09-09",
            "table_count": 2,
            "group_count": 1,
            "qualify_per_group": 2,
            "operation_mode": mode,
        },
    ).json()["id"]


def test_empty_tournament_reports_actionable_blockers(client):
    tournament_id = _create(client)

    response = client.get(f"/api/tournaments/{tournament_id}/preflight")

    assert response.status_code == 200
    report = response.json()
    assert report["overall"] == "BLOCK"
    assert report["blocker_count"] >= 4
    codes = {item["code"]: item for item in report["checks"]}
    assert codes["roster"]["level"] == "BLOCK"
    assert codes["groups"]["action_path"] == f"/players?tid={tournament_id}"
    assert codes["rules"]["level"] == "READY"


def test_prepared_schedule_has_no_blocker_and_demo_is_warned(client):
    tournament_id = _create(client, "DEMO")
    for index in range(4):
        client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": f"选手{index + 1}"},
        )
    client.post(f"/api/tournaments/{tournament_id}/auto-group")
    client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")

    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()

    assert report["blocker_count"] == 0
    assert report["overall"] == "WARN"
    assert report["metrics"]["players"] == 4
    assert report["metrics"]["matches"] == 6
    mode = next(item for item in report["checks"] if item["code"] == "operation_mode")
    assert mode["level"] == "WARN"


def test_table_state_mismatch_is_a_blocker(client, conn):
    tournament_id = _create(client)
    conn.execute(
        "UPDATE tables SET status = 'OCCUPIED' WHERE tournament_id = ? AND id = "
        "(SELECT MIN(id) FROM tables WHERE tournament_id = ?)",
        (tournament_id, tournament_id),
    )
    conn.commit()

    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()

    tables = next(item for item in report["checks"] if item["code"] == "tables")
    assert tables["level"] == "BLOCK"


def test_zero_match_group_stage_is_not_reported_as_ungenerated(client):
    tournament_id = client.post(
        "/api/tournaments",
        json={
            "name": "单人小组测试",
            "date": "2026-09-09",
            "table_count": 2,
            "group_count": 4,
            "qualify_per_group": 1,
        },
    ).json()["id"]
    for index in range(4):
        client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": f"选手{index + 1}"},
        )
    client.post(f"/api/tournaments/{tournament_id}/auto-group")
    generated = client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")
    assert generated.json()["matches_generated"] == 0

    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()

    schedule = next(item for item in report["checks"] if item["code"] == "group_schedule")
    knockout = next(item for item in report["checks"] if item["code"] == "knockout")
    assert schedule["level"] == "READY"
    assert "无需产生" in schedule["detail"]
    assert knockout["level"] == "READY"


def test_duplicate_playing_table_assignment_is_a_blocker(client, conn):
    tournament_id = _create(client)
    for index in range(4):
        client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": f"选手{index + 1}"},
        )
    client.post(f"/api/tournaments/{tournament_id}/auto-group")
    client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")
    matches = client.get(f"/api/tournaments/{tournament_id}/matches").json()[:2]
    tables = client.get(f"/api/tournaments/{tournament_id}/dashboard").json()["tables"]
    conn.execute(
        "UPDATE matches SET status = 'PLAYING', table_id = ? WHERE id IN (?, ?)",
        (tables[0]["id"], matches[0]["id"], matches[1]["id"]),
    )
    conn.execute(
        "UPDATE tables SET status = 'OCCUPIED' WHERE id IN (?, ?)",
        (tables[0]["id"], tables[1]["id"]),
    )
    conn.commit()

    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()

    table_check = next(item for item in report["checks"] if item["code"] == "tables")
    assert table_check["level"] == "BLOCK"
