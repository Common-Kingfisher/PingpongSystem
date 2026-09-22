"""D4A：Tournament 赛制配置持久化、更新与 B Handler 接线。"""

from __future__ import annotations

import json

import pytest

from app import db as db_module
from app import repository as repo
from app.models import SystemRole, TournamentRole
from app.security import hash_password
from app.services import auth as auth_service
from app.services import formats as formats_service
from app.services import tournaments as tournament_service


PASSWORD = "StrongPassword123"
RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
TOURNAMENT_PAYLOAD = {
    "name": "D4A 赛制配置赛事",
    "date": "2026-09-22",
    "table_count": 2,
    "group_count": 1,
    "qualify_per_group": 1,
}
SINGLE_ELIMINATION_CONFIG = {"draw_seed": 7}
SEMANTIC_INVALID_CONFIGS = [
    ("ROUND_ROBIN", {"draw_seed": 7}, "未知配置"),
    ("GROUP_KNOCKOUT", {"bracket_size": 8}, "未知配置"),
    ("GROUP_KNOCKOUT", {"note": "武汉大学"}, "未知配置"),
    ("SINGLE_ELIMINATION", {"draw_seed": True}, "draw_seed 必须是整数"),
    ("SINGLE_ELIMINATION", {"draw_seed": "7"}, "draw_seed 必须是整数"),
    ("SINGLE_ELIMINATION", {"unknown": 1}, "未知配置"),
]


def _encoded_config(rule_config: dict) -> str:
    return json.dumps(
        rule_config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_tournament(client, **overrides) -> dict:
    response = client.post(
        "/api/tournaments",
        json={**TOURNAMENT_PAYLOAD, **overrides},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_user(
    conn,
    username: str,
    system_role: SystemRole = SystemRole.EVENT_ADMIN,
) -> tuple[dict, str]:
    user = repo.create_user(
        conn,
        username,
        f"{username} 显示名",
        hash_password(PASSWORD, iterations=1000),
        system_role.value,
    )
    conn.commit()
    token = auth_service.login(conn, username, PASSWORD)["access_token"]
    return user, token


def _grant(
    conn,
    tournament_id: int,
    user_id: int,
    role: TournamentRole,
) -> None:
    repo.upsert_tournament_admin(
        conn,
        tournament_id,
        user_id,
        role.value,
        created_by_user_id=1,
    )
    conn.commit()


def _raw_format(conn, tournament_id: int) -> tuple:
    row = conn.execute(
        "SELECT format_code, rule_config, rule_version FROM tournaments WHERE id = ?",
        (tournament_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _assert_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == RESOURCE_NOT_FOUND


def test_create_with_group_knockout_persists_and_round_trips(client, conn):
    tournament = _create_tournament(
        client,
        format_code="GROUP_KNOCKOUT",
        rule_config={},
    )

    assert tournament["format_code"] == "GROUP_KNOCKOUT"
    assert tournament["rule_version"] == 1
    assert tournament["rule_config"] == {}
    raw = _raw_format(conn, tournament["id"])
    assert raw == (
        "GROUP_KNOCKOUT",
        "{}",
        1,
    )

    restart_conn = db_module.connect()
    try:
        persisted = repo.get_tournament(restart_conn, tournament["id"])
    finally:
        restart_conn.close()
    assert persisted is not None
    assert persisted["format_code"] == "GROUP_KNOCKOUT"
    assert persisted["rule_version"] == 1
    assert persisted["rule_config"] == {}
    handler = formats_service.resolve_format_handler(persisted["format_code"])
    assert handler.format_code == formats_service.GROUP_KNOCKOUT

    detail = client.get(f"/api/tournaments/{tournament['id']}")
    assert detail.status_code == 200
    assert detail.json()["rule_config"] == {}
    listed = client.get("/api/tournaments").json()
    assert listed[0]["format_code"] == "GROUP_KNOCKOUT"
    assert listed[0]["rule_version"] == 1
    assert listed[0]["rule_config"] == {}


def test_create_without_format_keeps_legacy_null_contract(client, conn):
    tournament = _create_tournament(client)

    assert tournament["format_code"] is None
    assert tournament["rule_version"] is None
    assert tournament["rule_config"] == {}
    assert _raw_format(conn, tournament["id"]) == (None, None, None)

    persisted = repo.get_tournament(conn, tournament["id"])
    assert persisted is not None
    assert persisted["format_code"] is None
    assert persisted["rule_version"] is None
    assert persisted["rule_config"] == {}


def test_create_rule_config_without_format_is_rejected(client, conn):
    response = client.post(
        "/api/tournaments",
        json={**TOURNAMENT_PAYLOAD, "rule_config": {"extra": 1}},
    )

    assert response.status_code == 422, response.text
    assert "未指定 format_code" in response.text
    assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("format_code", "rule_config"),
    [
        ("ROUND_ROBIN", {}),
        ("SINGLE_ELIMINATION", {}),
        ("SINGLE_ELIMINATION", SINGLE_ELIMINATION_CONFIG),
        ("GROUP_KNOCKOUT", {}),
    ],
)
def test_create_registered_handler_persists_supported_config(
    client,
    conn,
    format_code: str,
    rule_config: dict,
):
    response = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "name": f"创建赛制-{format_code}",
            "format_code": format_code,
            "rule_config": rule_config,
        },
    )

    assert response.status_code == 201, response.text
    tournament = response.json()
    assert tournament["format_code"] == format_code
    assert tournament["rule_config"] == rule_config
    assert tournament["rule_version"] == 1
    assert _raw_format(conn, tournament["id"]) == (
        format_code,
        _encoded_config(rule_config),
        1,
    )
    assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 1


def test_create_unknown_format_and_non_object_config_are_rejected(client, conn):
    unknown = client.post(
        "/api/tournaments",
        json={**TOURNAMENT_PAYLOAD, "format_code": "SINGLE_ELIM"},
    )
    assert unknown.status_code == 422, unknown.text

    non_object = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "format_code": "GROUP_KNOCKOUT",
            "rule_config": [1, 2, 3],
        },
    )
    assert non_object.status_code == 422, non_object.text
    assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("format_code", "rule_config", "error_message"),
    SEMANTIC_INVALID_CONFIGS,
)
def test_create_semantic_invalid_config_rolls_back_tournament(
    client,
    conn,
    format_code: str,
    rule_config: dict,
    error_message: str,
):
    response = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "format_code": format_code,
            "rule_config": rule_config,
        },
    )

    assert response.status_code == 422, response.text
    assert error_message in response.text
    assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 0



def test_update_format_config_api_rejects_client_rule_version(client, conn):
    tournament = _create_tournament(client)

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={
            "format_code": "GROUP_KNOCKOUT",
            "rule_config": {},
            "rule_version": 99,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["format_code"] == "GROUP_KNOCKOUT"
    assert response.json()["rule_version"] == 1
    assert response.json()["rule_config"] == {}
    assert _raw_format(conn, tournament["id"]) == (
        "GROUP_KNOCKOUT",
        "{}",
        1,
    )


def test_update_non_object_and_non_finite_config_is_atomic(client, conn):
    tournament = _create_tournament(client)
    before = _raw_format(conn, tournament["id"])

    non_object = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": "GROUP_KNOCKOUT", "rule_config": ["not", "object"]},
    )
    assert non_object.status_code == 422, non_object.text
    assert _raw_format(conn, tournament["id"]) == before

    with pytest.raises(tournament_service.TournamentFormatError) as exc_info:
        tournament_service.update_format_config(
            conn,
            tournament["id"],
            "GROUP_KNOCKOUT",
            {"value": float("nan")},
        )
    assert exc_info.value.code == 422
    assert _raw_format(conn, tournament["id"]) == before


@pytest.mark.parametrize(
    ("format_code", "rule_config"),
    [
        ("ROUND_ROBIN", {}),
        ("SINGLE_ELIMINATION", {}),
        ("SINGLE_ELIMINATION", SINGLE_ELIMINATION_CONFIG),
        ("GROUP_KNOCKOUT", {}),
    ],
)
def test_update_supported_format_persists(
    client,
    conn,
    format_code: str,
    rule_config: dict,
):
    tournament = _create_tournament(client)
    before = _raw_format(conn, tournament["id"])
    assert before == (None, None, None)

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": format_code, "rule_config": rule_config},
    )

    assert response.status_code == 200, response.text
    assert response.json()["format_code"] == format_code
    assert response.json()["rule_config"] == rule_config
    assert response.json()["rule_version"] == 1
    assert _raw_format(conn, tournament["id"]) == (
        format_code,
        _encoded_config(rule_config),
        1,
    )


@pytest.mark.parametrize(
    ("format_code", "rule_config", "error_message"),
    SEMANTIC_INVALID_CONFIGS,
)
def test_update_semantic_invalid_config_rolls_back_all_three_fields(
    client,
    conn,
    format_code: str,
    rule_config: dict,
    error_message: str,
):
    tournament = _create_tournament(client)
    before = _raw_format(conn, tournament["id"])
    assert before == (None, None, None)

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": format_code, "rule_config": rule_config},
    )

    assert response.status_code == 422, response.text
    assert error_message in response.text
    assert _raw_format(conn, tournament["id"]) == before



def test_update_unknown_format_is_rejected(client, conn):
    tournament = _create_tournament(client)
    before = _raw_format(conn, tournament["id"])

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": "SINGLE_ELIM", "rule_config": {}},
    )

    assert response.status_code == 422, response.text
    assert _raw_format(conn, tournament["id"]) == before


def test_update_permissions_match_tournament_write_matrix(client, conn):
    tournament = _create_tournament(client, name="D4A 权限矩阵赛事")
    payload = {"format_code": "GROUP_KNOCKOUT", "rule_config": {}}

    allowed_cases = (
        ("ADMIN", TournamentRole.ADMIN),
        ("OPERATOR", TournamentRole.OPERATOR),
    )
    for suffix, role in allowed_cases:
        _, token = _create_user(conn, f"d4a-{suffix.lower()}")
        _grant(conn, tournament["id"], repo.get_user_by_username(
            conn, f"d4a-{suffix.lower()}"
        )["id"], role)
        response = client.put(
            f"/api/tournaments/{tournament['id']}/format",
            json=payload,
            headers=_headers(token),
        )
        assert response.status_code == 200, response.text

    outsider, outsider_token = _create_user(conn, "d4a-outsider")
    viewer, viewer_token = _create_user(conn, "d4a-viewer")
    system_admin, system_admin_token = _create_user(
        conn,
        "d4a-system-admin",
        SystemRole.SYSTEM_ADMIN,
    )
    _grant(conn, tournament["id"], viewer["id"], TournamentRole.VIEWER)

    denied = (
        client.put(
            f"/api/tournaments/{tournament['id']}/format",
            json={"format_code": "ROUND_ROBIN", "rule_config": {}},
            headers=_headers(outsider_token),
        ),
        client.put(
            f"/api/tournaments/{tournament['id']}/format",
            json={"format_code": "ROUND_ROBIN", "rule_config": {}},
            headers=_headers(viewer_token),
        ),
        client.put(
            f"/api/tournaments/{tournament['id']}/format",
            json={"format_code": "ROUND_ROBIN", "rule_config": {}},
            headers=_headers(system_admin_token),
        ),
    )
    for response in denied:
        _assert_not_found(response)
    assert outsider["id"] != system_admin["id"]

    client.headers.pop("Authorization")
    unauthenticated = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": "ROUND_ROBIN", "rule_config": {}},
    )
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_update_rejected_after_match_exists(client, conn):
    tournament = _create_tournament(client)
    repo.create_match(
        conn,
        tournament["id"],
        "GROUP",
        None,
        1,
        1,
        None,
        None,
    )
    conn.commit()
    before = _raw_format(conn, tournament["id"])

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": "GROUP_KNOCKOUT", "rule_config": {}},
    )

    assert response.status_code == 409, response.text
    assert "已产生比赛或团体对抗" in response.text
    assert repo.count_matches(conn, tournament["id"]) == 1
    assert _raw_format(conn, tournament["id"]) == before


def test_update_rejected_after_team_tie_exists(client, conn):
    tournament = _create_tournament(client)
    first = repo.create_entry(conn, tournament["id"], "TEAM", "甲队", 1000, [])
    second = repo.create_entry(conn, tournament["id"], "TEAM", "乙队", 1000, [])
    repo.create_team_tie(
        conn,
        tournament["id"],
        "GROUP",
        None,
        1,
        1,
        first["id"],
        second["id"],
    )
    conn.commit()
    before = _raw_format(conn, tournament["id"])

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": "GROUP_KNOCKOUT", "rule_config": {}},
    )

    assert response.status_code == 409, response.text
    assert "已产生比赛或团体对抗" in response.text
    assert repo.count_team_ties(conn, tournament["id"]) == 1
    assert _raw_format(conn, tournament["id"]) == before


def test_handler_validation_failure_rolls_back_all_three_fields(client, conn):
    tournament = _create_tournament(
        client,
        name="D4A 团体赛回滚",
        event_type="TEAM",
    )
    before = _raw_format(conn, tournament["id"])

    response = client.put(
        f"/api/tournaments/{tournament['id']}/format",
        json={"format_code": "GROUP_KNOCKOUT", "rule_config": {}},
    )

    assert response.status_code == 409, response.text
    assert "团体赛不使用个人赛赛制处理器" in response.text
    assert _raw_format(conn, tournament["id"]) == before


def test_group_knockout_end_to_end_from_persisted_configuration(client):
    tournament = _create_tournament(
        client,
        name="D4A 落库配置端到端",
        group_count=2,
        qualify_per_group=1,
        format_code="GROUP_KNOCKOUT",
        rule_config={},
    )
    for index in range(4):
        response = client.post(
            f"/api/tournaments/{tournament['id']}/players",
            json={"name": f"选手{index + 1}"},
        )
        assert response.status_code == 201, response.text
    assert client.post(
        f"/api/tournaments/{tournament['id']}/auto-group"
    ).status_code == 200

    conn = db_module.connect()
    try:
        persisted = repo.get_tournament(conn, tournament["id"])
        assert persisted is not None
        handler = formats_service.resolve_format_handler(persisted["format_code"])
        assert handler.validate_config(conn, tournament["id"])["id"] == tournament["id"]
        generated = handler.generate_matches(conn, tournament["id"])
        conn.commit()
        assert generated.matches_generated == 2
        assert sum(generated.per_group.values()) == 2
        assert repo.count_matches(conn, tournament["id"]) == 2
    finally:
        conn.close()


def test_repository_round_trip_and_invalid_database_json_is_explicit(conn):
    config = {"nested": {"seed": [2, 1]}, "alpha": "武汉大学"}
    tournament = repo.create_tournament(
        conn,
        "D4A Repository",
        "2026-09-22",
        2,
        1,
        1,
        format_code="GROUP_KNOCKOUT",
        rule_config=config,
        rule_version=1,
    )
    conn.commit()

    assert _raw_format(conn, tournament["id"]) == (
        "GROUP_KNOCKOUT",
        '{"alpha":"武汉大学","nested":{"seed":[2,1]}}',
        1,
    )
    persisted = repo.get_tournament(conn, tournament["id"])
    assert persisted is not None
    assert persisted["rule_config"] == config

    updated = repo.update_tournament_format_config(
        conn,
        tournament["id"],
        format_code="GROUP_KNOCKOUT",
        rule_config={"alpha": "新的配置"},
        rule_version=1,
    )
    assert updated is not None
    assert updated["rule_config"] == {"alpha": "新的配置"}
    assert _raw_format(conn, tournament["id"])[1] == '{"alpha":"新的配置"}'

    conn.execute(
        "UPDATE tournaments SET rule_config = ? WHERE id = ?",
        ("{not-json", tournament["id"]),
    )
    conn.commit()
    with pytest.raises(repo.RuleConfigError, match="不是合法 JSON"):
        repo.get_tournament(conn, tournament["id"])

    conn.execute(
        "UPDATE tournaments SET rule_config = ? WHERE id = ?",
        (json.dumps([1, 2]), tournament["id"]),
    )
    conn.commit()
    with pytest.raises(repo.RuleConfigError, match="JSON object"):
        repo.get_tournament(conn, tournament["id"])

    with pytest.raises(repo.RuleConfigError, match="可稳定序列化"):
        repo.encode_rule_config({"value": float("nan")})
