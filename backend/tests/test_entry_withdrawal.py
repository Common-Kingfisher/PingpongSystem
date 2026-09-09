"""整赛事退赛与单场赛果边界。"""

from app import repository as repo
from app.models import MatchStatus, ResultType, TableStatus
from app.services import entries as entry_service
from app.services import groups as groups_service
from app.services import matches as matches_service
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
