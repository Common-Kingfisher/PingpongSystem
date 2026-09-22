"""A1-4：删除赛事的基础防误操作（存在性检查、业务错误、级联完整性、先导出再删除）。

本轮不引入软删除 / 回收站 / 归档状态机，只验证并锁定最小可靠性行为。
"""

import json

from app import repository as repo
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service

CHILD_TABLES = [
    "groups",
    "players",
    "entries",
    "entry_members",
    "tables",
    "matches",
    "match_games",
    "score_requests",
    "qualification_decisions",
]


def test_delete_missing_tournament_returns_404(client):
    resp = client.delete("/api/tournaments/999999")
    assert resp.status_code == 404
    # A2.5：赛事读/写入口统一用 RESOURCE_NOT_FOUND，避免泄漏资源存在性。
    assert resp.json()["detail"] == {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}


def test_delete_live_requires_exact_name_and_supports_backup_first(client):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "删除保护验收",
            "date": "2025-06-01",
            "table_count": 2,
            "group_count": 2,
            "qualify_per_group": 1,
            "operation_mode": "LIVE",
        },
    ).json()["id"]
    for index in range(4):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1}"})
    client.post(f"/api/tournaments/{tid}/auto-group")

    # 推荐的人工备份流程：删除前先导出
    backup = client.get(f"/api/tournaments/{tid}/export")
    assert backup.status_code == 200
    assert backup.json()["tournament"]["name"] == "删除保护验收"
    assert len(backup.json()["players"]) == 4

    assert client.delete(f"/api/tournaments/{tid}").status_code == 409
    assert client.delete(f"/api/tournaments/{tid}?confirm_name=错误名称").status_code == 409
    assert client.delete("/api/tournaments/999999?confirm_name=x").status_code == 404

    assert client.delete(f"/api/tournaments/{tid}?confirm_name=删除保护验收").status_code == 204
    assert client.get(f"/api/tournaments/{tid}/export").status_code == 404


def test_delete_cascades_every_child_table(conn):
    """级联必须清空全部子表（含比赛小分、幂等账本与人工裁定审计）。"""
    tournament = repo.create_tournament(conn, "级联验收", "2025-06-01", 2, 2, 1)
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 2)
    for index in range(4):
        repo.add_player(conn, tid, f"P{index + 1}", None)
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    match = repo.list_matches(conn, tid, stage="GROUP")[0]
    scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
    scores_service.record_score(conn, match["id"], 2, 0, request_id="cascade-audit-1")
    scores_service.revise_score(conn, match["id"], None, None, games=[(11, 9), (11, 7)])
    group = repo.list_groups(conn, tid)[0]
    repo.create_qualification_decision(
        conn, tid, group["id"], json.dumps([]), json.dumps([]), "级联测试", "裁判长"
    )
    conn.commit()

    # 删除前每张子表都有该赛事的数据
    for table in CHILD_TABLES:
        rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert rows > 0, f"{table} 未准备好删除前的数据"

    assert repo.delete_tournament(conn, tid) is True
    conn.commit()

    for table in CHILD_TABLES:
        rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert rows == 0, f"{table} 仍有残留（级联不完整）"
    assert repo.get_tournament(conn, tid) is None
    assert repo.delete_tournament(conn, tid) is False


def test_delete_cascades_team_ties_and_rubbers(conn):
    """A3：删除团体赛赛事必须一并清掉 team_ties / team_rubbers，且不留悬空外键。

    注意 team_ties.entry_a_id / entry_b_id 故意不带 ON DELETE CASCADE：
    单删一支队伍必须被业务层拦住（否则对抗会凭空少一边）。这里验证的是"删整个赛事"
    这条路径（队伍、对抗、盘一起消失）不会因为外键而失败或残留。
    """
    tid = repo.create_tournament(conn, "团体级联验收", "2026-05-01", 4, 2, 1, event_type="TEAM")["id"]
    repo.create_tables_for_tournament(conn, tid, 4)
    players = [repo.add_player(conn, tid, f"P{index}", None) for index in range(1, 5)]
    a = repo.create_entry(conn, tid, "TEAM", "A队", 0, [players[0]["id"], players[1]["id"]])
    b = repo.create_entry(conn, tid, "TEAM", "B队", 0, [players[2]["id"], players[3]["id"]])
    tie = repo.create_team_tie(conn, tid, "GROUP", None, 1, 1, a["id"], b["id"])
    # 直接用 repository 造盘：本用例只验证级联，不依赖任何"已冻结的赛制"
    repo.create_team_rubber(conn, tie["id"], 1, "SINGLES", '["H1"]', '["A1"]')
    repo.create_team_rubber(conn, tie["id"], 2, "DOUBLES", '["H2","H3"]', '["A2","A3"]')
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM team_ties").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM team_rubbers").fetchone()[0] == 2

    assert repo.delete_tournament(conn, tid) is True
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM team_ties").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM team_rubbers").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
