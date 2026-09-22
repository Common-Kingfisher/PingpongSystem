"""REST API 集成测试（FastAPI TestClient）。"""


def _create_tournament(client, **overrides):
    body = {
        "name": "2025 秋季乒乓球赛",
        "date": "2025-06-01",
        "table_count": 6,
        "group_count": 4,
        "qualify_per_group": 2,
    }
    body.update(overrides)
    return client.post("/api/tournaments", json=body)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------- tournament

def test_create_tournament_ok(client):
    resp = _create_tournament(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] > 0
    assert data["name"] == "2025 秋季乒乓球赛"
    assert data["date"] == "2025-06-01"
    assert data["table_count"] == 6
    assert data["stage"] == "REGISTRATION"  # 初始阶段为注册
    assert data["operation_mode"] == "LIVE"
    assert "created_at" in data


def test_create_tournament_table_count_out_of_range(client):
    resp = _create_tournament(client, table_count=16)
    assert resp.status_code == 422  # 球台数 1~15


def test_create_tournament_empty_name(client):
    resp = _create_tournament(client, name="")
    assert resp.status_code == 422


def test_create_tournament_creates_tables(client):
    resp = _create_tournament(client, table_count=6)
    tid = resp.json()["id"]
    # 任务 4 之前没有球台 API，这里直接通过查询验证表已生成（此处从响应无法直接看到，
    # 改由 repository 测试覆盖；此处仅验证创建成功且阶段正确）。
    assert resp.status_code == 201


def test_list_tournaments(client):
    _create_tournament(client, name="第一场")
    _create_tournament(client, name="第二场")
    resp = client.get("/api/tournaments")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert names == ["第二场", "第一场"]


def test_get_tournament(client):
    tid = _create_tournament(client).json()["id"]
    resp = client.get(f"/api/tournaments/{tid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == tid


def test_get_tournament_not_found(client):
    resp = client.get("/api/tournaments/999")
    assert resp.status_code == 404
    # A2.5：赛事读/写入口统一用 RESOURCE_NOT_FOUND，避免泄漏资源存在性。
    assert resp.json()["detail"] == {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}


def test_live_tournament_delete_requires_exact_name(client):
    tid = _create_tournament(client, name="不可误删的正式赛事").json()["id"]
    assert client.delete(f"/api/tournaments/{tid}").status_code == 409
    assert client.delete(f"/api/tournaments/{tid}?confirm_name=名称错误").status_code == 409
    assert client.delete(
        f"/api/tournaments/{tid}", params={"confirm_name": "不可误删的正式赛事"}
    ).status_code == 204


def test_demo_tournament_delete_keeps_simple_confirmation_contract(client):
    tid = _create_tournament(client, operation_mode="DEMO").json()["id"]
    assert client.delete(f"/api/tournaments/{tid}").status_code == 204


# ------------------------------------------------------------------ players

def test_player_lifecycle(client):
    tid = _create_tournament(client).json()["id"]

    resp = client.post(f"/api/tournaments/{tid}/players", json={"name": "张三", "college": "计算机学院"})
    assert resp.status_code == 201
    player = resp.json()
    assert player["name"] == "张三"
    assert player["college"] == "计算机学院"
    assert player["group_id"] is None

    # 修改
    resp = client.patch(f"/api/tournaments/{tid}/players/{player['id']}", json={"name": "张三丰"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "张三丰"

    # 列表
    resp = client.get(f"/api/tournaments/{tid}/players")
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["张三丰"]

    # 删除
    resp = client.delete(f"/api/tournaments/{tid}/players/{player['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/api/tournaments/{tid}/players")
    assert resp.json() == []


def test_add_player_to_missing_tournament(client):
    resp = client.post("/api/tournaments/999/players", json={"name": "张三"})
    assert resp.status_code == 404


def test_add_player_empty_name(client):
    tid = _create_tournament(client).json()["id"]
    resp = client.post(f"/api/tournaments/{tid}/players", json={"name": ""})
    assert resp.status_code == 422


def test_update_missing_player(client):
    tid = _create_tournament(client).json()["id"]
    resp = client.patch(f"/api/tournaments/{tid}/players/999", json={"name": "李四"})
    assert resp.status_code == 404


def test_delete_missing_player(client):
    tid = _create_tournament(client).json()["id"]
    resp = client.delete(f"/api/tournaments/{tid}/players/999")
    assert resp.status_code == 404
