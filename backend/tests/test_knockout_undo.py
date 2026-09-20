"""A1-1 / A1-2：撤销淘汰签表与重新生成。

覆盖：正常撤销、轮空可撤销、名次排位一并删除、已开赛拒绝、撤销后修正小组比分并重签。
"""

import pytest

from app import repository as repo
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import rankings as rankings_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


def _build(conn, *, players=8, group_count=4, qualify=2, table_count=4, **kwargs):
    tournament = repo.create_tournament(
        conn, "撤销验收", "2025-06-01", table_count, group_count, qualify, **kwargs
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, table_count)
    for index in range(players):
        repo.add_player(conn, tid, f"P{index + 1:02d}", None)
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    return tid


def _play_all_group_matches(conn, tid):
    """批量排台 + 录分（id 小者 2:0 胜），直到小组赛全部结束。"""
    for _ in range(200):
        assignments = scheduling_service.schedule_next(conn, tid)
        playing = repo.list_playing_matches(conn, tid)
        if not assignments and not playing:
            break
        for match in playing:
            winner = min(match["player_a_id"], match["player_b_id"])
            score_a, score_b = (2, 0) if winner == match["player_a_id"] else (0, 2)
            scores_service.record_score(conn, match["id"], score_a, score_b)


def _knockout_matches(conn, tid, bracket="MAIN"):
    return [
        match for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["bracket"] == bracket
    ]


def _qualifier_labels(conn, tid):
    """entry_id → (组名, 组内晋级名次)，用于断言实际对阵。"""
    labels = {}
    for group in rankings_service.get_rankings(conn, tid):
        rank = 0
        for entry in group["entries"]:
            if entry["qualified"]:
                rank += 1
                labels[entry["player_id"]] = (group["group_name"], rank)
    return labels


def test_undo_knockout_before_start_restores_group_stage(conn):
    tid = _build(conn, players=16, group_count=4, qualify=2, table_count=4)
    _play_all_group_matches(conn, tid)
    group_matches = repo.list_matches(conn, tid, stage="GROUP")
    group_scores = {m["id"]: (m["player_a_score"], m["player_b_score"]) for m in group_matches}
    players_before = len(repo.list_players(conn, tid))
    entries_before = len(repo.list_entries(conn, tid))

    knockout_service.generate_knockout(conn, tid)
    # 4 组 × 2 = 8 名晋级 → 4 场首轮 + 2 半决赛 + 1 决赛 = 7 场主签
    assert len(_knockout_matches(conn, tid)) == 7
    assert repo.get_tournament(conn, tid)["stage"] == "KNOCKOUT"

    result = knockout_service.undo_knockout(conn, tid)

    assert result["deleted_main_matches"] == 7
    assert result["deleted_placement_matches"] == 0
    assert result["deleted_matches"] == 7
    assert repo.list_matches(conn, tid, stage="KNOCKOUT") == []
    # 小组数据必须原样保留
    remaining = repo.list_matches(conn, tid, stage="GROUP")
    assert len(remaining) == len(group_matches)
    assert {m["id"]: (m["player_a_score"], m["player_b_score"]) for m in remaining} == group_scores
    assert len(repo.list_players(conn, tid)) == players_before
    assert len(repo.list_entries(conn, tid)) == entries_before
    assert len(repo.list_groups(conn, tid)) == 4
    # 阶段恢复 + 排名仍可读取
    assert repo.get_tournament(conn, tid)["stage"] == "GROUP_STAGE"
    rankings = rankings_service.get_rankings(conn, tid)
    assert [len([e for e in g["entries"] if e["qualified"]]) for g in rankings] == [2, 2, 2, 2]
    # 球台没有被淘汰赛永久占用
    assert all(t["status"] == "FREE" for t in repo.list_tables(conn, tid))


def test_undo_knockout_removes_placement_matches(conn):
    """名次排位比赛引用主签，必须先删排位再删主签（外键顺序）。"""
    tid = _build(
        conn, players=8, group_count=4, qualify=2,
        placement_mode="COMPLETE", bronze_mode="BRONZE_MATCH",
    )
    _play_all_group_matches(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    main = _knockout_matches(conn, tid)
    assert len(main) == 7

    repo.create_match(
        conn, tid, "KNOCKOUT", None, 1, 0, None, None,
        prev_match_a_id=main[0]["id"], prev_match_b_id=main[1]["id"],
        prev_match_a_outcome="LOSER", prev_match_b_outcome="LOSER",
        bracket="PLACEMENT", placement_min=5, placement_max=8,
    )
    conn.commit()

    result = knockout_service.undo_knockout(conn, tid)

    assert result["deleted_placement_matches"] == 1
    assert result["deleted_main_matches"] == 7
    assert repo.list_matches(conn, tid, stage="KNOCKOUT") == []


def test_undo_knockout_allowed_with_system_byes(conn):
    """6 组 = 12 人 → 16 签：系统轮空（一方为空 WALKOVER）不算真实结果，允许撤销。"""
    tid = _build(conn, players=12, group_count=6, qualify=2, table_count=4)
    _play_all_group_matches(conn, tid)
    knockout_service.generate_knockout(conn, tid)

    knockout = repo.list_matches(conn, tid, stage="KNOCKOUT")
    assert sum(1 for m in knockout if m["result_type"] == "WALKOVER") == 4
    assert len(knockout) == 15

    result = knockout_service.undo_knockout(conn, tid)

    assert result["deleted_main_matches"] == 15
    assert repo.list_matches(conn, tid, stage="KNOCKOUT") == []
    assert repo.get_tournament(conn, tid)["stage"] == "GROUP_STAGE"


def test_undo_knockout_rejected_after_result_recorded(conn):
    tid = _build(conn, players=8, group_count=4, qualify=2)
    _play_all_group_matches(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    match = _knockout_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    scores_service.record_score(conn, match["id"], 2, 0)

    with pytest.raises(knockout_service.KnockoutError) as excinfo:
        knockout_service.undo_knockout(conn, tid)

    assert excinfo.value.code == 409
    assert "淘汰赛已经开始" in str(excinfo.value)
    # 真实结果不得被删除
    assert len(_knockout_matches(conn, tid)) == 7
    assert repo.get_match(conn, match["id"])["status"] == "FINISHED"


def test_undo_knockout_rejected_while_match_playing(conn):
    tid = _build(conn, players=8, group_count=4, qualify=2)
    _play_all_group_matches(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    match = _knockout_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])

    with pytest.raises(knockout_service.KnockoutError) as excinfo:
        knockout_service.undo_knockout(conn, tid)

    assert excinfo.value.code == 409
    assert repo.get_match(conn, match["id"])["status"] == "PLAYING"


def test_undo_knockout_rejected_when_not_generated(conn):
    tid = _build(conn, players=8, group_count=4, qualify=2)
    _play_all_group_matches(conn, tid)

    with pytest.raises(knockout_service.KnockoutError) as excinfo:
        knockout_service.undo_knockout(conn, tid)

    assert excinfo.value.code == 409
    assert "尚未生成淘汰赛" in str(excinfo.value)


def test_undo_then_revise_group_score_changes_qualifier_and_regeneration(conn):
    """A1 核心恢复流程：撤销 → 修正小组比分 → 排名改变 → 重新生成签表。"""
    tid = _build(conn, players=16, group_count=4, qualify=2, table_count=4)
    _play_all_group_matches(conn, tid)
    knockout_service.generate_knockout(conn, tid)

    rankings = rankings_service.get_rankings(conn, tid)
    group = rankings[0]
    qualified_before = [e["player_id"] for e in group["entries"] if e["qualified"]]
    assert len(qualified_before) == 2
    runner_up = qualified_before[1]
    third = next(e["player_id"] for e in group["entries"] if not e["qualified"])

    target = next(
        match
        for match in repo.list_matches(conn, tid, stage="GROUP", group_id=group["group_id"])
        if {match["entry_a_id"], match["entry_b_id"]} == {runner_up, third}
    )

    undo = knockout_service.undo_knockout(conn, tid)
    assert undo["deleted_matches"] == 7
    assert repo.get_tournament(conn, tid)["stage"] == "GROUP_STAGE"

    # 修正：让原先告负的一方获胜（原比分固定为 id 小者 2:0）
    scores_service.revise_score(conn, target["id"], 0, 2)

    rankings_after = rankings_service.get_rankings(conn, tid)
    qualified_after = [e["player_id"] for e in rankings_after[0]["entries"] if e["qualified"]]
    assert qualified_after != qualified_before
    assert third in qualified_after and runner_up not in qualified_after

    knockout_service.generate_knockout(conn, tid)
    first_round = [
        match for match in _knockout_matches(conn, tid) if match["round"] == 1
    ]
    bracket_entries = {
        entry_id
        for match in first_round
        for entry_id in (match["entry_a_id"], match["entry_b_id"])
    }
    assert third in bracket_entries and runner_up not in bracket_entries
    # 重新生成仍遵守已冻结的 4 组首尾交叉
    labels = _qualifier_labels(conn, tid)
    pairs = {
        frozenset((labels[m["entry_a_id"]], labels[m["entry_b_id"]]))
        for m in first_round
    }
    assert pairs == {
        frozenset({("A组", 1), ("D组", 2)}),
        frozenset({("C组", 1), ("B组", 2)}),
        frozenset({("B组", 1), ("C组", 2)}),
        frozenset({("D组", 1), ("A组", 2)}),
    }


# ------------------------------------------------------------------------ API

def _api_tournament(client, *, players=8, group_count=4, qualify=2, table_count=4):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "撤销 API 验收",
            "date": "2025-06-01",
            "table_count": table_count,
            "group_count": group_count,
            "qualify_per_group": qualify,
        },
    ).json()["id"]
    for index in range(players):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1:02d}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    return tid


def test_api_undo_knockout_roundtrip(client):
    tid = _api_tournament(client)
    matches = client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()
    for match in matches:
        winner = min(match["player_a_id"], match["player_b_id"])
        score_a, score_b = (2, 0) if winner == match["player_a_id"] else (0, 2)
        client.post(
            f"/api/matches/{match['id']}/score",
            json={"player_a_score": score_a, "player_b_score": score_b},
        )

    generated = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert generated.status_code == 200
    assert len(generated.json()["rounds"][0]["matches"]) == 4

    resp = client.post(f"/api/tournaments/{tid}/knockout/undo")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_matches"] == 7
    assert body["deleted_main_matches"] == 7
    assert body["tournament"]["stage"] == "GROUP_STAGE"

    tree = client.get(f"/api/tournaments/{tid}/knockout").json()
    assert tree["rounds"] == []
    assert client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()

    # 撤销后可以重新生成，且对阵仍是冻结规则
    assert client.post(f"/api/tournaments/{tid}/generate-knockout").status_code == 200


def test_api_undo_knockout_conflicts(client):
    tid = _api_tournament(client)
    assert client.post(f"/api/tournaments/{tid}/knockout/undo").status_code == 409
    assert client.post("/api/tournaments/999999/knockout/undo").status_code == 404

    matches = client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()
    for match in matches:
        client.post(
            f"/api/matches/{match['id']}/score",
            json={"player_a_score": 2, "player_b_score": 0},
        )
    client.post(f"/api/tournaments/{tid}/generate-knockout")
    first = client.get(f"/api/tournaments/{tid}/knockout").json()["rounds"][0]["matches"][0]
    client.post(f"/api/matches/{first['id']}/score", json={"player_a_score": 2, "player_b_score": 0})

    resp = client.post(f"/api/tournaments/{tid}/knockout/undo")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "淘汰赛已经开始，不能直接撤销。"
    assert client.get(f"/api/tournaments/{tid}/knockout").json()["rounds"] != []
