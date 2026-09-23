"""A1-3：赛事结构化导出（只读、可机器读取、含审计与推导结果）。"""

import json

from app import repository as repo
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import rankings as rankings_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service
from app.services import tournament_export as export_service

EXPORT_TABLES = [
    "tournaments",
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


def _db_snapshot(conn):
    """整库数据指纹：导出前后必须完全一致（导出只读）。"""
    snapshot = {}
    for table in EXPORT_TABLES:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        snapshot[table] = [tuple(row) for row in rows]
    return snapshot


def _build(conn, *, players=4, group_count=2, qualify=1, table_count=2, **kwargs):
    tournament = repo.create_tournament(
        conn, "导出验收", "2025-06-01", table_count, group_count, qualify, **kwargs
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, table_count)
    for index in range(players):
        repo.add_player(conn, tid, f"P{index + 1:02d}", "计算机学院", 1000 + index * 50)
    return tid


def _finish_group_stage(conn, tid):
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    for match in repo.list_matches(conn, tid, stage="GROUP"):
        winner = min(match["player_a_id"], match["player_b_id"])
        score_a, score_b = (2, 0) if winner == match["player_a_id"] else (0, 2)
        scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
        scores_service.record_score(conn, match["id"], score_a, score_b)


def test_export_available_at_every_stage(client):
    """REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED 都能导出。"""
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "导出阶段验收",
            "date": "2025-06-01",
            "table_count": 2,
            "group_count": 2,
            "qualify_per_group": 1,
            "games_to_win": 3,
            "points_to_win": 21,
        },
    ).json()["id"]
    for index in range(4):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1}"})

    def export():
        resp = client.get(f"/api/tournaments/{tid}/export")
        assert resp.status_code == 200
        return resp.json()

    # REGISTRATION
    data = export()
    assert data["schema_version"] == export_service.EXPORT_SCHEMA_VERSION
    assert data["tournament"]["stage"] == "REGISTRATION"
    assert len(data["players"]) == 4
    assert data["entries"] == [] and data["matches"] == []
    assert data["derived"]["rankings"] == []

    # 赛事规则必须随导出带走
    tournament = data["tournament"]
    assert tournament["event_type"] == "SINGLES"
    assert tournament["games_to_win"] == 3
    assert tournament["points_to_win"] == 21
    assert tournament["operation_mode"] == "LIVE"
    assert tournament["qualify_per_group"] == 1
    assert tournament["bronze_mode"] and tournament["placement_mode"]
    assert tournament["format_code"] is None
    assert tournament["rule_version"] is None
    assert tournament["rule_config"] == {}

    # GROUP_STAGE
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    data = export()
    assert data["tournament"]["stage"] == "GROUP_STAGE"
    assert len(data["groups"]) == 2
    assert len(data["tables"]) == 2
    assert len(data["entries"]) == 4
    assert len(data["entry_members"]) == 4
    assert {m["stage"] for m in data["matches"]} == {"GROUP"}
    assert len(data["derived"]["rankings"]) == 2

    # KOOTNOUT：小组赛结束后生成签表
    for match in client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json():
        winner = min(match["player_a_id"], match["player_b_id"])
        score_a, score_b = (3, 0) if winner == match["player_a_id"] else (0, 3)
        client.post(
            f"/api/matches/{match['id']}/score",
            json={
                "player_a_score": score_a,
                "player_b_score": score_b,
                # 前端始终带幂等编号；导出必须包含这份审计账本
                "request_id": f"11111111-1111-4111-8111-{match['id']:012d}",
            },
        )
    client.post(f"/api/tournaments/{tid}/generate-knockout")
    data = export()
    assert data["tournament"]["stage"] == "KNOCKOUT"
    knockout_matches = [m for m in data["matches"] if m["stage"] == "KNOCKOUT"]
    assert len(knockout_matches) == 1
    assert data["derived"]["champion"] is None
    assert [row["request_id"] for row in data["score_requests"]], "比分写入审计必须随导出带走"

    # FINISHED
    final = knockout_matches[0]
    client.post(f"/api/matches/{final['id']}/score", json={"player_a_score": 3, "player_b_score": 1})
    data = export()
    assert data["tournament"]["stage"] == "FINISHED"
    assert data["derived"]["champion"] is not None
    assert data["derived"]["runner_up"] is not None
    assert [row["rank"] for row in data["derived"]["placements"]][:2] == [1, 2]
    finished = next(m for m in data["matches"] if m["id"] == final["id"])
    assert (finished["player_a_score"], finished["player_b_score"]) == (3, 1)
    assert finished["winner_entry_id"] is not None
    assert finished["result_type"] == "NORMAL"


def test_export_contains_games_audit_and_derived(conn):
    tid = _build(conn)
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    match = repo.list_matches(conn, tid, stage="GROUP")[0]
    scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
    scores_service.record_score(conn, match["id"], 2, 0, request_id="export-audit-1")
    scores_service.revise_score(conn, match["id"], None, None, games=[(11, 9), (11, 7)])
    group = repo.list_groups(conn, tid)[0]
    # 用真实生产逻辑写入一条人工裁定（快照格式以 rankings.qualification_snapshot 为准）
    repo.create_qualification_decision(
        conn, tid, group["id"], json.dumps([match["entry_a_id"]]),
        rankings_service.qualification_snapshot({"group_id": group["id"], "qualify_count": 1,
                                                "finished_matches": 0, "total_matches": 0, "entries": []}),
        "同分人工裁定", "裁判长",
    )
    conn.commit()

    data = export_service.get_export(conn, tid)

    exported_match = next(m for m in data["matches"] if m["id"] == match["id"])
    assert (exported_match["player_a_score"], exported_match["player_b_score"]) == (2, 0)
    assert exported_match["winner_entry_id"] == match["entry_a_id"]
    assert exported_match["result_type"] == "NORMAL"
    assert [g["game_no"] for g in exported_match["games"]] == [1, 2]

    assert [g["game_no"] for g in data["match_games"]] == [1, 2]
    assert data["match_games"][0]["side_a_score"] == 11
    assert [r["request_id"] for r in data["score_requests"]] == ["export-audit-1"]
    # A6.26：score_audits 与 score_requests 同属比分审计链，必须一并归档
    assert [a["action"] for a in data["score_audits"]] == ["RECORD", "REVISE"]
    assert all(isinstance(a["before_snapshot"], dict) for a in data["score_audits"])
    assert all(isinstance(a["after_snapshot"], dict) for a in data["score_audits"])
    decision = data["qualification_decisions"][0]
    assert decision["operator_name"] == "裁判长"
    assert decision["active"] is True
    assert decision["selected_entry_ids"] == [match["entry_a_id"]]
    assert isinstance(decision["ranking_snapshot"], dict)
    assert decision["ranking_snapshot"]["group_id"] == group["id"]

    # entry_members 与 entries[].members 一致（两种等价形式）
    flat = {(row["entry_id"], row["player_id"], row["member_order"]) for row in data["entry_members"]}
    nested = {
        (entry["id"], member["player_id"], member["member_order"])
        for entry in data["entries"]
        for member in entry["members"]
    }
    assert flat == nested


def test_export_is_read_only(conn):
    tid = _build(conn, players=6, group_count=2, qualify=2, table_count=2)
    _finish_group_stage(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    before = _db_snapshot(conn)

    data = export_service.get_export(conn, tid)

    assert data["tournament"]["stage"] == "KNOCKOUT"
    assert _db_snapshot(conn) == before


def test_export_missing_tournament(client):
    resp = client.get("/api/tournaments/999999/export")
    assert resp.status_code == 404
    # A2.5：赛事读/写入口统一用 RESOURCE_NOT_FOUND，避免泄漏资源存在性。
    assert resp.json()["detail"] == {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}


def test_api_export_with_qualification_decision(client):
    """人工裁定（含冻结排名快照）必须能通过 API 导出，不能因 DTO 缺字段/格式不符变成 500。"""
    # 3 人单组循环 + 小分补录 → 三人互克 → 晋级线并列，可走真实人工裁定接口
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "裁定导出",
            "date": "2025-06-01",
            "table_count": 2,
            "group_count": 1,
            "qualify_per_group": 1,
        },
    ).json()["id"]
    for name in ("甲", "乙", "丙"):
        client.post(f"/api/tournaments/{tid}/players", json={"name": name})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    entries = sorted(client.get(f"/api/tournaments/{tid}/entries").json(), key=lambda e: e["id"])
    first, second, third = (entry["id"] for entry in entries)
    winner_by_pair = {
        frozenset((first, second)): first,
        frozenset((second, third)): second,
        frozenset((first, third)): third,
    }
    for match in client.get(f"/api/tournaments/{tid}/matches").json():
        winner = winner_by_pair[frozenset((match["entry_a_id"], match["entry_b_id"]))]
        score_a, score_b = (2, 0) if winner == match["entry_a_id"] else (0, 2)
        client.post(
            f"/api/matches/{match['id']}/score",
            json={"player_a_score": score_a, "player_b_score": score_b},
        )
        games = (
            [{"side_a_score": 11, "side_b_score": 5}, {"side_a_score": 11, "side_b_score": 5}]
            if winner == match["entry_a_id"]
            else [{"side_a_score": 5, "side_b_score": 11}, {"side_a_score": 5, "side_b_score": 11}]
        )
        assert client.post(
            f"/api/matches/{match['id']}/revise-score",
            json={"games": games, "operator_name": "测试主裁", "change_reason": "复核补录小分"},
        ).status_code == 200

    group = client.get(f"/api/tournaments/{tid}/groups").json()["groups"][0]
    decision = client.post(
        f"/api/tournaments/{tid}/groups/{group['id']}/qualification-decision",
        json={
            "selected_entry_ids": [third],
            "reason": "三人循环互克并列，按现场规程人工指定",
            "operator_name": "裁判长",
        },
    )
    assert decision.status_code == 201

    resp = client.get(f"/api/tournaments/{tid}/export")

    assert resp.status_code == 200
    exported = resp.json()["qualification_decisions"]
    assert [d["operator_name"] for d in exported] == ["裁判长"]
    assert exported[0]["active"] is True
    assert exported[0]["selected_entry_ids"] == [third]
    # 真实快照是 JSON 对象，导出必须原样保留可机读结构
    assert exported[0]["ranking_snapshot"]["group_id"] == group["id"]
    assert exported[0]["ranking_snapshot"]["entries"], "快照必须保留各组参赛位明细"

def test_export_decisions_cover_every_group(conn):
    """多组赛事的裁定按 group_id 分散存储，导出必须全部覆盖。

    ``tournament_id`` 与 ``group_id`` 在单组测试里常会撞号，因此必须用两组
    用例证明导出确实遍历了赛事下的每个小组。
    """
    tid = _build(conn, players=4, group_count=2, qualify=1)
    groups_service.auto_group_tournament(conn, tid)
    groups = repo.list_groups(conn, tid)
    assert len(groups) == 2
    matches_service.generate_group_matches(conn, tid)
    selected_a = repo.list_entries(conn, tid)[0]["id"]
    selected_b = repo.list_entries(conn, tid)[1]["id"]
    for group, selected in ((groups[0], selected_a), (groups[1], selected_b)):
        repo.create_qualification_decision(
            conn,
            tid,
            group["id"],
            json.dumps([selected]),
            rankings_service.qualification_snapshot(
                {
                    "group_id": group["id"],
                    "qualify_count": 1,
                    "finished_matches": 0,
                    "total_matches": 0,
                    "entries": [],
                }
            ),
            f"第{group['sort_order'] + 1}组人工裁定",
            "裁判长",
        )
    conn.commit()

    data = export_service.get_export(conn, tid)

    exported_group_ids = {d["group_id"] for d in data["qualification_decisions"]}
    assert exported_group_ids == {groups[0]["id"], groups[1]["id"]}
    assert len(data["qualification_decisions"]) == 2


def test_export_contains_registration_organization_and_venue(conn):
    """A6.26：D5 报名 / 组织方 / 场馆字段必须进入赛事归档导出。"""
    tid = _build(conn, players=2, group_count=1, qualify=1)
    repo.create_registration(
        conn,
        tid,
        name="现场补报名",
        affiliation="体育学院",
        contact="13800000000",
        rating_points=1200,
    )
    repo.upsert_organization(
        conn,
        tid,
        name="市乒乓球协会",
        contact_name="王老师",
        contact="010-00000000",
        note="主办单位",
    )
    repo.upsert_venue(
        conn,
        tid,
        name="市民健身中心",
        address="体育馆路 1 号",
        contact_name="李老师",
        contact="010-11111111",
        note="主赛场",
    )
    conn.commit()

    data = export_service.get_export(conn, tid)

    assert [r["name"] for r in data["registrations"]] == ["现场补报名"]
    assert data["registrations"][0]["status"] == "PENDING"
    assert data["organizations"]["name"] == "市乒乓球协会"
    assert data["venues"]["address"] == "体育馆路 1 号"


def test_export_optional_d5_fields_default_to_empty(conn):
    """未设置 D5 资料时导出字段存在且为空，保证归档结构稳定。"""
    tid = _build(conn, players=2, group_count=1, qualify=1)
    conn.commit()

    data = export_service.get_export(conn, tid)

    assert data["registrations"] == []
    assert data["organizations"] is None
    assert data["venues"] is None
    assert data["score_audits"] == []
