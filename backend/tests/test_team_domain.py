"""A3：团体赛领域核心 —— TeamFormatSpec 校验/快照、TeamTie/TeamRubber 骨架、与 Match 的边界。

三条必须锁死的边界：
1. 生产赛制注册表为空：A3 不臆造任何"经典赛制"（OLYMPIC / ITTF_CLASSIC 之类一律不存在），
   未登记的赛制调用建盘一律 422。测试里用的赛制叫 TEST_ONLY_*，只存在于测试进程内。
2. 骨架只记录"这一盘需要几个出场位置"，绝不创建 Match：team_rubbers.match_id 恒为 NULL。
3. 团体赛不进入单打引擎：小组赛/淘汰赛生成器必须显式拒绝 TEAM，而不是悄悄生成一堆
   "队伍 vs 队伍"的普通比赛。
"""

import json

import pytest

from app import repository as repo
from app.domain import team_formats
from app.domain.team_formats import RubberTemplate, TeamFormatSpec
from app.models import (
    EventType,
    MatchStage,
    TeamRubberStatus,
    TeamRubberType,
    TeamTieStatus,
)
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import team_ties as tie_service
from app.services import teams as teams_service
from app.services import tournament_export

R1 = RubberTemplate(1, TeamRubberType.SINGLES.value, ("H1",), ("A1",))
R2 = RubberTemplate(2, TeamRubberType.SINGLES.value, ("H2",), ("A2",))
R3 = RubberTemplate(3, TeamRubberType.DOUBLES.value, ("H3", "H4"), ("A3", "A4"))

#: 测试专用赛制：不是任何官方规则，只用来验证"注册表 → 骨架"这条链路。
TEST_ONLY_SPEC = TeamFormatSpec(
    code="TEST_ONLY_SKELETON",
    version=1,
    display_name="测试用骨架赛制（非生产规则，仅验证骨架构建）",
    rubbers_to_win=2,
    rubbers=(R1, R2, R3),
)


@pytest.fixture()
def test_only_format(monkeypatch):
    """把测试用赛制临时放进注册表，测试结束后自动移除（不污染生产注册表）。"""
    team_formats.validate_format_spec(TEST_ONLY_SPEC)
    monkeypatch.setitem(team_formats.PRODUCTION_FORMATS, TEST_ONLY_SPEC.code, TEST_ONLY_SPEC)
    return TEST_ONLY_SPEC


def _team_tournament(conn, *, players: int = 6, group_count: int = 2) -> int:
    tournament = repo.create_tournament(
        conn, "团体领域验收", "2026-05-01", 4, group_count, 1, event_type="TEAM", operation_mode="DEMO"
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 4)
    for index in range(1, players + 1):
        repo.add_player(conn, tid, f"选手{index:02d}", "计算机学院", 1000 + index)
    conn.commit()
    return tid


def _two_teams(conn, tid: int) -> tuple[dict, dict]:
    """把选手对半分给两支队伍；人数为奇数时最后一名选手不入队（留给用例使用）。"""
    players = repo.list_players(conn, tid)
    half = len(players) // 2
    a = teams_service.create_team_entry(conn, tid, "A队", [p["id"] for p in players[:half]])
    b = teams_service.create_team_entry(conn, tid, "B队", [p["id"] for p in players[half : half * 2]])
    return a, b


# ------------------------------------------------------------------- 枚举边界

def test_event_type_is_three_way_and_has_no_team_match_stage():
    assert {e.value for e in EventType} == {"SINGLES", "DOUBLES", "TEAM"}
    # A3 不引入 MatchStage.TEAM：团体对抗不是普通比赛，不能混进 matches.stage
    assert {s.value for s in MatchStage} == {"GROUP", "KNOCKOUT"}
    # 一盘只可能是单打盘或双打盘
    assert {t.value for t in TeamRubberType} == {"SINGLES", "DOUBLES"}
    assert {s.value for s in TeamTieStatus} == {"WAITING", "PLAYING", "FINISHED"}
    assert {s.value for s in TeamRubberStatus} == {"PENDING", "READY", "PLAYING", "FINISHED", "SKIPPED"}


# --------------------------------------------------------------- 生产注册表为空

def test_production_format_registry_is_empty():
    assert team_formats.PRODUCTION_FORMATS == {}
    for invented in ("OLYMPIC", "ITTF_CLASSIC", "BESTOF5"):
        with pytest.raises(team_formats.TeamFormatError) as excinfo:
            team_formats.get_format_spec(invented)
        assert "未知的团体赛赛制" in str(excinfo.value)
    with pytest.raises(team_formats.TeamFormatError):
        team_formats.get_format_spec("   ")


def test_register_format_spec_validates_and_looks_up(monkeypatch):
    monkeypatch.setattr(team_formats, "PRODUCTION_FORMATS", {})
    team_formats.register_format_spec(TEST_ONLY_SPEC)
    assert team_formats.get_format_spec(TEST_ONLY_SPEC.code) is TEST_ONLY_SPEC
    bad = TeamFormatSpec("BAD", 1, "坏赛制", 5, (R1,))
    with pytest.raises(team_formats.TeamFormatError):
        team_formats.register_format_spec(bad)


# ------------------------------------------------------------------- 规格校验

@pytest.mark.parametrize(
    "spec, fragment",
    [
        (TeamFormatSpec("", 1, "无名", 1, (R1,)), "code 不能为空"),
        (TeamFormatSpec(" X ", 1, "带空白", 1, (R1,)), "首尾空白"),
        (TeamFormatSpec("X", 0, "版本 0", 1, (R1,)), "版本号"),
        (TeamFormatSpec("X", 1, "  ", 1, (R1,)), "显示名称"),
        (TeamFormatSpec("X", 1, "零盘获胜", 0, (R1,)), ">= 1"),
        (TeamFormatSpec("X", 1, "赢的比打的多", 3, (R1, R2)), "只定义了 2 盘"),
        (TeamFormatSpec("X", 1, "没有盘", 1, ()), "至少要包含一盘"),
        (TeamFormatSpec("X", 1, "盘序号重复", 1, (R1, RubberTemplate(1, "SINGLES", ("H9",), ("A9",)))), "盘序号重复"),
        (TeamFormatSpec("X", 1, "盘序号不连续", 1, (R1, RubberTemplate(3, "SINGLES", ("H3",), ("A3",)))), "连续"),
        (TeamFormatSpec("X", 1, "盘序号为零", 1, (RubberTemplate(0, "SINGLES", ("H1",), ("A1",)),)), ">= 1 的整数"),
        (TeamFormatSpec("X", 1, "盘类型是团体", 1, (RubberTemplate(1, "TEAM", ("H1",), ("A1",)),)), "盘类型不合法"),
        (TeamFormatSpec("X", 1, "双打只有一个位置", 1, (RubberTemplate(1, "DOUBLES", ("H1",), ("A1", "A2")),)), "需要 2 个位置"),
        (TeamFormatSpec("X", 1, "单打两个位置", 1, (RubberTemplate(1, "SINGLES", ("H1", "H2"), ("A1",)),)), "需要 1 个位置"),
        (TeamFormatSpec("X", 1, "空位置", 1, (RubberTemplate(1, "SINGLES", (), ("A1",)),)), "位置列表不能为空"),
        (TeamFormatSpec("X", 1, "位置重复", 1, (RubberTemplate(1, "DOUBLES", ("H1", "H1"), ("A1", "A2")),)), "位置代号重复"),
        (TeamFormatSpec("X", 1, "位置带空白", 1, (RubberTemplate(1, "SINGLES", (" H1 ",), ("A1",)),)), "首尾空白"),
        (TeamFormatSpec("X", 1, "位置不是字符串", 1, (RubberTemplate(1, "SINGLES", (1,), ("A1",)),)), "位置代号不能为空"),
    ],
)
def test_invalid_format_specs_are_rejected(spec, fragment):
    with pytest.raises(team_formats.TeamFormatError) as excinfo:
        team_formats.validate_format_spec(spec)
    assert fragment in str(excinfo.value)


def test_valid_format_spec_is_accepted():
    team_formats.validate_format_spec(TEST_ONLY_SPEC)
    # 允许同一位置代号在不同盘里复用（同一位选手可以打多盘），这不是错误
    repeat = TeamFormatSpec("REPEAT", 1, "位置复用", 1, (R1, RubberTemplate(2, "SINGLES", ("H1",), ("A1",))))
    team_formats.validate_format_spec(repeat)


# --------------------------------------------------------------------- 快照

def test_snapshot_round_trip():
    data = team_formats.snapshot_dict(TEST_ONLY_SPEC)
    assert data["snapshot_version"] == team_formats.SNAPSHOT_VERSION
    assert [r["sequence"] for r in data["rubbers"]] == [1, 2, 3]
    assert data["rubbers"][2]["home_slots"] == ["H3", "H4"]

    text = team_formats.dump_snapshot(TEST_ONLY_SPEC)
    restored = team_formats.load_snapshot(text)
    assert restored == TEST_ONLY_SPEC
    assert json.loads(text)["code"] == TEST_ONLY_SPEC.code


def test_snapshot_is_ordered_even_if_spec_order_is_not():
    spec = TeamFormatSpec("UNSORTED", 1, "乱序输入", 1, (R3, R1, R2))
    assert [r["sequence"] for r in team_formats.snapshot_dict(spec)["rubbers"]] == [1, 2, 3]
    assert [r["sequence"] for r in team_formats.build_rubber_skeleton(spec)] == [1, 2, 3]


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("", "快照文本为空"),
        ("{not json", "不是合法 JSON"),
        ("{}", "缺少 rubbers"),
        ('{"snapshot_version": 99, "rubbers": []}', "不支持的赛制快照版本"),
        (
            '{"code":"X","version":1,"display_name":"x","rubbers_to_win":1,'
            '"rubbers":[{"sequence":1,"rubber_type":"SINGLES","home_slots":"H1","away_slots":["A1"]}]}',
            "必须是字符串列表",
        ),
        (
            '{"code":"X","version":1,"display_name":"x","rubbers_to_win":2,'
            '"rubbers":[{"sequence":1,"rubber_type":"SINGLES","home_slots":["H1"],"away_slots":["A1"]}]}',
            "只定义了 1 盘",
        ),
    ],
)
def test_broken_snapshots_are_rejected(raw, fragment):
    with pytest.raises(team_formats.TeamFormatError) as excinfo:
        team_formats.load_snapshot(raw)
    assert fragment in str(excinfo.value)


def test_build_rubber_skeleton_marks_pending_and_keeps_slots():
    skeleton = team_formats.build_rubber_skeleton(TEST_ONLY_SPEC)
    assert [item["sequence"] for item in skeleton] == [1, 2, 3]
    assert {item["status"] for item in skeleton} == {TeamRubberStatus.PENDING.value}
    assert skeleton[0] == {
        "sequence": 1,
        "rubber_type": "SINGLES",
        "home_slots": ["H1"],
        "away_slots": ["A1"],
        "status": "PENDING",
    }
    assert skeleton[2]["home_slots"] == ["H3", "H4"]


# --------------------------------------------------------- TeamTie 创建与读取

def test_create_and_read_team_tie(conn):
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"])

    assert tie["stage"] == MatchStage.GROUP.value
    assert tie["status"] == TeamTieStatus.WAITING.value
    assert (tie["team_a_score"], tie["team_b_score"]) == (0, 0)
    assert tie["winner_entry_id"] is None
    # 还没建骨架：赛制字段保持为空，不预填任何"默认赛制"
    assert (tie["format_code"], tie["format_version"], tie["format_snapshot"]) == (None, None, None)

    detail = tie_service.get_team_tie(conn, tid, tie["id"])
    assert detail["rubbers"] == []
    assert [t["id"] for t in tie_service.list_team_ties(conn, tid)] == [tie["id"]]


def test_team_tie_validations(conn):
    tid = _team_tournament(conn, players=7)  # 留一名没进队伍的选手，用于"非 TEAM 实体"用例
    a, b = _two_teams(conn, tid)
    players = repo.list_players(conn, tid)
    free_player = next(p for p in players if p["id"] not in {m["player_id"] for m in a["members"] + b["members"]})

    with pytest.raises(tie_service.TeamTieError) as same:
        tie_service.create_team_tie(conn, tid, a["id"], a["id"])
    assert same.value.code == 422

    with pytest.raises(tie_service.TeamTieError) as unknown:
        tie_service.create_team_tie(conn, tid, a["id"], 987654)
    assert unknown.value.code == 404

    other = _team_tournament(conn)
    foreign_players = repo.list_players(conn, other)
    foreign_team = teams_service.create_team_entry(conn, other, "外部队", [foreign_players[0]["id"]])
    with pytest.raises(tie_service.TeamTieError) as cross:
        tie_service.create_team_tie(conn, tid, a["id"], foreign_team["id"])
    assert cross.value.code == 404

    # 非 TEAM 的参赛实体不能参加团体对抗
    stray = repo.create_entry(conn, tid, EventType.SINGLES.value, "误入实体", 0, [free_player["id"]])
    conn.commit()
    with pytest.raises(tie_service.TeamTieError) as not_team:
        tie_service.create_team_tie(conn, tid, a["id"], stray["id"])
    assert not_team.value.code == 409

    with pytest.raises(tie_service.TeamTieError) as bad_stage:
        tie_service.create_team_tie(conn, tid, a["id"], b["id"], stage="LEAGUE")
    assert bad_stage.value.code == 422
    with pytest.raises(tie_service.TeamTieError) as group_in_knockout:
        tie_service.create_team_tie(conn, tid, a["id"], b["id"], stage="KNOCKOUT", group_id=1)
    assert group_in_knockout.value.code == 422
    with pytest.raises(tie_service.TeamTieError) as bad_round:
        tie_service.create_team_tie(conn, tid, a["id"], b["id"], round_num=0)
    assert bad_round.value.code == 422

    with pytest.raises(tie_service.TeamTieError) as missing_tournament:
        tie_service.create_team_tie(conn, 999999, a["id"], b["id"])
    assert missing_tournament.value.code == 404
    singles = repo.create_tournament(conn, "单打赛", "2026-05-02", 4, 2, 1, event_type="SINGLES")
    conn.commit()
    with pytest.raises(tie_service.TeamTieError) as wrong_event:
        tie_service.create_team_tie(conn, singles["id"], a["id"], b["id"])
    assert wrong_event.value.code == 409
    assert "TEAM" in str(wrong_event.value)


def test_team_tie_group_membership(conn):
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    group = repo.create_group(conn, tid, "A组", 0)
    conn.commit()

    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"], group_id=group["id"])
    assert tie["group_id"] == group["id"]

    other = _team_tournament(conn)
    foreign_group = repo.create_group(conn, other, "别组", 0)
    conn.commit()
    with pytest.raises(tie_service.TeamTieError) as cross_group:
        tie_service.create_team_tie(conn, tid, a["id"], b["id"], group_id=foreign_group["id"])
    assert cross_group.value.code == 404


def test_get_and_list_team_tie_errors(conn):
    tid = _team_tournament(conn)
    with pytest.raises(tie_service.TeamTieError) as missing:
        tie_service.get_team_tie(conn, tid, 987654)
    assert missing.value.code == 404

    other = _team_tournament(conn)
    a, b = _two_teams(conn, other)
    tie = tie_service.create_team_tie(conn, other, a["id"], b["id"])
    with pytest.raises(tie_service.TeamTieError) as wrong_tournament:
        tie_service.get_team_tie(conn, tid, tie["id"])
    assert wrong_tournament.value.code == 404


# ------------------------------------------------------------------ 骨架构建

def test_skeleton_requires_a_registered_format(conn):
    """生产注册表为空：任何建盘请求都必须 422，而且不留下半个骨架。"""
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"])

    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.build_rubber_skeleton(conn, tid, tie["id"], "OLYMPIC")
    assert excinfo.value.code == 422
    assert repo.list_team_rubbers(conn, tie["id"]) == []
    assert repo.get_team_tie(conn, tie["id"])["format_code"] is None


def test_skeleton_freezes_format_and_creates_no_match(conn, test_only_format):
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"])

    detail = tie_service.build_rubber_skeleton(conn, tid, tie["id"], TEST_ONLY_SPEC.code)

    assert detail["format_code"] == TEST_ONLY_SPEC.code
    assert detail["format_version"] == TEST_ONLY_SPEC.version
    # 快照必须能原样还原成规格（赛事进行中注册表升级也不会改写历史）
    assert team_formats.load_snapshot(detail["format_snapshot"]) == TEST_ONLY_SPEC

    assert [r["sequence"] for r in detail["rubbers"]] == [1, 2, 3]
    assert [[r["home_slots"], r["away_slots"]] for r in detail["rubbers"]] == [
        [["H1"], ["A1"]],
        [["H2"], ["A2"]],
        [["H3", "H4"], ["A3", "A4"]],
    ]
    assert {r["status"] for r in detail["rubbers"]} == {TeamRubberStatus.PENDING.value}
    # A3 边界：一盘不创建 Match，match_id 保持 NULL
    assert {r["match_id"] for r in detail["rubbers"]} == {None}
    assert conn.execute("SELECT COUNT(*) FROM matches WHERE tournament_id = ?", (tid,)).fetchone()[0] == 0
    # 对抗本身也没有比分/胜者（状态机属于 A4）
    stored = repo.get_team_tie(conn, tie["id"])
    assert (stored["team_a_score"], stored["team_b_score"], stored["winner_entry_id"]) == (0, 0, None)
    assert stored["status"] == TeamTieStatus.WAITING.value


def test_skeleton_rebuild_guard(conn, test_only_format):
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"])
    tie_service.build_rubber_skeleton(conn, tid, tie["id"], TEST_ONLY_SPEC.code)

    with pytest.raises(tie_service.TeamTieError) as exists:
        tie_service.build_rubber_skeleton(conn, tid, tie["id"], TEST_ONLY_SPEC.code)
    assert exists.value.code == 409
    assert "已生成 3 盘骨架" in str(exists.value)

    rebuilt = tie_service.build_rubber_skeleton(
        conn, tid, tie["id"], TEST_ONLY_SPEC.code, replace=True
    )
    assert len(rebuilt["rubbers"]) == 3
    assert {r["status"] for r in rebuilt["rubbers"]} == {TeamRubberStatus.PENDING.value}

    # 只要有一盘已经开打（status 或 match_id 变化），就不允许重建
    first = rebuilt["rubbers"][0]
    conn.execute(
        "UPDATE team_rubbers SET status = 'PLAYING' WHERE id = ?", (first["id"],)
    )
    conn.commit()
    with pytest.raises(tie_service.TeamTieError) as started:
        tie_service.build_rubber_skeleton(conn, tid, tie["id"], TEST_ONLY_SPEC.code, replace=True)
    assert started.value.code == 409
    assert "开打" in str(started.value)
    assert len(repo.list_team_rubbers(conn, tie["id"])) == 3  # 原骨架没被破坏


def test_skeleton_unknown_tie_and_tournament(conn, test_only_format):
    tid = _team_tournament(conn)
    with pytest.raises(tie_service.TeamTieError) as missing_tie:
        tie_service.build_rubber_skeleton(conn, tid, 987654, TEST_ONLY_SPEC.code)
    assert missing_tie.value.code == 404
    with pytest.raises(tie_service.TeamTieError) as missing_tournament:
        tie_service.build_rubber_skeleton(conn, 999999, 1, TEST_ONLY_SPEC.code)
    assert missing_tournament.value.code == 404


def test_corrupted_slot_json_is_reported_not_silently_dropped(conn, test_only_format):
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"])
    detail = tie_service.build_rubber_skeleton(conn, tid, tie["id"], TEST_ONLY_SPEC.code)
    conn.execute(
        "UPDATE team_rubbers SET home_slots_json = ? WHERE id = ?",
        ("{坏数据", detail["rubbers"][0]["id"]),
    )
    conn.commit()
    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.get_team_tie(conn, tid, tie["id"])
    assert excinfo.value.code == 500
    assert "位置数据已损坏" in str(excinfo.value)


# ------------------------------------------------- 团体赛不进入单打引擎（守卫）

def test_individual_engine_guards_reject_team(conn):
    tid = _team_tournament(conn)
    _two_teams(conn, tid)

    with pytest.raises(matches_service.TournamentStageError) as group:
        matches_service.generate_group_matches(conn, tid)
    assert "团体赛" in str(group.value)

    with pytest.raises(knockout_service.KnockoutError) as knockout:
        knockout_service.generate_knockout(conn, tid)
    assert "团体赛" in str(knockout.value)

    with pytest.raises(matches_service.TournamentStageError) as demo:
        matches_service.finish_group_stage(conn, tid)
    assert "团体赛" in str(demo.value)

    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


# ------------------------------------------------------------------- 导出

def test_export_includes_team_tables_and_stays_read_only(conn, test_only_format):
    tid = _team_tournament(conn)
    a, b = _two_teams(conn, tid)
    tie = tie_service.create_team_tie(conn, tid, a["id"], b["id"])
    tie_service.build_rubber_skeleton(conn, tid, tie["id"], TEST_ONLY_SPEC.code)

    before = {
        "ties": [dict(r) for r in conn.execute("SELECT * FROM team_ties ORDER BY id")],
        "rubbers": [dict(r) for r in conn.execute("SELECT * FROM team_rubbers ORDER BY id")],
    }
    exported = tournament_export.get_export(conn, tid)
    after = {
        "ties": [dict(r) for r in conn.execute("SELECT * FROM team_ties ORDER BY id")],
        "rubbers": [dict(r) for r in conn.execute("SELECT * FROM team_rubbers ORDER BY id")],
    }
    assert before == after  # 导出是纯读操作

    assert exported["schema_version"] == "1.0"  # 追加字段不改变结构版本
    assert [t["id"] for t in exported["team_ties"]] == [tie["id"]]
    assert len(exported["team_rubbers"]) == 3
    assert {r["match_id"] for r in exported["team_rubbers"]} == {None}
    assert json.loads(exported["team_rubbers"][2]["home_slots_json"]) == ["H3", "H4"]
    assert exported["team_ties"][0]["format_code"] == TEST_ONLY_SPEC.code
    # 队伍仍然出现在普通 entries 里（不重复导出第二份名单）
    assert {e["display_name"] for e in exported["entries"]} == {"A队", "B队"}
    assert all(e["entry_type"] == "TEAM" for e in exported["entries"])


def test_export_of_singles_tournament_has_empty_team_arrays(conn):
    tid = repo.create_tournament(conn, "单打导出", "2026-05-01", 2, 2, 1)["id"]
    repo.create_tables_for_tournament(conn, tid, 2)
    for index in range(4):
        repo.add_player(conn, tid, f"P{index + 1}", None)
    conn.commit()
    exported = tournament_export.get_export(conn, tid)
    assert exported["team_ties"] == []
    assert exported["team_rubbers"] == []
    assert exported["schema_version"] == "1.0"


# ------------------------------------------------------------------- API 层

def _api_team_tournament(client, players: int = 6) -> tuple[int, list[int]]:
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "团体赛领域 API",
            "date": "2026-05-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 1,
            "event_type": "TEAM",
            "operation_mode": "DEMO",
        },
    ).json()["id"]
    ids = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, players + 1)
    ]
    return tid, ids


def _api_teams(client, tid: int, player_ids: list[int]) -> tuple[int, int]:
    half = len(player_ids) // 2
    a = client.post(
        f"/api/tournaments/{tid}/teams",
        json={"display_name": "A队", "member_ids": player_ids[:half]},
    ).json()["id"]
    b = client.post(
        f"/api/tournaments/{tid}/teams",
        json={"display_name": "B队", "member_ids": player_ids[half:]},
    ).json()["id"]
    return a, b


def test_team_tie_api_flow_and_production_format_gate(client, test_only_format):
    tid, player_ids = _api_team_tournament(client)
    a, b = _api_teams(client, tid, player_ids)

    created = client.post(
        f"/api/tournaments/{tid}/team-ties", json={"entry_a_id": a, "entry_b_id": b}
    )
    assert created.status_code == 201, created.text
    tie = created.json()
    assert tie["entry_a_id"] == a and tie["entry_b_id"] == b
    assert tie["status"] == "WAITING"
    assert tie["format_code"] is None

    listed = client.get(f"/api/tournaments/{tid}/team-ties")
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [tie["id"]]

    detail = client.get(f"/api/tournaments/{tid}/team-ties/{tie['id']}")
    assert detail.status_code == 200
    assert detail.json()["rubbers"] == []

    assert client.post(
        f"/api/tournaments/{tid}/team-ties", json={"entry_a_id": a, "entry_b_id": a}
    ).status_code == 422
    assert client.get(f"/api/tournaments/{tid}/team-ties/999999").status_code == 404
    assert client.get("/api/tournaments/999999/team-ties").status_code == 404

    # 未登记的赛制（例如臆造的"奥运赛制"）→ 422，且不落任何盘
    invented = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie['id']}/rubber-skeleton",
        json={"format_code": "OLYMPIC"},
    )
    assert invented.status_code == 422
    assert "未知的团体赛赛制" in invented.json()["detail"]
    assert client.get(f"/api/tournaments/{tid}/team-ties/{tie['id']}").json()["rubbers"] == []

    built = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie['id']}/rubber-skeleton",
        json={"format_code": test_only_format.code},
    )
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["format_code"] == test_only_format.code
    assert [r["sequence"] for r in body["rubbers"]] == [1, 2, 3]
    assert all(r["match_id"] is None and r["status"] == "PENDING" for r in body["rubbers"])
    assert body["rubbers"][2]["home_slots"] == ["H3", "H4"]

    # 已经生成过 → 409；显式要求重建才允许
    again = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie['id']}/rubber-skeleton",
        json={"format_code": test_only_format.code},
    )
    assert again.status_code == 409
    replaced = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie['id']}/rubber-skeleton",
        json={"format_code": test_only_format.code, "replace": True},
    )
    assert replaced.status_code == 200
    assert len(replaced.json()["rubbers"]) == 3

    # 团体赛不能走普通比赛的生成接口
    assert client.post(f"/api/tournaments/{tid}/generate-group-matches").status_code == 409
    assert client.post(f"/api/tournaments/{tid}/generate-knockout").status_code == 409
    # 也没有产生任何 Match
    assert client.get(f"/api/tournaments/{tid}/matches").json() == []

    # 导出里能看到对抗与盘骨架
    export = client.get(f"/api/tournaments/{tid}/export").json()
    assert len(export["team_ties"]) == 1
    assert len(export["team_rubbers"]) == 3
    assert {r["match_id"] for r in export["team_rubbers"]} == {None}
