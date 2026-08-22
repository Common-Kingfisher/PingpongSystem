"""小组循环赛生成测试：数量、无重复、无自对、状态与守卫。"""

from collections import Counter

from app import repository as repo
from app.services import groups as groups_service
from app.services import matches as matches_service


def _grouped_tournament(client, n_players=24, group_count=4, table_count=6, qualify=2):
    resp = client.post(
        "/api/tournaments",
        json={
            "name": "循环赛测试",
            "date": "2025-06-01",
            "table_count": table_count,
            "group_count": group_count,
            "qualify_per_group": qualify,
        },
    )
    tid = resp.json()["id"]
    for i in range(1, n_players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    return tid


# ------------------------------------------------------------ domain/service

def test_generate_4x6_produces_60(conn):
    t = repo.create_tournament(conn, "T", "2025-06-01", 6, 4, 2)
    for i in range(1, 25):
        repo.add_player(conn, t["id"], f"选手{i:02d}", None)
    groups_service.auto_group_tournament(conn, t["id"])

    total, per_group = matches_service.generate_group_matches(conn, t["id"])
    assert total == 60
    assert per_group == {"A组": 15, "B组": 15, "C组": 15, "D组": 15}

    matches = repo.list_matches(conn, t["id"])
    assert len(matches) == 60
    assert all(m["status"] == "WAITING" for m in matches)
    assert all(m["winner_id"] is None and m["player_a_score"] is None for m in matches)
    # 赛事进入小组赛阶段
    assert repo.get_tournament(conn, t["id"])["stage"] == "GROUP_STAGE"
    # 每组 15 场
    assert sorted(Counter(m["group_id"] for m in matches).values()) == [15, 15, 15, 15]


def test_generate_rejected_when_stage_not_registration(conn):
    t = repo.create_tournament(conn, "T", "2025-06-01", 6, 4, 2)
    for i in range(1, 7):
        repo.add_player(conn, t["id"], f"P{i}", None)
    groups_service.auto_group_tournament(conn, t["id"])
    matches_service.generate_group_matches(conn, t["id"])
    # 第二次生成 → 阶段已不是 REGISTRATION，先触发阶段守卫
    try:
        matches_service.generate_group_matches(conn, t["id"])
        assert False, "应当抛出异常"
    except matches_service.TournamentStageError:
        pass


def test_generate_before_grouping_rejected(conn):
    t = repo.create_tournament(conn, "T", "2025-06-01", 6, 4, 2)
    for i in range(1, 7):
        repo.add_player(conn, t["id"], f"P{i}", None)
    try:
        matches_service.generate_group_matches(conn, t["id"])
        assert False, "应当抛出异常"
    except matches_service.NoGroupsError:
        pass


# ---------------------------------------------------------------------- API

def test_api_generate_60_matches(client):
    tid = _grouped_tournament(client)
    resp = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert resp.status_code == 200
    data = resp.json()
    assert data["matches_generated"] == 60
    assert data["per_group"] == {"A组": 15, "B组": 15, "C组": 15, "D组": 15}
    assert data["tournament"]["stage"] == "GROUP_STAGE"

    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    assert len(matches) == 60
    assert all(m["stage"] == "GROUP" and m["status"] == "WAITING" for m in matches)


def test_api_matches_no_duplicate_pairs_no_self(client):
    tid = _grouped_tournament(client)
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    seen = set()
    for m in matches:
        assert m["player_a_id"] != m["player_b_id"]
        pair = frozenset((m["player_a_id"], m["player_b_id"]))
        assert pair not in seen, f"重复对阵: {pair}"
        seen.add(pair)
    assert len(seen) == 60


def test_api_generate_before_grouping_409(client):
    resp = client.post(
        "/api/tournaments",
        json={"name": "T", "date": "2025-06-01", "table_count": 6, "group_count": 4, "qualify_per_group": 2},
    )
    tid = resp.json()["id"]
    for i in range(1, 7):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"})
    resp = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert resp.status_code == 409
    assert "分组" in resp.json()["detail"]


def test_api_regenerate_409(client):
    tid = _grouped_tournament(client)
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    resp = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert resp.status_code == 409
    # 首次生成后阶段已变为 GROUP_STAGE，重复生成命中阶段守卫（同为 409）
    assert "不允许" in resp.json()["detail"] or "已生成" in resp.json()["detail"]


def test_api_five_player_group_generates_10(client):
    tid = _grouped_tournament(client, n_players=5, group_count=1)
    resp = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert resp.status_code == 200
    assert resp.json()["matches_generated"] == 10  # 5×4/2


def test_api_matches_filter(client):
    tid = _grouped_tournament(client, n_players=6, group_count=1)
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    resp = client.get(f"/api/tournaments/{tid}/matches?status=WAITING")
    assert len(resp.json()) == 15
    resp = client.get(f"/api/tournaments/{tid}/matches?status=PLAYING")
    assert resp.json() == []
    resp = client.get(f"/api/tournaments/{tid}/matches?stage=BAD")
    assert resp.status_code == 422


def test_api_matches_missing_tournament_404(client):
    resp = client.get("/api/tournaments/999/matches")
    assert resp.status_code == 404
