"""秩序册快照接口契约。"""


def _create_tournament(client):
    response = client.post(
        "/api/tournaments",
        json={
            "name": "秩序册快照验收",
            "date": "2026-09-07",
            "table_count": 2,
            "group_count": 1,
            "qualify_per_group": 1,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_snapshot_returns_all_print_sections_in_one_response(client):
    tournament_id = _create_tournament(client)
    for name in ("甲", "乙"):
        assert client.post(
            f"/api/tournaments/{tournament_id}/players",
            json={"name": name, "rating_points": 1000},
        ).status_code == 201

    response = client.get(f"/api/tournaments/{tournament_id}/order-book-snapshot")

    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["snapshot_at"].endswith("Z")
    assert snapshot["tournament"]["id"] == tournament_id
    assert set(snapshot) == {
        "snapshot_at", "tournament", "entries", "groups", "rankings",
        "tree", "matches", "dashboard",
    }
    assert snapshot["dashboard"]["stats"]["total"] == len(snapshot["matches"])


def test_snapshot_missing_tournament_returns_404(client):
    response = client.get("/api/tournaments/999/order-book-snapshot")
    assert response.status_code == 404
