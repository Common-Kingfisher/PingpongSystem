"""A5：生产团体赛赛制 `LOCAL_CLASSIC_5_V1` —— 注册、建盘、Runtime 契约与快照历史。

本文件与 `test_team_runtime.py` 的分工：
- `test_team_runtime.py` 用 `TEST_ONLY_*` 证明**引擎与赛制无关**（换规格不改引擎）；
- 本文件证明**真实生产赛制**可以端到端驱动 PR #20 的 Runtime，也就是 Definition of Done
  的最后一块：真实赛事不再需要测试赛制才能建盘开赛。

必须锁死的边界：
1. 生产注册表里只有组织者确认过的版本化模板（当前 `LOCAL_CLASSIC_5_V1`），
   `TEST_ONLY_*` 不得出现，臆造的 "OLYMPIC" / "ITTF_CLASSIC" 之类的名字永远不存在；
2. `LOCAL_CLASSIC_5_V1` 只冻结"盘数 / 盘类型顺序 / 获胜所需盘数"，
   不冻结任何选手角色、兼项、替补与盘序强制规则；位置代号是中性的 `HOME_R*` / `AWAY_R*`；
3. 快照是历史真相：注册表以后被改、被换、被删，已创建的对抗仍按 `format_snapshot` 解释；
4. 对抗一旦进入 Runtime（有盘 READY/PLAYING/FINISHED/SKIPPED），就再也不能换赛制或重建骨架。
"""

import json
import re

import pytest

from app import repository as repo
from app.domain import team_formats as tf
from app.services import entries as entries_service
from app.services import team_runtime as runtime
from app.services import team_ties as ties_service
from app.services import teams as teams_service

FORMAT_CODE = "LOCAL_CLASSIC_5_V1"
FORMAT_NAME = "经典五盘三胜团体赛"
EXPECTED_TYPES = ["SINGLES", "SINGLES", "DOUBLES", "SINGLES", "SINGLES"]
S = "SINGLES"
D = "DOUBLES"

#: 测试专用赛制（非生产规则）：只用来验证"未登记/未暴露"的边界。
TEST_ONLY_SPEC = tf.TeamFormatSpec(
    code="TEST_ONLY_FORMAT_V1_SPEC",
    version=1,
    display_name="测试用赛制（非生产规则）",
    rubbers_to_win=1,
    rubbers=(tf.RubberTemplate(1, S, ("T1",), ("U1",)),),
)


def _production_spec() -> tf.TeamFormatSpec:
    return tf.get_format_spec(FORMAT_CODE)


# ------------------------------------------------------------------ 夹具与工具

class Setup:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _setup(conn, *, players: int = 8, format_code: str = FORMAT_CODE) -> Setup:
    """TEAM 赛事 → 选手 → A/B 两队 → 确认名单 → 对抗 → 生产赛制建盘。"""
    tournament = repo.create_tournament(
        conn, f"生产赛制 {format_code}", "2026-07-01", 4, 1, 1,
        event_type="TEAM", operation_mode="DEMO",
    )
    tid = tournament["id"]
    roster = [
        repo.add_player(conn, tid, f"P{index:02d}", "计算机学院", 1000 + index)
        for index in range(1, players + 1)
    ]
    conn.commit()
    half = len(roster) // 2
    team_a = teams_service.create_team_entry(
        conn, tid, "A队", [p["id"] for p in roster[:half]]
    )
    team_b = teams_service.create_team_entry(
        conn, tid, "B队", [p["id"] for p in roster[half:]]
    )
    entries_service.confirm_roster(conn, tid)
    tie = ties_service.create_team_tie(conn, tid, team_a["id"], team_b["id"])
    built = ties_service.build_rubber_skeleton(conn, tid, tie["id"], format_code)
    view = runtime.runtime_view(conn, tid, tie["id"])
    return Setup(
        tournament_id=tid,
        tie_id=tie["id"],
        team_a=team_a["id"],
        team_b=team_b["id"],
        built=built,
        view=view,
        rubbers=[r["id"] for r in view["rubbers"]],
        home_ids=[m["player_id"] for m in view["home_team"]["members"]],
        away_ids=[m["player_id"] for m in view["away_team"]["members"]],
    )


def _play(conn, s: Setup, index: int, home_score: int, away_score: int) -> dict:
    """打完一盘：按盘型取够人数 → lineup → start → score，返回最新运行态。"""
    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    rubber = view["rubbers"][index]
    need = 2 if rubber["rubber_type"] == D else 1
    runtime.set_lineup(
        conn, s.tournament_id, s.tie_id, rubber["id"],
        s.home_ids[:need], s.away_ids[:need],
    )
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber["id"])
    return runtime.record_rubber_score(
        conn, s.tournament_id, s.tie_id, rubber["id"], home_score, away_score
    )


# ------------------------------------------------- Test 1：生产注册表与规格本身

def test_production_registry_exposes_only_confirmed_templates():
    assert set(tf.PRODUCTION_FORMATS) == {FORMAT_CODE}
    # 测试赛制绝不能混进生产注册表，否则真实 API 会暴露它
    assert tf.PRODUCTION_FORMATS.get(TEST_ONLY_SPEC.code) is None
    assert not [c for c in tf.PRODUCTION_FORMATS if c.startswith("TEST_ONLY")]
    # 容易被读成"官方认证"的名字一律不存在
    for invented in ("ITTF_OFFICIAL", "ITTF_CLASSIC_V1", "OLYMPIC", "NATIONAL_STANDARD",
                     "OFFICIAL_CLASSIC"):
        with pytest.raises(tf.TeamFormatError):
            tf.get_format_spec(invented)


def test_classic_5_v1_spec_is_valid_and_versioned():
    spec = _production_spec()
    assert spec.code == FORMAT_CODE
    assert spec.version == 1
    assert spec.display_name == FORMAT_NAME
    assert spec.rubbers_to_win == 3
    assert len(spec.rubbers) == 5
    # 注册即通过既有校验（没有为了让它通过而放松 validation）
    tf.validate_format_spec(spec)
    assert tf.PRODUCTION_FORMATS[FORMAT_CODE] is spec


def test_production_spec_rejects_invalid_versions_of_itself():
    """同一份字段被改坏时必须报错，而不是"能注册就行"。"""
    broken = [
        # 赢的盘数比总盘数还多
        tf.TeamFormatSpec(FORMAT_CODE, 1, FORMAT_NAME, 6, _production_spec().rubbers),
        # 盘类型不合法
        tf.TeamFormatSpec(
            FORMAT_CODE, 1, FORMAT_NAME, 3,
            (tf.RubberTemplate(1, "TEAM", ("HOME_R1",), ("AWAY_R1",)),),
        ),
        # 双打只给一个位置
        tf.TeamFormatSpec(
            FORMAT_CODE, 1, FORMAT_NAME, 1,
            (tf.RubberTemplate(1, D, ("HOME_R1",), ("AWAY_R1", "AWAY_R2")),),
        ),
        # 盘序不连续
        tf.TeamFormatSpec(
            FORMAT_CODE, 1, FORMAT_NAME, 1,
            (tf.RubberTemplate(2, S, ("HOME_R2",), ("AWAY_R2",)),),
        ),
    ]
    for spec in broken:
        with pytest.raises(tf.TeamFormatError):
            tf.validate_format_spec(spec)

    with pytest.raises(tf.TeamFormatError):
        tf.register_format_spec(broken[0])
    # 注册失败不得污染生产注册表
    assert tf.PRODUCTION_FORMATS[FORMAT_CODE] is _production_spec()


# ------------------------------------------------- Test 2：盘序与位置代号（已冻结的边界）

def test_rubber_sequence_and_types_are_frozen_in_order():
    spec = _production_spec()
    assert [r.sequence for r in spec.rubbers] == [1, 2, 3, 4, 5]
    assert [r.rubber_type for r in spec.rubbers] == EXPECTED_TYPES
    assert spec.rubbers_to_win == 3

    skeleton = tf.build_rubber_skeleton(spec)
    assert [item["sequence"] for item in skeleton] == [1, 2, 3, 4, 5]
    assert [item["rubber_type"] for item in skeleton] == EXPECTED_TYPES
    assert {item["status"] for item in skeleton} == {"PENDING"}
    # 位置数只由"单打 1 / 双打 2"的结构含义决定
    assert [(len(i["home_slots"]), len(i["away_slots"])) for i in skeleton] == [
        (1, 1), (1, 1), (2, 2), (1, 1), (1, 1)
    ]


def test_slots_are_neutral_positions_not_fixed_player_roles():
    """位置代号只是"第几盘的第几个位置"，不隐含 A/B/C/X/Y/Z 这类角色映射。

    这类角色代号会暗示"某个固定角色 = 某个位置的固定选手"，而角色映射恰恰是
    本 PR **故意没有冻结**的规则，因此生产赛制里不得出现。
    """
    pattern = re.compile(r"^(HOME|AWAY)_R[1-9][0-9]*(_[12])?$")
    spec = _production_spec()
    for rubber in spec.rubbers:
        for slot in tuple(rubber.home_slots) + tuple(rubber.away_slots):
            assert pattern.match(slot), f"位置代号必须是中性位置标识：{slot}"
        # 单打位置带盘序；双打位置带盘序与边内序号
        for index, slot in enumerate(rubber.home_slots, start=1):
            if len(rubber.home_slots) == 1:
                assert slot == f"HOME_R{rubber.sequence}"
            else:
                assert slot == f"HOME_R{rubber.sequence}_{index}"
        for index, slot in enumerate(rubber.away_slots, start=1):
            if len(rubber.away_slots) == 1:
                assert slot == f"AWAY_R{rubber.sequence}"
            else:
                assert slot == f"AWAY_R{rubber.sequence}_{index}"
    # 反例：角色式代号不满足该模式（保证上面的断言真的有效）
    for role_slot in ("A", "B1", "X2", "H3", "HOME_1"):
        assert not pattern.match(role_slot), role_slot


# ------------------------------------------------- Test 3：真实生产建盘（服务层）

def test_real_production_skeleton_builds_five_rubbers(conn):
    s = _setup(conn)
    detail = s.built

    assert detail["format_code"] == FORMAT_CODE
    assert detail["format_version"] == 1
    assert tf.load_snapshot(detail["format_snapshot"]) == _production_spec()
    assert [r["sequence"] for r in detail["rubbers"]] == [1, 2, 3, 4, 5]
    assert [r["rubber_type"] for r in detail["rubbers"]] == EXPECTED_TYPES
    assert detail["rubbers"][2]["home_slots"] == ["HOME_R3_1", "HOME_R3_2"]
    assert detail["rubbers"][2]["away_slots"] == ["AWAY_R3_1", "AWAY_R3_2"]
    assert {r["status"] for r in detail["rubbers"]} == {"PENDING"}
    assert len(repo.list_team_rubbers(conn, s.tie_id)) == 5


def test_production_skeleton_creates_no_match(conn):
    """A5 仍然不把一盘做成普通 Match：match_id 恒为 NULL。"""
    s = _setup(conn)
    assert {r["match_id"] for r in s.view["rubbers"]} == {None}
    assert conn.execute(
        "SELECT COUNT(*) FROM matches WHERE tournament_id = ?", (s.tournament_id,)
    ).fetchone()[0] == 0


def test_production_skeleton_persists_format_columns(conn):
    s = _setup(conn)
    stored = repo.get_team_tie(conn, s.tie_id)
    assert stored["format_code"] == FORMAT_CODE
    assert stored["format_version"] == 1
    assert json.loads(stored["format_snapshot"])["rubbers_to_win"] == 3
    assert stored["format_snapshot"] == tf.dump_snapshot(_production_spec())


# ------------------------------------------------- Test 4：Runtime 契约

def test_runtime_contract_exposes_production_format(conn):
    s = _setup(conn)
    view = s.view

    assert view["target_wins"] == 3
    assert view["format"]["code"] == FORMAT_CODE
    assert view["format"]["version"] == 1
    assert view["format"]["display_name"] == FORMAT_NAME
    assert view["format"]["rubbers_to_win"] == 3
    assert len(view["rubbers"]) == 5
    # 与 A3 存储字段同源，不出现两个真相
    assert view["format_code"] == FORMAT_CODE
    assert view["format_version"] == 1
    assert view["status"] == "WAITING"
    assert (view["home_score"], view["away_score"]) == (0, 0)
    assert [r["status"] for r in view["rubbers"]] == ["PENDING"] * 5


def test_runtime_contract_is_identical_between_service_and_detail_paths(conn):
    s = _setup(conn)
    assert runtime.runtime_view(conn, s.tournament_id, s.tie_id)["format"] == s.view["format"]


# ------------------------------------------------- Test 5：生产赛制 Runtime E2E（本 PR 最重要）

def test_production_format_runtime_end_to_end(conn):
    """真实生产赛制跑完整闭环：3 盘到手 → 对抗结束 → 剩余盘 SKIPPED。"""
    s = _setup(conn)
    assert s.view["target_wins"] == 3
    assert [r["status"] for r in s.view["rubbers"]] == ["PENDING"] * 5

    # 第 1 盘（单打）主队胜
    view = _play(conn, s, 0, 2, 0)
    assert (view["home_score"], view["away_score"]) == (1, 0)
    assert view["status"] == "PLAYING"
    assert view["rubbers"][0]["winner_entry_id"] == s.team_a

    # 第 2 盘（单打）客队胜
    view = _play(conn, s, 1, 0, 2)
    assert (view["home_score"], view["away_score"]) == (1, 1)
    assert view["rubbers"][1]["winner_entry_id"] == s.team_b

    # 第 3 盘是双打盘：每边 2 人
    view = _play(conn, s, 2, 2, 1)
    assert (view["home_score"], view["away_score"]) == (2, 1)
    assert len(view["rubbers"][2]["home_player_ids"]) == 2
    assert len(view["rubbers"][2]["away_player_ids"]) == 2

    # 第 4 盘主队达到 3 胜 → 对抗自动结束
    view = _play(conn, s, 3, 2, 0)
    assert (view["home_score"], view["away_score"]) == (3, 1)
    assert view["status"] == "FINISHED"
    assert view["winner_entry_id"] == s.team_a
    assert view["finished_at"] is not None
    assert [r["status"] for r in view["rubbers"]] == [
        "FINISHED", "FINISHED", "FINISHED", "FINISHED", "SKIPPED",
    ]
    assert view["permissions"] == {
        "can_edit_lineup": False,
        "can_confirm_lineup": False,
        "can_start": False,
        "can_record_score": False,
        "can_revise_score": False,
    }
    # 落库口径与运行态一致；仍然没有 Match
    stored = repo.get_team_tie(conn, s.tie_id)
    assert (stored["team_a_score"], stored["team_b_score"]) == (3, 1)
    assert stored["winner_entry_id"] == s.team_a
    assert stored["status"] == "FINISHED"
    assert stored["format_code"] == FORMAT_CODE
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_production_format_can_finish_5th_rubber_when_no_early_end(conn):
    """2:2 之后第 5 盘必须能正常打——提前结束是"达到 3 胜"，不是"打完 4 盘"。"""
    s = _setup(conn)
    _play(conn, s, 0, 2, 0)   # 主队 1
    _play(conn, s, 1, 0, 2)   # 客队 1
    _play(conn, s, 2, 2, 0)   # 主队 2（双打）
    view = _play(conn, s, 3, 0, 2)  # 客队 2
    assert (view["home_score"], view["away_score"]) == (2, 2)
    assert view["status"] == "PLAYING"
    assert view["rubbers"][4]["status"] == "PENDING"

    view = _play(conn, s, 4, 2, 1)
    assert (view["home_score"], view["away_score"]) == (3, 2)
    assert view["status"] == "FINISHED"
    assert view["winner_entry_id"] == s.team_a
    assert [r["status"] for r in view["rubbers"]] == ["FINISHED"] * 5


# ------------------------------------------------- Test 6：快照是历史真相

def test_snapshot_survives_registry_rewrite(conn, monkeypatch):
    """注册表里 V1 被换成别的含义后，已创建的对抗仍按原快照解释。"""
    s = _setup(conn)
    assert s.view["target_wins"] == 3

    # 在测试作用域内把 V1 "偷偷改坏"：7 盘、先赢 4 盘、显示名也换了
    rewritten = tf.TeamFormatSpec(
        code=FORMAT_CODE,
        version=1,
        display_name="被改写过的同名赛制",
        rubbers_to_win=4,
        rubbers=tuple(
            tf.RubberTemplate(i, S, (f"HOME_X{i}",), (f"AWAY_X{i}",)) for i in range(1, 8)
        ),
    )
    monkeypatch.setitem(tf.PRODUCTION_FORMATS, FORMAT_CODE, rewritten)
    assert tf.get_format_spec(FORMAT_CODE).rubbers_to_win == 4  # 注册表确实被改了

    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    assert view["target_wins"] == 3
    assert view["format"]["display_name"] == FORMAT_NAME
    assert view["format"]["rubbers_to_win"] == 3
    assert len(view["rubbers"]) == 5
    assert [r["rubber_type"] for r in view["rubbers"]] == EXPECTED_TYPES

    # 赛程也照旧可跑（结束判定仍按快照里的 3 胜）
    view = _play(conn, s, 0, 2, 0)
    view = _play(conn, s, 1, 2, 0)
    view = _play(conn, s, 2, 2, 0)
    assert view["status"] == "FINISHED"
    assert view["winner_entry_id"] == s.team_a
    assert [r["status"] for r in view["rubbers"]] == [
        "FINISHED", "FINISHED", "FINISHED", "SKIPPED", "SKIPPED",
    ]


def test_snapshot_survives_registry_replacement_and_removal(conn, monkeypatch):
    """将来新增 V2（甚至把 V1 从清单里下线）时，历史对抗不受影响。"""
    s = _setup(conn)

    v2 = tf.TeamFormatSpec(
        code="LOCAL_CLASSIC_5_V2",
        version=2,
        display_name="经典五盘三胜团体赛（第二版）",
        rubbers_to_win=3,
        rubbers=tuple(
            tf.RubberTemplate(i, S, (f"HOME_V2_{i}",), (f"AWAY_V2_{i}",)) for i in range(1, 6)
        ),
    )
    with monkeypatch.context() as mp:
        mp.setitem(tf.PRODUCTION_FORMATS, v2.code, v2)
        assert (s.view["format"]["code"], s.view["target_wins"]) == (FORMAT_CODE, 3)
        assert s.view["format"]["version"] == 1
        assert runtime.runtime_view(conn, s.tournament_id, s.tie_id)["target_wins"] == 3

    # 把 V1 从注册表里彻底移除：历史对抗仍然可读、可跑
    with monkeypatch.context() as mp:
        mp.delitem(tf.PRODUCTION_FORMATS, FORMAT_CODE)
        with pytest.raises(tf.TeamFormatError):
            tf.get_format_spec(FORMAT_CODE)
        view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
        assert view["target_wins"] == 3
        assert view["format"]["code"] == FORMAT_CODE
        assert len(view["rubbers"]) == 5
        view = _play(conn, s, 0, 2, 0)
        assert view["home_score"] == 1

    # monkeypatch 退出后注册表恢复原状，不污染全局测试环境
    assert tf.PRODUCTION_FORMATS[FORMAT_CODE] is _production_spec()


def test_snapshot_roundtrip_is_stable():
    spec = _production_spec()
    text = tf.dump_snapshot(spec)
    assert tf.load_snapshot(text) == spec
    assert tf.load_snapshot(tf.dump_snapshot(tf.load_snapshot(text))) == spec
    assert json.loads(text)["code"] == FORMAT_CODE


# ------------------------------------------------- Test 7 / 8：拒绝路径

def test_unknown_format_is_422_and_leaves_no_rubber(conn):
    tid = repo.create_tournament(
        conn, "未知赛制", "2026-07-02", 4, 1, 1, event_type="TEAM", operation_mode="DEMO"
    )["id"]
    for index in range(1, 5):
        repo.add_player(conn, tid, f"P{index}", "计算机学院", 1000 + index)
    conn.commit()
    players = repo.list_players(conn, tid)
    a = teams_service.create_team_entry(conn, tid, "A队", [p["id"] for p in players[:2]])
    b = teams_service.create_team_entry(conn, tid, "B队", [p["id"] for p in players[2:]])
    entries_service.confirm_roster(conn, tid)
    tie = ties_service.create_team_tie(conn, tid, a["id"], b["id"])

    for code in ("UNKNOWN_FORMAT", "OLYMPIC", "itTF_classic_v1", TEST_ONLY_SPEC.code, ""):
        with pytest.raises(ties_service.TeamTieError) as excinfo:
            ties_service.build_rubber_skeleton(conn, tid, tie["id"], code)
        assert excinfo.value.code == 422, code
    assert repo.list_team_rubbers(conn, tie["id"]) == []
    assert repo.get_team_tie(conn, tie["id"])["format_code"] is None


def test_non_team_tournament_rejects_production_format(conn):
    """单打/双打赛事不能建团体盘骨架（沿用 TeamTie service 既有契约：409）。"""
    for event_type in ("SINGLES", "DOUBLES"):
        tid = repo.create_tournament(
            conn, f"{event_type} 赛事", "2026-07-03", 4, 1, 1,
            event_type=event_type, operation_mode="DEMO",
        )["id"]
        for index in range(1, 5):
            repo.add_player(conn, tid, f"P{index}", "计算机学院", 1000 + index)
        conn.commit()

        with pytest.raises(ties_service.TeamTieError) as build:
            ties_service.build_rubber_skeleton(conn, tid, 1, FORMAT_CODE)
        assert build.value.code == 409
        assert event_type in str(build.value)

        with pytest.raises(ties_service.TeamTieError) as create:
            ties_service.create_team_tie(conn, tid, 1, 2)
        assert create.value.code == 409
    assert conn.execute("SELECT COUNT(*) FROM team_rubbers").fetchone()[0] == 0


# ------------------------------------------------- Test 9：重复建盘

def test_rebuild_is_refused_without_explicit_replace(conn):
    s = _setup(conn)
    with pytest.raises(ties_service.TeamTieError) as excinfo:
        ties_service.build_rubber_skeleton(conn, s.tournament_id, s.tie_id, FORMAT_CODE)
    assert excinfo.value.code == 409
    assert "已生成 5 盘骨架" in str(excinfo.value)
    # 拒绝之后仍然是 5 盘，没有变成 10 盘
    assert len(repo.list_team_rubbers(conn, s.tie_id)) == 5


def test_replace_is_allowed_only_before_any_rubber_starts(conn):
    s = _setup(conn)
    rebuilt = ties_service.build_rubber_skeleton(
        conn, s.tournament_id, s.tie_id, FORMAT_CODE, replace=True
    )
    assert len(rebuilt["rubbers"]) == 5
    assert {r["status"] for r in rebuilt["rubbers"]} == {"PENDING"}
    assert rebuilt["format_code"] == FORMAT_CODE
    assert len(repo.list_team_rubbers(conn, s.tie_id)) == 5


def test_replace_is_refused_when_tie_is_in_flight_but_rubbers_untouched(conn):
    """防御：即使盘被人为改回 PENDING，只要对抗已进入 Runtime 就绝不重建。"""
    s = _setup(conn)
    conn.execute("UPDATE team_ties SET status = 'PLAYING' WHERE id = ?", (s.tie_id,))
    conn.commit()
    with pytest.raises(ties_service.TeamTieError) as excinfo:
        ties_service.build_rubber_skeleton(
            conn, s.tournament_id, s.tie_id, FORMAT_CODE, replace=True
        )
    assert excinfo.value.code == 409
    assert len(repo.list_team_rubbers(conn, s.tie_id)) == 5


# ------------------------------------------------- Test 10：开赛后不能换赛制 / 重建

def test_format_cannot_change_or_rebuild_after_lineup_and_start(conn):
    s = _setup(conn)
    first = s.rubbers[0]

    runtime.set_lineup(
        conn, s.tournament_id, s.tie_id, first, s.home_ids[:1], s.away_ids[:1]
    )
    started = runtime.start_rubber(conn, s.tournament_id, s.tie_id, first)
    assert started["rubbers"][0]["status"] == "PLAYING"
    snapshot_before = repo.get_team_tie(conn, s.tie_id)["format_snapshot"]

    # 一个"另一个已注册赛制"，用来验证"换赛制"这条路也被封死
    other = tf.TeamFormatSpec(
        code="LOCAL_CLASSIC_5_V2",
        version=2,
        display_name="第二版赛制（仅本测试注册）",
        rubbers_to_win=1,
        rubbers=(tf.RubberTemplate(1, S, ("HOME_R1",), ("AWAY_R1",)),),
    )
    tf.validate_format_spec(other)
    tf.PRODUCTION_FORMATS[other.code] = other
    try:
        assert tf.get_format_spec(other.code) is other  # 确认它真的是"已注册"

        # 同一赛制重建（replace=False → 409；replace=True → 已开打，409）
        for replace in (False, True):
            with pytest.raises(ties_service.TeamTieError) as same:
                ties_service.build_rubber_skeleton(
                    conn, s.tournament_id, s.tie_id, FORMAT_CODE, replace=replace
                )
            assert same.value.code == 409

        # 换成一个已注册的短赛制（replace=True）→ 仍然 409，历史不能被改写
        with pytest.raises(ties_service.TeamTieError) as swapped:
            ties_service.build_rubber_skeleton(
                conn, s.tournament_id, s.tie_id, other.code, replace=True
            )
        assert swapped.value.code == 409

        # 未登记的 code 依然是 422（错误语义没有互相污染）
        with pytest.raises(ties_service.TeamTieError) as unknown:
            ties_service.build_rubber_skeleton(
                conn, s.tournament_id, s.tie_id, "UNKNOWN_FORMAT", replace=True
            )
        assert unknown.value.code == 422

        # 历史、盘、阵容、运行态全部没被破坏
        view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
        assert repo.get_team_tie(conn, s.tie_id)["format_snapshot"] == snapshot_before
        assert view["format"]["code"] == FORMAT_CODE
        assert view["target_wins"] == 3
        assert len(view["rubbers"]) == 5
        assert [r["rubber_type"] for r in view["rubbers"]] == EXPECTED_TYPES
        assert view["rubbers"][0]["status"] == "PLAYING"
        assert view["rubbers"][0]["home_player_ids"] == s.home_ids[:1]
        assert view["rubbers"][0]["away_player_ids"] == s.away_ids[:1]
        assert view["status"] == "PLAYING"
    finally:
        tf.PRODUCTION_FORMATS.pop(other.code, None)
    # 临时赛制已清掉，生产注册表回到原状
    assert set(tf.PRODUCTION_FORMATS) == {FORMAT_CODE}


# ------------------------------------------------- API 层 E2E（真实路由 / 真实载荷）

def _api_setup(client, *, players: int = 8, format_code: str = FORMAT_CODE):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "生产赛制 API",
            "date": "2026-07-04",
            "table_count": 4,
            "group_count": 1,
            "qualify_per_group": 1,
            "event_type": "TEAM",
            "operation_mode": "DEMO",
        },
    ).json()["id"]
    ids = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, players + 1)
    ]
    half = len(ids) // 2
    a = client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "A队", "member_ids": ids[:half]}
    ).json()["id"]
    b = client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "B队", "member_ids": ids[half:]}
    ).json()["id"]
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    tie = client.post(
        f"/api/tournaments/{tid}/team-ties", json={"entry_a_id": a, "entry_b_id": b}
    ).json()["id"]
    built = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubber-skeleton",
        json={"format_code": format_code},
    )
    assert built.status_code == 200, built.text
    return tid, tie, a, b, built.json()


def test_api_production_skeleton_endpoint(client):
    tid, tie, _a, _b, body = _api_setup(client)
    assert body["format"]["code"] == FORMAT_CODE
    assert body["format"]["version"] == 1
    assert body["format"]["display_name"] == FORMAT_NAME
    assert body["format"]["rubbers_to_win"] == 3
    assert body["target_wins"] == 3
    assert len(body["rubbers"]) == 5
    assert [r["sequence"] for r in body["rubbers"]] == [1, 2, 3, 4, 5]
    assert [r["rubber_type"] for r in body["rubbers"]] == EXPECTED_TYPES
    assert [r["home_slots"] for r in body["rubbers"]] == [
        ["HOME_R1"], ["HOME_R2"], ["HOME_R3_1", "HOME_R3_2"], ["HOME_R4"], ["HOME_R5"]
    ]
    # GET 详情返回同一个契约
    assert client.get(f"/api/tournaments/{tid}/team-ties/{tie}").json() == body
    # 重复建盘 409（不会静默多生成 5 盘）
    again = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubber-skeleton",
        json={"format_code": FORMAT_CODE},
    )
    assert again.status_code == 409
    assert len(client.get(f"/api/tournaments/{tid}/team-ties/{tie}").json()["rubbers"]) == 5


def test_api_production_runtime_full_flow(client):
    """API 层：生产赛制 5 盘骨架 → 打到 3 胜 → 结束 → 剩余盘 SKIPPED。"""
    tid, tie, team_a, team_b, body = _api_setup(client)
    home_ids = [m["player_id"] for m in body["home_team"]["members"]]
    away_ids = [m["player_id"] for m in body["away_team"]["members"]]

    def play(rubber, home, away, need):
        assert client.put(
            f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber['id']}/lineup",
            json={"home_player_ids": home_ids[:need], "away_player_ids": away_ids[:need]},
        ).status_code == 200
        assert client.post(
            f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber['id']}/start"
        ).status_code == 200
        scored = client.post(
            f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber['id']}/score",
            json={"home_score": home, "away_score": away},
        )
        assert scored.status_code == 200, scored.text
        return scored.json()

    latest = play(body["rubbers"][0], 2, 0, 1)
    assert latest["rubbers"][0]["winner_entry_id"] == team_a
    latest = play(body["rubbers"][1], 0, 2, 1)
    assert latest["rubbers"][1]["winner_entry_id"] == team_b
    latest = play(body["rubbers"][2], 2, 1, 2)
    assert len(latest["rubbers"][2]["home_player_ids"]) == 2
    latest = play(body["rubbers"][3], 2, 0, 1)

    assert (latest["home_score"], latest["away_score"]) == (3, 1)
    assert latest["status"] == "FINISHED"
    assert latest["winner_entry_id"] == team_a
    assert [r["status"] for r in latest["rubbers"]] == [
        "FINISHED", "FINISHED", "FINISHED", "FINISHED", "SKIPPED"
    ]
    assert latest["format"]["code"] == FORMAT_CODE
    assert latest["target_wins"] == 3

    # 已结束后不能再开第 5 盘
    assert client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{latest['rubbers'][4]['id']}/start"
    ).status_code == 409


def test_api_unknown_format_is_422_not_500(client):
    tid, tie, _a, _b, _body = _api_setup(client)
    # 另建一场对抗来验未登记 code（避免与已建盘的对抗混在一起）
    ties = client.get(f"/api/tournaments/{tid}/team-ties").json()
    assert len(ties) == 1
    other = client.post(
        f"/api/tournaments/{tid}/team-ties",
        json={"entry_a_id": ties[0]["entry_b_id"], "entry_b_id": ties[0]["entry_a_id"]},
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]

    for code in ("UNKNOWN_FORMAT", "OLYMPIC", "TEST_ONLY_FORMAT_V1_SPEC"):
        rejected = client.post(
            f"/api/tournaments/{tid}/team-ties/{other_id}/rubber-skeleton",
            json={"format_code": code},
        )
        assert rejected.status_code == 422, code
        assert "未知的团体赛赛制" in rejected.json()["detail"]
    assert client.get(f"/api/tournaments/{tid}/team-ties/{other_id}").json()["rubbers"] == []


def test_api_production_format_on_non_team_tournament_is_rejected(client):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "单打赛事",
            "date": "2026-07-05",
            "table_count": 4,
            "group_count": 1,
            "qualify_per_group": 1,
            "event_type": "SINGLES",
            "operation_mode": "DEMO",
        },
    ).json()["id"]
    rejected = client.post(
        f"/api/tournaments/{tid}/team-ties/1/rubber-skeleton",
        json={"format_code": FORMAT_CODE},
    )
    assert rejected.status_code == 409
    assert "SINGLES" in rejected.json()["detail"]
