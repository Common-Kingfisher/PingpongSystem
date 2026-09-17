"""赛制配置闭环：局制（三局两胜/五局三胜/七局四胜）与每局目标分。"""

import pytest

from app import repository as repo
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


def _tournament(conn, *, games_to_win=2, points_to_win=11, players=6, group_count=1):
    tournament = repo.create_tournament(
        conn, "赛制验收", "2025-06-01", 2, group_count, 2,
        games_to_win=games_to_win, points_to_win=points_to_win,
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 2)
    for index in range(players):
        repo.add_player(conn, tid, f"P{index + 1}", None)
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    return tid


def _play(conn, tid, score_a, score_b):
    match = repo.list_matches(conn, tid, stage="GROUP")[0]
    scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
    return scores_service.record_score(conn, match["id"], score_a, score_b)


@pytest.mark.parametrize("games_to_win", [2, 3, 4])
def test_aggregate_score_follows_configured_games_to_win(conn, games_to_win):
    for winner_games in range(games_to_win):
        tid = _tournament(conn, games_to_win=games_to_win)
        updated = _play(conn, tid, games_to_win, winner_games)
        assert (updated["player_a_score"], updated["player_b_score"]) == (games_to_win, winner_games)
        assert updated["status"] == "FINISHED"


@pytest.mark.parametrize("games_to_win", [2, 3, 4])
def test_aggregate_score_rejects_wrong_game_count(conn, games_to_win):
    too_many = games_to_win + 1
    too_few = games_to_win - 1
    for score_a, score_b in ((too_many, 0), (too_few, 0), (games_to_win, games_to_win)):
        tid = _tournament(conn, games_to_win=games_to_win)
        with pytest.raises(scores_service.ScoreError):
            _play(conn, tid, score_a, score_b)


@pytest.mark.parametrize("games_to_win", [2, 3, 4])
def test_knockout_uses_same_aggregate_rule(conn, games_to_win):
    tid = _tournament(conn, games_to_win=games_to_win)
    entries = repo.list_entries(conn, tid)
    knockout = repo.create_match(
        conn, tid, "KNOCKOUT", None, 1, 0,
        entries[0]["members"][0]["player_id"], entries[1]["members"][0]["player_id"],
        entry_a_id=entries[0]["id"], entry_b_id=entries[1]["id"],
    )
    accepted = scores_service.record_score(conn, knockout["id"], games_to_win, games_to_win - 1)
    assert accepted["player_a_score"] == games_to_win

    other = repo.create_match(
        conn, tid, "KNOCKOUT", None, 1, 1,
        entries[2]["members"][0]["player_id"], entries[3]["members"][0]["player_id"],
        entry_a_id=entries[2]["id"], entry_b_id=entries[3]["id"],
    )
    with pytest.raises(scores_service.ScoreError):
        scores_service.record_score(conn, other["id"], games_to_win - 1, 0)


@pytest.mark.parametrize("points_to_win", [11, 21])
def test_game_supplement_uses_points_to_win(conn, points_to_win):
    tid = _tournament(conn, games_to_win=2, points_to_win=points_to_win)
    match = repo.list_matches(conn, tid, stage="GROUP")[0]
    scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
    scores_service.record_score(conn, match["id"], 2, 0)

    legal = [(points_to_win, points_to_win - 2), (points_to_win, 3)]
    illegal = [(points_to_win + 10, points_to_win - 2), (points_to_win - 1, 3)]

    updated = scores_service.revise_score(conn, match["id"], None, None, games=legal)
    assert len(updated["games"]) == 2

    with pytest.raises(scores_service.ScoreError):
        scores_service.revise_score(conn, match["id"], None, None, games=illegal)


@pytest.mark.parametrize("games_to_win", [2, 3, 4])
def test_demo_simulation_respects_games_to_win(client, games_to_win):
    """Demo 模拟必须按局制生成合法比分（旧实现写死 2:0 会让 3/4 局制 500）。"""
    tid = client.post(
        "/api/tournaments",
        json={
            "name": f"演示{games_to_win}局制",
            "date": "2025-06-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 2,
            "operation_mode": "DEMO",
            "games_to_win": games_to_win,
        },
    ).json()["id"]
    for index in range(8):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    resp = client.post(f"/api/tournaments/{tid}/demo/finish-group-stage")

    assert resp.status_code == 200
    assert resp.json()["finished"] == 12
    matches = client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()
    assert all(m["status"] == "FINISHED" for m in matches)
    assert all(
        max(m["player_a_score"], m["player_b_score"]) == games_to_win for m in matches
    )


def test_api_format_config_is_persisted_and_returned(client):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "五局三胜 21 分",
            "date": "2025-06-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 2,
            "games_to_win": 3,
            "points_to_win": 21,
        },
    ).json()["id"]
    for index in range(4):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1}"})

    tournament = client.get(f"/api/tournaments/{tid}").json()
    assert tournament["games_to_win"] == 3
    assert tournament["points_to_win"] == 21

    snapshot = client.get(f"/api/tournaments/{tid}/order-book-snapshot").json()
    assert snapshot["tournament"]["games_to_win"] == 3
    assert snapshot["tournament"]["points_to_win"] == 21


def test_demo_simulation_rejects_unsupported_format_with_readable_error(client):
    """业务异常不能裸 500：非法局制由 Pydantic 拦下（422）。"""
    resp = client.post(
        "/api/tournaments",
        json={
            "name": "非法局制",
            "date": "2025-06-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 2,
            "games_to_win": 5,
        },
    )
    assert resp.status_code == 422
