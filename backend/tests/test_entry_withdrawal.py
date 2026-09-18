"""整赛事退赛与单场赛果边界。"""

from app import repository as repo
from app.models import MatchStatus, ResultType, TableStatus
from app.services import entries as entry_service
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import qualification_decisions as decision_service
from app.services import rankings as rankings_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


def _group_event(conn):
    tournament = repo.create_tournament(conn, "退赛测试", "2026-09-09", 2, 1, 2)
    repo.create_tables_for_tournament(conn, tournament["id"], 2)
    for index in range(4):
        repo.add_player(conn, tournament["id"], f"参赛者{index + 1}", "体育学院")
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])
    return tournament["id"], repo.list_entries(conn, tournament["id"])


def test_withdrawal_preserves_finished_and_forfeits_unfinished(conn):
    tournament_id, entries = _group_event(conn)
    withdrawn_id = entries[0]["id"]
    involving = [
        match for match in repo.list_matches(conn, tournament_id)
        if withdrawn_id in (match["entry_a_id"], match["entry_b_id"])
    ]

    first = involving[0]
    score = (2, 0) if first["entry_a_id"] == withdrawn_id else (0, 2)
    scores_service.record_score(conn, first["id"], *score)
    table = repo.list_tables(conn, tournament_id)[0]
    scheduling_service.assign_table(conn, involving[1]["id"], table["id"])
    conn.execute("UPDATE matches SET started_at = '2026-09-01 10:00:00' WHERE id = ?", (involving[1]["id"],))
    first_before = repo.get_match(conn, first["id"])

    entry, affected, preserved = entry_service.withdraw_from_tournament(
        conn, tournament_id, withdrawn_id, "李主裁", "运动员伤病退出"
    )

    assert entry["status"] == "WITHDRAWN"
    assert entry["withdrawn_by"] == "李主裁"
    assert preserved == 1
    assert set(affected) == {match["id"] for match in involving[1:]}
    assert repo.get_table(conn, table["id"])["status"] == TableStatus.FREE.value
    assert repo.get_match(conn, first["id"])["result_type"] == ResultType.NORMAL.value
    for match_id in affected:
        match = repo.get_match(conn, match_id)
        assert match["status"] == MatchStatus.FINISHED.value
        assert match["result_type"] == ResultType.FORFEIT.value
        assert match["forfeit_entry_id"] == withdrawn_id
        assert match["finished_at"]
        if match_id == involving[1]["id"]:
            assert match["started_at"] == "2026-09-01 10:00:00"
        # WAITING 直接因退赛完赛不要求伪造 started_at；A2 时间语义合入后应保持为空。
    assert repo.get_match(conn, first["id"])["finished_at"] == first_before["finished_at"]

    ranking = rankings_service.get_rankings(conn, tournament_id)[0]
    withdrawn = next(item for item in ranking["entries"] if item["player_id"] == withdrawn_id)
    assert withdrawn["entry_status"] == "WITHDRAWN"
    assert withdrawn["qualified"] is False


def test_withdrawal_api_requires_operator_and_reason(client):
    tournament_id = client.post(
        "/api/tournaments",
        json={"name": "退赛接口", "date": "2026-09-09", "table_count": 1, "group_count": 1, "qualify_per_group": 1},
    ).json()["id"]
    for name in ("甲", "乙"):
        client.post(f"/api/tournaments/{tournament_id}/players", json={"name": name})
    client.post(f"/api/tournaments/{tournament_id}/auto-group")
    client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")
    entry_id = client.get(f"/api/tournaments/{tournament_id}/entries").json()[0]["id"]

    invalid = client.post(
        f"/api/tournaments/{tournament_id}/entries/{entry_id}/withdraw",
        json={"operator_name": "", "reason": ""},
    )
    assert invalid.status_code == 422

    response = client.post(
        f"/api/tournaments/{tournament_id}/entries/{entry_id}/withdraw",
        json={"operator_name": "李主裁", "reason": "现场确认退赛"},
    )
    assert response.status_code == 200
    assert response.json()["entry"]["status"] == "WITHDRAWN"
    assert response.json()["affected_match_ids"]


def test_withdrawal_invalidates_manual_qualification_and_cannot_requalify(conn):
    tournament = repo.create_tournament(conn, "退赛裁定失效", "2026-09-09", 2, 2, 1)
    repo.create_tables_for_tournament(conn, tournament["id"], 2)
    for name in ("甲", "乙", "丙", "丁", "戊"):
        repo.add_player(conn, tournament["id"], name, "体育学院")
    _, entries = entry_service.confirm_roster(conn, tournament["id"])
    entries = sorted(entries, key=lambda item: item["id"])
    group_a = repo.create_group(conn, tournament["id"], "A组", 0)
    group_b = repo.create_group(conn, tournament["id"], "B组", 1)
    for entry in entries[:3]:
        repo.set_entry_group(conn, entry["id"], group_a["id"])
        repo.set_player_group(conn, entry["members"][0]["player_id"], group_a["id"])
    for entry in entries[3:]:
        repo.set_entry_group(conn, entry["id"], group_b["id"])
        repo.set_player_group(conn, entry["members"][0]["player_id"], group_b["id"])
    conn.commit()
    matches_service.generate_group_matches(conn, tournament["id"])

    first, second, third = [entry["id"] for entry in entries[:3]]
    winner_by_pair = {
        frozenset((first, second)): first,
        frozenset((second, third)): second,
        frozenset((first, third)): third,
    }
    for match in repo.list_matches(conn, tournament["id"]):
        a, b = match["entry_a_id"], match["entry_b_id"]
        winner = winner_by_pair.get(frozenset((a, b)), min(a, b))
        score = (2, 0) if winner == a else (0, 2)
        scores_service.record_score(conn, match["id"], *score)
        games = [(11, 5), (11, 5)] if winner == a else [(5, 11), (5, 11)]
        scores_service.revise_score(conn, match["id"], None, None, games=games)

    before = rankings_service.get_rankings(conn, tournament["id"])[0]
    assert before["ambiguous_qualification"] is True
    decision_service.create_decision(
        conn, tournament["id"], group_a["id"], [first], "现场抽签", "李主裁"
    )

    entry_service.withdraw_from_tournament(
        conn, tournament["id"], first, "李主裁", "运动员退出整个赛事"
    )
    assert repo.get_active_qualification_decision(conn, group_a["id"]) is None
    after = rankings_service.get_rankings(conn, tournament["id"])[0]
    withdrawn = next(item for item in after["entries"] if item["player_id"] == first)
    assert withdrawn["qualified"] is False
    assert first not in after["manual_candidate_entry_ids"]
    if after["ambiguous_qualification"]:
        decision_service.create_decision(
            conn,
            tournament["id"],
            group_a["id"],
            [after["manual_candidate_entry_ids"][0]],
            "退赛后重新裁定",
            "李主裁",
        )

    tree = knockout_service.generate_knockout(conn, tournament["id"])
    first_round_ids = {
        side["id"]
        for match in tree["rounds"][0]["matches"]
        for side in (match["player_a"], match["player_b"])
        if side is not None
    }
    assert first not in first_round_ids


def test_withdrawn_waiting_slot_forfeits_when_opponent_arrives(conn):
    tournament = repo.create_tournament(conn, "淘汰签退赛传播", "2026-09-09", 2, 2, 2)
    repo.create_tables_for_tournament(conn, tournament["id"], 2)
    for name in ("甲", "乙", "丙", "丁"):
        repo.add_player(conn, tournament["id"], name, "体育学院")
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])
    for match in repo.list_matches(conn, tournament["id"]):
        scores_service.record_score(conn, match["id"], 2, 0)

    knockout_service.generate_knockout(conn, tournament["id"])
    semifinals = sorted(
        (match for match in repo.list_matches(conn, tournament["id"])
         if match["stage"] == "KNOCKOUT" and match["round"] == 1),
        key=lambda item: item["match_index"],
    )
    first_result = scores_service.record_score(conn, semifinals[0]["id"], 2, 0)
    withdrawn_id = first_result["winner_entry_id"]
    final = next(
        match for match in repo.list_matches(conn, tournament["id"])
        if match["stage"] == "KNOCKOUT" and match["round"] == 2
    )
    assert withdrawn_id in (final["entry_a_id"], final["entry_b_id"])
    assert None in (final["entry_a_id"], final["entry_b_id"])

    entry_service.withdraw_from_tournament(
        conn, tournament["id"], withdrawn_id, "李主裁", "运动员退出整个赛事"
    )
    scores_service.record_score(conn, semifinals[1]["id"], 2, 0)

    final = repo.get_match(conn, final["id"])
    assert final["status"] == MatchStatus.FINISHED.value
    assert final["result_type"] == ResultType.FORFEIT.value
    assert final["forfeit_entry_id"] == withdrawn_id
    assert final["winner_entry_id"] != withdrawn_id
    assert final["finished_at"]
    # 对手后来进入空槽触发自动完赛时，finished_at 是事实；started_at 不应成为前置条件。


def test_withdrawn_semifinal_loser_forfeits_new_bronze_match(conn):
    tournament = repo.create_tournament(
        conn,
        "季军赛退赛传播",
        "2026-09-09",
        2,
        2,
        2,
        bronze_mode="BRONZE_MATCH",
    )
    repo.create_tables_for_tournament(conn, tournament["id"], 2)
    for name in ("甲", "乙", "丙", "丁"):
        repo.add_player(conn, tournament["id"], name, "体育学院")
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])
    for match in repo.list_matches(conn, tournament["id"]):
        scores_service.record_score(conn, match["id"], 2, 0)

    knockout_service.generate_knockout(conn, tournament["id"])
    semifinals = sorted(
        (
            match
            for match in repo.list_matches(conn, tournament["id"])
            if match["stage"] == "KNOCKOUT"
            and match["bracket"] == "MAIN"
            and match["round"] == 1
        ),
        key=lambda item: item["match_index"],
    )
    # 先结束另一场半决赛；季军赛要等两场半决赛都有结果后才会动态创建。
    scores_service.record_score(conn, semifinals[1]["id"], 2, 0)
    withdrawn_id = semifinals[0]["entry_a_id"]

    entry_service.withdraw_from_tournament(
        conn,
        tournament["id"],
        withdrawn_id,
        "李主裁",
        "运动员退出整个赛事",
    )

    bronze = next(
        match
        for match in repo.list_matches(conn, tournament["id"])
        if match.get("placement_min") == 3 and match.get("placement_max") == 4
    )
    assert withdrawn_id in (bronze["entry_a_id"], bronze["entry_b_id"])
    assert bronze["status"] == MatchStatus.FINISHED.value
    assert bronze["result_type"] == ResultType.FORFEIT.value
    assert bronze["forfeit_entry_id"] == withdrawn_id
    assert bronze["winner_entry_id"] != withdrawn_id
    assert bronze["finished_at"]
