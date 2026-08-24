"""针对本轮根因（sqlite 跨线程）与添加一致性 的回归测试。"""

import threading


def test_connection_usable_across_threads(monkeypatch, tmp_path):
    """根因回归：FastAPI 会把"依赖创建连接"与"端点使用连接"调度到不同线程，
    连接必须可跨线程使用，否则并发请求会间歇 500（sqlite3.ProgrammingError）。"""
    import os

    from app import db as db_module

    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "thread.db"))
    db_module.init_db()

    conn = db_module.connect()
    conn.execute("SELECT 1").fetchone()  # 在线程 A 创建并使用

    errors = []

    def use_in_other_thread():
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=use_in_other_thread)
    t.start()
    t.join()
    assert not errors, f"连接跨线程使用失败: {errors}"
    conn.close()


def test_add_player_immediately_visible(client):
    """验收 1：POST 201 后，GET 立即能看到新选手，不依赖第二次刷新。"""
    tid = client.post(
        "/api/tournaments",
        json={"name": "原子性验证", "date": "2025-06-01", "table_count": 6, "group_count": 4, "qualify_per_group": 2},
    ).json()["id"]

    resp = client.post(f"/api/tournaments/{tid}/players", json={"name": "测试选手01"})
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    names = [p["name"] for p in client.get(f"/api/tournaments/{tid}/players").json()]
    assert "测试选手01" in names
    assert new_id in [p["id"] for p in client.get(f"/api/tournaments/{tid}/players").json()]
