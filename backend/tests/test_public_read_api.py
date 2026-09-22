"""A2.5 修复回归：Public 页面只读 GET 必须可匿名访问。"""

from __future__ import annotations


PUBLIC_READ_SUFFIXES = (
    "",
    "/players",
    "/entries",
    "/groups",
    "/matches",
    "/dashboard",
    "/rankings",
    "/knockout",
)


def _create_public_tournament(client) -> tuple[int, int]:
    """准备带完整小组赛和淘汰赛签表的 Public 可读赛事。"""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Public 匿名只读回归赛",
            "date": "2026-09-22",
            "table_count": 6,
            "group_count": 4,
            "qualify_per_group": 2,
        },
    )
    assert response.status_code == 201, response.text
    tournament_id = response.json()["id"]

    for index in range(1, 9):
        response = client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": f"Public选手{index:02d}"},
        )
        assert response.status_code == 201, response.text

    response = client.post(f"/api/tournaments/{tournament_id}/auto-group")
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/tournaments/{tournament_id}/generate-group-matches"
    )
    assert response.status_code == 200, response.text

    for _ in range(50):
        response = client.post(f"/api/tournaments/{tournament_id}/schedule-next")
        assert response.status_code == 200, response.text
        dashboard = client.get(
            f"/api/tournaments/{tournament_id}/dashboard"
        ).json()
        playing = [table["match"] for table in dashboard["tables"] if table["match"]]
        if not playing:
            break
        for match in playing:
            winner_id = min(match["player_a_id"], match["player_b_id"])
            score_a, score_b = (
                (2, 0) if winner_id == match["player_a_id"] else (0, 2)
            )
            response = client.post(
                f"/api/matches/{match['id']}/score",
                json={"player_a_score": score_a, "player_b_score": score_b},
            )
            assert response.status_code == 200, response.text
    else:
        raise AssertionError("小组赛未在限定轮次内完成")

    group_matches = client.get(
        f"/api/tournaments/{tournament_id}/matches", params={"stage": "GROUP"}
    )
    assert group_matches.status_code == 200, group_matches.text
    assert group_matches.json()
    assert all(match["status"] == "FINISHED" for match in group_matches.json())

    response = client.post(f"/api/tournaments/{tournament_id}/generate-knockout")
    assert response.status_code == 200, response.text
    return tournament_id, group_matches.json()[0]["id"]


def _remove_credentials(client) -> None:
    client.headers.pop("Authorization", None)
    assert not client.cookies
    assert "Authorization" not in client.headers


def _assert_auth_required(response) -> None:
    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_public_read_apis_work_without_cookie_or_bearer(client):
    tournament_id, _ = _create_public_tournament(client)
    _remove_credentials(client)

    responses = {
        suffix: client.get(f"/api/tournaments/{tournament_id}{suffix}")
        for suffix in PUBLIC_READ_SUFFIXES
    }
    failures = {
        suffix: (response.status_code, response.text)
        for suffix, response in responses.items()
        if response.status_code != 200
    }
    assert not failures, failures

    assert responses[""].json()["id"] == tournament_id
    assert len(responses["/players"].json()) == 8
    assert isinstance(responses["/entries"].json(), list)
    assert len(responses["/groups"].json()["groups"]) == 4
    assert responses["/matches"].json()
    assert responses["/dashboard"].json()["tournament"]["id"] == tournament_id
    assert len(responses["/rankings"].json()["rankings"]) == 4
    assert responses["/knockout"].json()["tournament"]["stage"] == "KNOCKOUT"
    assert responses["/knockout"].json()["rounds"]


def test_sensitive_management_reads_still_require_login(client):
    tournament_id, match_id = _create_public_tournament(client)
    _remove_credentials(client)

    sensitive_paths = (
        f"/api/tournaments/{tournament_id}/export",
        f"/api/tournaments/{tournament_id}/order-book-snapshot",
        f"/api/tournaments/{tournament_id}/schedule-estimates",
        f"/api/tournaments/{tournament_id}/preflight",
        f"/api/matches/{match_id}/score-audits",
    )
    for path in sensitive_paths:
        _assert_auth_required(client.get(path))


def test_legacy_registration_write_stays_login_required(client):
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Legacy 报名边界赛",
            "date": "2026-09-22",
            "table_count": 1,
            "group_count": 1,
            "qualify_per_group": 1,
        },
    )
    assert response.status_code == 201, response.text
    tournament_id = response.json()["id"]
    _remove_credentials(client)

    response = client.post(
        f"/api/tournaments/{tournament_id}/players",
        json={"name": "匿名报名选手"},
    )
    _assert_auth_required(response)


def test_public_read_missing_tournament_returns_404_not_401(client):
    _remove_credentials(client)

    response = client.get("/api/tournaments/999999")
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "资源不存在",
    }
