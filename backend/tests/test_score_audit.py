"""比赛时间与比分不可覆盖审计回归测试。"""

from app import repository as repo
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import scheduling as scheduling_service


def _match_and_table(conn):
    tournament = repo.create_tournament(conn, "审计测试", "2026-09-09", 1, 1, 1)
    repo.create_tables_for_tournament(conn, tournament["id"], 1)
    for name in ("陈启航", "林知远"):
        repo.add_player(conn, tournament["id"], name, "测试学院")
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])
    return repo.list_matches(conn, tournament["id"])[0], repo.list_tables(conn, tournament["id"])[0]


def test_started_at_is_first_assignment_time(conn):
    match, table = _match_and_table(conn)
    started = scheduling_service.assign_table(conn, match["id"], table["id"])["started_at"]
    assert started is not None

    scheduling_service.release_match(conn, match["id"])
    reassigned = scheduling_service.assign_table(conn, match["id"], table["id"])
    assert reassigned["started_at"] == started


def test_revision_requires_identity_and_preserves_finish_time(client):
    tournament_id = client.post(
        "/api/tournaments",
        json={"name": "审计接口", "date": "2026-09-09", "table_count": 1, "group_count": 1, "qualify_per_group": 1},
    ).json()["id"]
    for name in ("陈启航", "林知远"):
        client.post(f"/api/tournaments/{tournament_id}/players", json={"name": name})
    client.post(f"/api/tournaments/{tournament_id}/auto-group")
    client.post(f"/api/tournaments/{tournament_id}/generate-group-matches")
    match_id = client.get(f"/api/tournaments/{tournament_id}/matches").json()[0]["id"]

    recorded = client.post(
        f"/api/matches/{match_id}/score",
        json={"player_a_score": 2, "player_b_score": 0, "operator_name": "王主裁"},
    ).json()
    assert recorded["started_at"] is not None
    assert recorded["finished_at"] is not None

    missing_audit = client.post(
        f"/api/matches/{match_id}/revise-score",
        json={"player_a_score": 2, "player_b_score": 1},
    )
    assert missing_audit.status_code == 422

    revised = client.post(
        f"/api/matches/{match_id}/revise-score",
        json={
            "player_a_score": 2,
            "player_b_score": 1,
            "operator_name": "王主裁",
            "change_reason": "纸质记分表复核",
            "request_id": "42e12ef0-f39c-46d0-a76c-f45b4f11df2c",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["finished_at"] == recorded["finished_at"]

    audits = client.get(f"/api/matches/{match_id}/score-audits").json()
    assert len(audits) == 2
    assert audits[0]["action"] == "REVISE"
    assert audits[0]["operator_name"] == "王主裁"
    assert audits[0]["before_snapshot"]["player_b_score"] == 0
    assert audits[0]["after_snapshot"]["player_b_score"] == 1

    replay = client.post(
        f"/api/matches/{match_id}/revise-score",
        json={
            "player_a_score": 2,
            "player_b_score": 1,
            "operator_name": "王主裁",
            "change_reason": "纸质记分表复核",
            "request_id": "42e12ef0-f39c-46d0-a76c-f45b4f11df2c",
        },
    )
    assert replay.status_code == 200
    assert len(client.get(f"/api/matches/{match_id}/score-audits").json()) == 2


def test_revision_openapi_marks_audit_fields_required(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ScoreRevisionRequest"]
    assert {"operator_name", "change_reason"}.issubset(schema["required"])


def test_revision_contract_requires_audit_fields(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ScoreRevisionRequest"]
    assert {"operator_name", "change_reason"}.issubset(schema["required"])
