"""D5A：报名确认入赛的原子性、并发与回滚边界。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from app import db as db_module
from app import repository as repo
from app.models import TournamentStage
from app.services import players as players_service
from app.services import registrations as registrations_service


TOURNAMENT_PAYLOAD = {
    "name": "D5A 报名确认赛事",
    "date": "2026-09-22",
    "table_count": 2,
    "group_count": 2,
    "qualify_per_group": 1,
    "registration_enabled": True,
}
REGISTRATION_PAYLOAD = {
    "name": "待确认选手",
    "affiliation": "自动化学院",
    "contact": "13900000000",
    "rating_points": 1725,
}
RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}


def _create_tournament(client, name: str = TOURNAMENT_PAYLOAD["name"]) -> dict:
    response = client.post(
        "/api/tournaments", json={**TOURNAMENT_PAYLOAD, "name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _submit_registration(client, tournament_id: int) -> dict:
    response = client.post(
        f"/api/tournaments/{tournament_id}/registrations",
        json=REGISTRATION_PAYLOAD,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_confirm_creates_one_player_and_keeps_traceable_link(client, conn):
    tournament = _create_tournament(client)
    submitted = _submit_registration(client, tournament["id"])
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    response = client.post(
        f"/api/tournaments/{tournament['id']}/registrations/"
        f"{submitted['registration_id']}/confirm"
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["registration"]["status"] == "CONFIRMED"
    assert result["registration"]["confirmed_player_id"] == result["player"]["id"]
    assert result["registration"]["confirmed_by_user_id"] == owner_id
    assert result["player"]["name"] == REGISTRATION_PAYLOAD["name"]
    assert result["player"]["college"] == REGISTRATION_PAYLOAD["affiliation"]
    assert result["player"]["rating_points"] == REGISTRATION_PAYLOAD["rating_points"]

    assert len(repo.list_players(conn, tournament["id"])) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM entries WHERE tournament_id = ?", (tournament["id"],)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM matches WHERE tournament_id = ?", (tournament["id"],)
    ).fetchone()[0] == 0

    repeated = client.post(
        f"/api/tournaments/{tournament['id']}/registrations/"
        f"{submitted['registration_id']}/confirm"
    )
    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["detail"]["code"] == "REGISTRATION_ALREADY_PROCESSED"
    assert len(repo.list_players(conn, tournament["id"])) == 1

    delete_player = client.delete(
        f"/api/tournaments/{tournament['id']}/players/{result['player']['id']}"
    )
    assert delete_player.status_code == 409, delete_player.text
    assert delete_player.json()["detail"] == "该选手由已确认报名创建，不能直接删除"
    assert repo.get_player(conn, result["player"]["id"]) is not None


def test_confirm_is_rejected_for_other_tournament_and_locked_roster(client, conn):
    first = _create_tournament(client, "确认归属 A")
    second = _create_tournament(client, "确认归属 B")
    submitted = _submit_registration(client, first["id"])

    wrong_tournament = client.post(
        f"/api/tournaments/{second['id']}/registrations/"
        f"{submitted['registration_id']}/confirm"
    )
    assert wrong_tournament.status_code == 404, wrong_tournament.text
    assert wrong_tournament.json()["detail"] == (
        {"code": "REGISTRATION_NOT_FOUND", "message": "报名记录不存在"}
    )

    repo.update_tournament_stage(conn, first["id"], TournamentStage.GROUP_STAGE.value)
    conn.commit()
    locked = client.post(
        f"/api/tournaments/{first['id']}/registrations/"
        f"{submitted['registration_id']}/confirm"
    )
    assert locked.status_code == 409, locked.text
    assert locked.json()["detail"]["code"] == "ROSTER_LOCKED"
    assert repo.list_players(conn, first["id"]) == []


def test_confirm_rejects_capacity_and_rolls_back_internal_failure(
    client, conn, monkeypatch
):
    tournament = _create_tournament(client, "确认容量回滚")
    submitted = _submit_registration(client, tournament["id"])
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    monkeypatch.setattr(players_service, "MAX_PLAYERS_PER_TOURNAMENT", 0)
    capacity = client.post(
        f"/api/tournaments/{tournament['id']}/registrations/"
        f"{submitted['registration_id']}/confirm"
    )
    assert capacity.status_code == 409, capacity.text
    assert capacity.json()["detail"]["code"] == "ROSTER_LOCKED"
    assert repo.list_players(conn, tournament["id"]) == []

    monkeypatch.setattr(players_service, "MAX_PLAYERS_PER_TOURNAMENT", 120)

    def fail_after_player_insert(*_args, **_kwargs):
        raise RuntimeError("模拟确认持久化失败")

    monkeypatch.setattr(repo, "confirm_registration", fail_after_player_insert)
    with pytest.raises(RuntimeError, match="模拟确认持久化失败"):
        registrations_service.confirm_registration(
            conn,
            tournament["id"],
            submitted["registration_id"],
            confirmed_by_user_id=owner_id,
        )

    assert repo.list_players(conn, tournament["id"]) == []
    persisted = repo.get_registration(conn, submitted["registration_id"])
    assert persisted["status"] == "PENDING"
    assert persisted["confirmed_player_id"] is None
    assert persisted["confirmed_at"] is None


def test_concurrent_confirm_serializes_and_creates_only_one_player(client, conn):
    tournament = _create_tournament(client, "确认并发赛事")
    submitted = _submit_registration(client, tournament["id"])
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    barrier = threading.Barrier(2)

    def confirm_once() -> tuple[str, object]:
        worker_conn = db_module.connect()
        try:
            barrier.wait(timeout=5)
            try:
                result = registrations_service.confirm_registration(
                    worker_conn,
                    tournament["id"],
                    submitted["registration_id"],
                    confirmed_by_user_id=owner_id,
                )
                return "ok", result
            except registrations_service.RegistrationError as exc:
                return "error", (exc.status_code, exc.error_code)
        finally:
            worker_conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm_once(), range(2)))

    assert sum(result[0] == "ok" for result in results) == 1
    errors = [result[1] for result in results if result[0] == "error"]
    assert len(errors) == 1
    assert errors[0] in {
        (409, "REGISTRATION_ALREADY_PROCESSED"),
        (409, "TRANSACTION_BUSY"),
    }
    assert len(repo.list_players(conn, tournament["id"])) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM registrations "
        "WHERE tournament_id = ? AND status = 'CONFIRMED'",
        (tournament["id"],),
    ).fetchone()[0] == 1


def test_confirm_respects_locked_team_roster(client, conn):
    tournament = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "name": "团体锁定报名确认",
            "event_type": "TEAM",
        },
    ).json()
    registration = repo.create_registration(
        conn,
        tournament["id"],
        name="团体报名",
        affiliation=None,
        contact=None,
        rating_points=1000,
    )
    conn.execute(
        "UPDATE tournaments SET roster_confirmed = 1, "
        "confirmed_at = datetime('now') WHERE id = ?",
        (tournament["id"],),
    )
    conn.commit()

    response = client.post(
        f"/api/tournaments/{tournament['id']}/registrations/"
        f"{registration['id']}/confirm"
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ROSTER_LOCKED"
    assert repo.list_players(conn, tournament["id"]) == []


def test_confirm_respects_locked_singles_roster(client, conn):
    tournament = _create_tournament(client, "单打名单确认后拒绝待审报名")
    submitted = _submit_registration(client, tournament["id"])
    conn.execute(
        "UPDATE tournaments SET roster_confirmed = 1, "
        "confirmed_at = datetime('now') WHERE id = ?",
        (tournament["id"],),
    )
    conn.commit()

    response = client.post(
        f"/api/tournaments/{tournament['id']}/registrations/"
        f"{submitted['registration_id']}/confirm"
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "ROSTER_LOCKED",
        "message": "参赛名单已确认，不能再修改运动员",
    }
    assert repo.list_players(conn, tournament["id"]) == []


def test_confirm_missing_tournament_and_registration_return_404(client):
    tournament = _create_tournament(client, "确认缺失资源")
    missing_tournament = client.post(
        f"/api/tournaments/999999/registrations/1/confirm"
    )
    assert missing_tournament.status_code == 404, missing_tournament.text
    assert missing_tournament.json()["detail"] == RESOURCE_NOT_FOUND

    missing_registration = client.post(
        f"/api/tournaments/{tournament['id']}/registrations/999999/confirm"
    )
    assert missing_registration.status_code == 404, missing_registration.text
    assert missing_registration.json()["detail"] == (
        {"code": "REGISTRATION_NOT_FOUND", "message": "报名记录不存在"}
    )
