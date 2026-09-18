"""主裁判赛前检查聚合接口。"""

from app import repository as repo
import pytest


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


@pytest.mark.parametrize("qualify", [1, 2])
def test_zero_match_group_stage_is_not_reported_as_ungenerated(client, qualify):
    tournament_id = client.post(
        "/api/tournaments",
        json={
            "name": "单人小组测试",
            "date": "2026-09-09",
            "table_count": 2,
            "group_count": 4,
            "qualify_per_group": qualify,
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
    assert knockout["level"] == ("READY" if qualify == 1 else "BLOCK")
    qualification = next(item for item in report["checks"] if item["code"] == "qualification")
    assert qualification["level"] == ("READY" if qualify == 1 else "BLOCK")


def test_zero_match_group_can_regenerate_knockout_after_undo(client):
    tournament_id = client.post(
        "/api/tournaments",
        json={
            "name": "零场小组撤销往返测试",
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
    assert generated.status_code == 200
    assert generated.json()["matches_generated"] == 0

    first_knockout = client.post(f"/api/tournaments/{tournament_id}/generate-knockout")
    assert first_knockout.status_code == 200

    undone = client.post(f"/api/tournaments/{tournament_id}/knockout/undo")
    assert undone.status_code == 200
    assert undone.json()["tournament"]["stage"] == "GROUP_STAGE"

    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()
    schedule = next(item for item in report["checks"] if item["code"] == "group_schedule")
    assert schedule["level"] == "READY"
    assert "无需产生" in schedule["detail"]

    regenerated = client.post(f"/api/tournaments/{tournament_id}/generate-knockout")
    assert regenerated.status_code == 200


def _withdraw(client, tournament_id, entry_id):
    response = client.post(
        f"/api/tournaments/{tournament_id}/entries/{entry_id}/withdraw",
        json={"operator_name": "李主裁", "reason": "赛前确认退赛"},
    )
    assert response.status_code == 200


def _create_with_six_entries(client):
    tournament_id = client.post(
        "/api/tournaments",
        json={
            "name": "退赛赛前检查",
            "date": "2026-09-09",
            "table_count": 2,
            "group_count": 2,
            "qualify_per_group": 1,
        },
    ).json()["id"]
    for index in range(6):
        client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": f"选手{index + 1}"},
        )
    confirmed = client.post(f"/api/tournaments/{tournament_id}/confirm-roster")
    assert confirmed.status_code == 200
    entries = client.get(f"/api/tournaments/{tournament_id}/entries").json()
    return tournament_id, entries


def _preflight_checks(client, tournament_id):
    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()
    return {item["code"]: item for item in report["checks"]}


def test_withdrawal_before_grouping_does_not_require_withdrawn_entry_assignment(client):
    tournament_id, entries = _create_with_six_entries(client)
    _withdraw(client, tournament_id, entries[0]["id"])

    assert client.post(f"/api/tournaments/{tournament_id}/auto-group").status_code == 200
    assert client.post(f"/api/tournaments/{tournament_id}/generate-group-matches").status_code == 200

    checks = _preflight_checks(client, tournament_id)
    assert checks["groups"]["level"] == "READY"
    assert checks["group_schedule"]["level"] != "BLOCK"


def test_withdrawal_after_grouping_does_not_require_new_fixture(client):
    tournament_id, entries = _create_with_six_entries(client)
    assert client.post(f"/api/tournaments/{tournament_id}/auto-group").status_code == 200
    _withdraw(client, tournament_id, entries[0]["id"])

    generated = client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")
    assert generated.status_code == 200
    assert generated.json()["matches_generated"] == 4

    checks = _preflight_checks(client, tournament_id)
    assert checks["groups"]["level"] == "READY"
    assert checks["group_schedule"]["level"] != "BLOCK"


def test_withdrawal_after_schedule_keeps_valid_historical_fixtures(client):
    tournament_id, entries = _create_with_six_entries(client)
    assert client.post(f"/api/tournaments/{tournament_id}/auto-group").status_code == 200
    generated = client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")
    assert generated.status_code == 200
    assert generated.json()["matches_generated"] == 6

    _withdraw(client, tournament_id, entries[0]["id"])

    matches = client.get(f"/api/tournaments/{tournament_id}/matches").json()
    assert len([match for match in matches if match["stage"] == "GROUP"]) == 6
    checks = _preflight_checks(client, tournament_id)
    assert checks["groups"]["level"] == "READY"
    assert checks["group_schedule"]["level"] != "BLOCK"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "null", "empty"])
def test_invalid_round_robin_blocks_qualification(client, conn, damage):
    tid = _create(client)
    for index in range(4):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"球员{index}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    matches = repo.list_matches(conn, tid)
    if damage in ("missing", "empty"):
        conn.execute("DELETE FROM matches WHERE tournament_id = ? AND id != ?", (tid, matches[0]["id"] if damage == "missing" else -1))
    elif damage == "duplicate":
        conn.execute("UPDATE matches SET entry_a_id = ?, entry_b_id = ? WHERE id = ?", (matches[0]["entry_a_id"], matches[0]["entry_b_id"], matches[1]["id"]))
    else:
        conn.execute("UPDATE matches SET entry_a_id = NULL WHERE id = ?", (matches[0]["id"],))
    conn.execute("UPDATE matches SET status = 'FINISHED', player_a_score = 2, player_b_score = 0, winner_entry_id = entry_a_id WHERE tournament_id = ?", (tid,))
    conn.commit()
    report = client.get(f"/api/tournaments/{tid}/preflight").json()
    checks = {item["code"]: item for item in report["checks"]}
    assert report["overall"] == "BLOCK"
    for code in ("group_schedule", "qualification", "knockout"):
        assert checks[code]["level"] == "BLOCK"


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


@pytest.mark.parametrize(("event_type", "player_count"), [("SINGLES", 4), ("DOUBLES", 8)])
def test_player_cannot_be_in_two_playing_matches(client, conn, event_type, player_count):
    tournament_id = client.post(
        "/api/tournaments",
        json={
            "name": f"{event_type} 重复上场检查",
            "date": "2026-09-09",
            "table_count": 2,
            "group_count": 1,
            "qualify_per_group": 2,
            "event_type": event_type,
        },
    ).json()["id"]
    for index in range(player_count):
        client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": f"运动员{index + 1}", "rating_points": 1000 + index},
        )
    if event_type == "DOUBLES":
        paired = client.post(
            f"/api/tournaments/{tournament_id}/pair-doubles",
            json={"pairing_seed": 42},
        )
        assert paired.status_code == 200
    confirmed = client.post(f"/api/tournaments/{tournament_id}/confirm-roster")
    assert confirmed.status_code == 200
    client.post(f"/api/tournaments/{tournament_id}/auto-group")
    client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")

    entries = {entry["id"]: entry for entry in repo.list_entries(conn, tournament_id)}
    matches = repo.list_matches(conn, tournament_id)

    def members(match):
        return {
            member["player_id"]
            for entry_id in (match["entry_a_id"], match["entry_b_id"])
            for member in entries[entry_id]["members"]
        }

    first = matches[0]
    second = next(match for match in matches[1:] if members(first) & members(match))
    tables = repo.list_tables(conn, tournament_id)
    conn.execute(
        "UPDATE matches SET status = 'PLAYING', table_id = ? WHERE id = ?",
        (tables[0]["id"], first["id"]),
    )
    conn.execute(
        "UPDATE matches SET status = 'PLAYING', table_id = ? WHERE id = ?",
        (tables[1]["id"], second["id"]),
    )
    conn.execute(
        "UPDATE tables SET status = 'OCCUPIED' WHERE id IN (?, ?)",
        (tables[0]["id"], tables[1]["id"]),
    )
    conn.commit()

    report = client.get(f"/api/tournaments/{tournament_id}/preflight").json()
    checks = {item["code"]: item for item in report["checks"]}
    assert checks["tables"]["level"] == "READY"
    assert checks["playing_participants"]["level"] == "BLOCK"
    assert report["overall"] == "BLOCK"
