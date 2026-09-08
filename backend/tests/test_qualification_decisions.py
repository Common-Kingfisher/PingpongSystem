"""人工晋级裁定：候选范围、审计留痕、排名生效及成绩变更失效。"""

import pytest

from app import repository as repo
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import qualification_decisions as decision_service
from app.services import rankings as rankings_service
from app.services import scores as scores_service


def _fully_tied_group(conn, qualify_per_group=1):
    tournament = repo.create_tournament(
        conn, "人工裁定测试", "2026-09-08", 2, 1, qualify_per_group
    )
    repo.create_tables_for_tournament(conn, tournament["id"], 2)
    for name in ("甲", "乙", "丙"):
        repo.add_player(conn, tournament["id"], name, None)
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])

    entries = sorted(repo.list_entries(conn, tournament["id"]), key=lambda item: item["id"])
    first, second, third = [entry["id"] for entry in entries]
    winner_by_pair = {
        frozenset((first, second)): first,
        frozenset((second, third)): second,
        frozenset((first, third)): third,
    }
    for match in repo.list_matches(conn, tournament["id"]):
        side_a, side_b = match["entry_a_id"], match["entry_b_id"]
        winner = winner_by_pair[frozenset((side_a, side_b))]
        score = (2, 0) if winner == side_a else (0, 2)
        scores_service.record_score(conn, match["id"], *score)
        games = [(11, 5), (11, 5)] if winner == side_a else [(5, 11), (5, 11)]
        scores_service.revise_score(conn, match["id"], None, None, games=games)
    group_id = repo.list_groups(conn, tournament["id"])[0]["id"]
    return tournament["id"], group_id, [entry["id"] for entry in entries]


def test_manual_decision_resolves_only_cutoff_and_keeps_audit(conn):
    tid, group_id, entry_ids = _fully_tied_group(conn)
    before = rankings_service.get_rankings(conn, tid)[0]
    assert before["ambiguous_qualification"] is True
    assert before["needs_point_scores"] is False
    assert set(before["manual_candidate_entry_ids"]) == set(entry_ids)
    assert before["manual_slots_remaining"] == 1

    decision = decision_service.create_decision(
        conn, tid, group_id, [entry_ids[1]], "裁判长抽签决定", "主裁判王老师"
    )
    after = rankings_service.get_rankings(conn, tid)[0]

    assert decision["active"] is True
    assert after["ambiguous_qualification"] is False
    assert after["manually_resolved"] is True
    assert after["qualification_decision"]["reason"] == "裁判长抽签决定"
    assert [item["player_id"] for item in after["entries"] if item["qualified"]] == [entry_ids[1]]


def test_manual_decision_rejects_wrong_count_and_outsider(conn):
    tid, group_id, entry_ids = _fully_tied_group(conn)
    with pytest.raises(decision_service.QualificationDecisionError) as count_error:
        decision_service.create_decision(conn, tid, group_id, entry_ids[:2], "人数错误", "主裁判")
    assert count_error.value.code == 422

    with pytest.raises(decision_service.QualificationDecisionError) as outsider_error:
        decision_service.create_decision(conn, tid, group_id, [99999], "范围错误", "主裁判")
    assert outsider_error.value.code == 422


def test_score_change_invalidates_manual_decision(conn):
    tid, group_id, entry_ids = _fully_tied_group(conn)
    decision_service.create_decision(conn, tid, group_id, [entry_ids[0]], "现场抽签", "主裁判")
    match = repo.list_matches(conn, tid)[0]

    scores_service.revise_score(conn, match["id"], 2, 1)

    history = decision_service.list_decisions(conn, tid, group_id)
    assert history[0]["active"] is False
    assert "相关比赛结果已修改" in history[0]["invalidation_reason"]
    assert rankings_service.get_rankings(conn, tid)[0]["manually_resolved"] is False


def test_revoke_manual_decision_records_operator_and_reason(conn):
    tid, group_id, entry_ids = _fully_tied_group(conn)
    decision_service.create_decision(conn, tid, group_id, [entry_ids[0]], "现场抽签", "主裁判甲")

    revoked = decision_service.revoke_decision(conn, tid, group_id, "发现记录错误", "主裁判乙")

    assert revoked["active"] is False
    assert revoked["invalidation_reason"] == "由 主裁判乙 撤销：发现记录错误"


def test_revoke_is_blocked_after_knockout_generation(conn):
    tid, group_id, entry_ids = _fully_tied_group(conn, qualify_per_group=2)
    decision_service.create_decision(
        conn, tid, group_id, entry_ids[:2], "现场抽签", "主裁判甲"
    )
    knockout_service.generate_knockout(conn, tid)

    with pytest.raises(
        decision_service.QualificationDecisionError, match="淘汰赛已生成"
    ):
        decision_service.revoke_decision(
            conn, tid, group_id, "发现记录错误", "主裁判乙"
        )

    active = repo.get_active_qualification_decision(conn, group_id)
    assert active is not None
    assert active["invalidated_at"] is None


def test_manual_decision_http_contract(client):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "裁定接口测试", "date": "2026-09-08", "table_count": 2,
            "group_count": 1, "qualify_per_group": 1,
        },
    ).json()["id"]
    for name in ("甲", "乙", "丙"):
        assert client.post(f"/api/tournaments/{tid}/players", json={"name": name}).status_code == 201
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200
    assert client.post(f"/api/tournaments/{tid}/generate-group-matches").status_code == 200
    matches = client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()
    entry_ids = sorted({side for match in matches for side in (match["entry_a_id"], match["entry_b_id"])})
    first, second, third = entry_ids
    winner_by_pair = {
        frozenset((first, second)): first,
        frozenset((second, third)): second,
        frozenset((first, third)): third,
    }
    for match in matches:
        a, b = match["entry_a_id"], match["entry_b_id"]
        winner = winner_by_pair[frozenset((a, b))]
        score = (2, 0) if winner == a else (0, 2)
        assert client.post(
            f"/api/matches/{match['id']}/score",
            json={"player_a_score": score[0], "player_b_score": score[1]},
        ).status_code == 200
        games = (
            [{"side_a_score": 11, "side_b_score": 5}] * 2
            if winner == a else [{"side_a_score": 5, "side_b_score": 11}] * 2
        )
        assert client.post(
            f"/api/matches/{match['id']}/revise-score",
            json={"games": games},
        ).status_code == 200

    ranking = client.get(f"/api/tournaments/{tid}/rankings").json()["rankings"][0]
    assert ranking["ambiguous_qualification"] is True
    group_id = ranking["group_id"]
    selected = ranking["manual_candidate_entry_ids"][0]
    created = client.post(
        f"/api/tournaments/{tid}/groups/{group_id}/qualification-decision",
        json={
            "selected_entry_ids": [selected],
            "reason": "组委会现场抽签", "operator_name": "裁判长",
        },
    )
    assert created.status_code == 201
    assert created.json()["active"] is True
    resolved = client.get(f"/api/tournaments/{tid}/rankings").json()["rankings"][0]
    assert resolved["manually_resolved"] is True
    assert resolved["ambiguous_qualification"] is False
    history = client.get(
        f"/api/tournaments/{tid}/groups/{group_id}/qualification-decisions"
    )
    assert history.status_code == 200
    assert history.json()[0]["operator_name"] == "裁判长"

    changed = client.patch(
        f"/api/tournaments/{tid}/groups/{group_id}/qualification",
        json={"qualify_count": 2},
    )
    assert changed.status_code == 200
    after_change = client.get(f"/api/tournaments/{tid}/rankings").json()["rankings"][0]
    assert after_change["manually_resolved"] is False
    history_after = client.get(
        f"/api/tournaments/{tid}/groups/{group_id}/qualification-decisions"
    ).json()
    assert history_after[0]["active"] is False
    assert history_after[0]["invalidation_reason"] == "小组出线人数已修改"
