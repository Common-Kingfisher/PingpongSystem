"""A4.1 团体赛 Runtime Engine：阵容绑定 → 盘状态机 → 对抗计分与提前结束。

测试用的赛制叫 `TEST_ONLY_*`，只在测试进程内注册，**不代表任何正式团体赛赛制**，
盘序也没有产品含义：它只是用来验证"与赛制无关"的通用状态机。
生产注册表始终为空（`PRODUCTION_FORMATS == {}`），赛制冻结后只需注册一个 TeamFormatSpec。

PR #20 复审后补充：名单冻结 / lineup 失效重校验（P1-1）、并发下的原子状态迁移（P1-2）、
"多盘 PLAYING"不变量必须在写入之前校验（P2）。
"""

import concurrent.futures
import json
import sqlite3

import pytest

from app import db as db_module
from app import repository as repo
from app.domain import team_formats as tf
from app.services import entries as entries_service
from app.services import team_runtime as runtime
from app.services import team_ties as ties_service
from app.services import teams as teams_service
from app.services import tournament_export

S = "SINGLES"
D = "DOUBLES"

#: 5 盘、需要 3 胜（S,S,D,S,S）——仅用于验证状态机，不是正式赛制。
TEST_ONLY_FORMAT = tf.TeamFormatSpec(
    code="TEST_ONLY_RUNTIME",
    version=1,
    display_name="测试用运行时赛制（非生产规则）",
    rubbers_to_win=3,
    rubbers=(
        tf.RubberTemplate(1, S, ("H1",), ("A1",)),
        tf.RubberTemplate(2, S, ("H2",), ("A2",)),
        tf.RubberTemplate(3, D, ("H3", "H4"), ("A3", "A4")),
        tf.RubberTemplate(4, S, ("H5",), ("A5",)),
        tf.RubberTemplate(5, S, ("H6",), ("A6",)),
    ),
)

#: 3 盘、需要 2 胜：用来证明 target_wins 真的来自快照，而不是写死的 3 或 (n+1)//2。
TEST_ONLY_SHORT_FORMAT = tf.TeamFormatSpec(
    code="TEST_ONLY_SHORT",
    version=2,
    display_name="测试用短赛制（非生产规则）",
    rubbers_to_win=2,
    rubbers=(
        tf.RubberTemplate(1, S, ("H1",), ("A1",)),
        tf.RubberTemplate(2, S, ("H2",), ("A2",)),
        tf.RubberTemplate(3, S, ("H3",), ("A3",)),
    ),
)


@pytest.fixture()
def runtime_format(monkeypatch):
    tf.validate_format_spec(TEST_ONLY_FORMAT)
    monkeypatch.setitem(tf.PRODUCTION_FORMATS, TEST_ONLY_FORMAT.code, TEST_ONLY_FORMAT)
    return TEST_ONLY_FORMAT


@pytest.fixture()
def short_format(monkeypatch):
    tf.validate_format_spec(TEST_ONLY_SHORT_FORMAT)
    monkeypatch.setitem(tf.PRODUCTION_FORMATS, TEST_ONLY_SHORT_FORMAT.code, TEST_ONLY_SHORT_FORMAT)
    return TEST_ONLY_SHORT_FORMAT


class Setup:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _setup(conn, spec: tf.TeamFormatSpec, *, players: int = 8, group_count: int = 1) -> Setup:
    """建赛事 → 选手 → 两队 → 确认名单 → 对抗 → 赛制骨架，返回常用 id。"""
    tournament = repo.create_tournament(
        conn, f"Runtime {spec.code}", "2026-06-01", 4, group_count, 1,
        event_type="TEAM", operation_mode="DEMO",
    )
    tid = tournament["id"]
    roster = [
        repo.add_player(conn, tid, f"P{index:02d}", "计算机学院", 1000 + index)
        for index in range(1, players + 1)
    ]
    conn.commit()
    half = len(roster) // 2
    team_a = teams_service.create_team_entry(conn, tid, "A队", [p["id"] for p in roster[:half]])
    team_b = teams_service.create_team_entry(conn, tid, "B队", [p["id"] for p in roster[half:]])
    entries_service.confirm_roster(conn, tid)
    tie = ties_service.create_team_tie(conn, tid, team_a["id"], team_b["id"])
    view = runtime.runtime_view(conn, tid, tie["id"])
    ties_service.build_rubber_skeleton(conn, tid, tie["id"], spec.code)
    view = runtime.runtime_view(conn, tid, tie["id"])
    return Setup(
        tournament_id=tid,
        tie_id=tie["id"],
        team_a=team_a["id"],
        team_b=team_b["id"],
        view=view,
        rubbers=[r["id"] for r in view["rubbers"]],
        home_ids=[m["player_id"] for m in view["home_team"]["members"]],
        away_ids=[m["player_id"] for m in view["away_team"]["members"]],
    )


def _play(conn, s: Setup, index: int, home_score: int, away_score: int, *, home=None, away=None) -> dict:
    """完整打完一盘：按盘型取足够的人数 → lineup → start → score，返回最新运行态。"""
    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    rubber = view["rubbers"][index]
    need = 2 if rubber["rubber_type"] == D else 1
    home_ids = (home or s.home_ids)[:need]
    away_ids = (away or s.away_ids)[:need]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber["id"], home_ids, away_ids)
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber["id"])
    return runtime.record_rubber_score(
        conn, s.tournament_id, s.tie_id, rubber["id"], home_score, away_score
    )


# --------------------------------------------------------------- 核心 E2E

def test_full_tie_runs_to_early_finish(conn, runtime_format):
    """PR #20 最重要的测试：骨架 → 阵容 → 开始 → 录分 → 累计 → 达标 → 结束 → 剩余 SKIPPED。"""
    s = _setup(conn, runtime_format)
    view = s.view
    assert view["status"] == "WAITING"
    assert view["target_wins"] == 3  # 来自快照
    assert [r["status"] for r in view["rubbers"]] == ["PENDING"] * 5
    assert view["home_score"] == view["away_score"] == 0
    assert view["home_team"]["display_name"] == "A队"
    assert len(view["home_team"]["members"]) == 4
    assert view["winner_entry_id"] is None

    # 第 1 盘：主队胜
    view = _play(conn, s, 0, 2, 0)
    assert view["home_score"] == 1 and view["away_score"] == 0
    assert view["status"] == "PLAYING"  # 第一盘开始后对抗进入 PLAYING
    assert view["started_at"] is not None and view["called_at"] is not None
    first = view["rubbers"][0]
    assert first["status"] == "FINISHED"
    assert (first["home_score"], first["away_score"]) == (2, 0)
    assert first["winner_side"] == "HOME"
    assert first["winner_entry_id"] == s.team_a
    assert first["finished_at"] is not None

    # 第 2 盘：客队胜（双打盘之外的 S 盘）
    view = _play(conn, s, 1, 1, 2)
    assert (view["home_score"], view["away_score"]) == (1, 1)
    assert view["rubbers"][1]["winner_side"] == "AWAY"

    # 第 3 盘：双打盘，主队胜
    view = _play(conn, s, 2, 2, 1)
    assert (view["home_score"], view["away_score"]) == (2, 1)
    assert view["status"] == "PLAYING"
    assert view["rubbers"][2]["home_players"] and len(view["rubbers"][2]["home_player_ids"]) == 2

    # 第 4 盘：主队达到 3 胜 → 对抗自动结束
    view = _play(conn, s, 3, 2, 0)
    assert (view["home_score"], view["away_score"]) == (3, 1)
    assert view["status"] == "FINISHED"
    assert view["winner_entry_id"] == s.team_a
    assert view["finished_at"] is not None
    # 剩余的第 5 盘自动 SKIPPED；已完成的盘不受影响
    assert [r["status"] for r in view["rubbers"]] == [
        "FINISHED", "FINISHED", "FINISHED", "FINISHED", "SKIPPED",
    ]
    # 结束后所有权限关闭
    assert view["permissions"] == {
        "can_edit_lineup": False,
        "can_confirm_lineup": False,
        "can_start": False,
        "can_record_score": False,
        "can_revise_score": False,
    }
    # A4.1 仍然不创建普通 Match：match_id 恒为 NULL
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0
    assert {r["match_id"] for r in view["rubbers"]} == {None}
    # 落库的对抗比分与演示的累计一致
    stored = repo.get_team_tie(conn, s.tie_id)
    assert (stored["team_a_score"], stored["team_b_score"]) == (3, 1)
    assert stored["status"] == "FINISHED"


def test_target_wins_comes_from_snapshot_not_hardcoded(conn, short_format):
    """3 盘 / 需要 2 胜：不能写死 3，也不能用 (len+1)//2 之外的臆测。"""
    s = _setup(conn, short_format)
    assert s.view["target_wins"] == 2
    assert len(s.view["rubbers"]) == 3

    view = _play(conn, s, 0, 2, 0)
    assert view["status"] == "PLAYING"
    view = _play(conn, s, 1, 2, 1)  # 2:0 达到 target_wins
    assert view["status"] == "FINISHED"
    assert (view["home_score"], view["away_score"]) == (2, 0)
    assert [r["status"] for r in view["rubbers"]] == ["FINISHED", "FINISHED", "SKIPPED"]


def test_tie_without_format_snapshot_has_no_target_wins(conn, runtime_format):
    """尚未建盘时读取不应 500：target_wins 为 null，format 全为 null。"""
    tournament = repo.create_tournament(
        conn, "无骨架", "2026-06-01", 4, 1, 1, event_type="TEAM", operation_mode="DEMO"
    )
    tid = tournament["id"]
    roster = [repo.add_player(conn, tid, f"P{i}", None, 1000) for i in range(1, 5)]
    conn.commit()
    a = teams_service.create_team_entry(conn, tid, "A队", [p["id"] for p in roster[:2]])
    b = teams_service.create_team_entry(conn, tid, "B队", [p["id"] for p in roster[2:]])
    tie = ties_service.create_team_tie(conn, tid, a["id"], b["id"])

    view = runtime.runtime_view(conn, tid, tie["id"])
    assert view["target_wins"] is None
    assert view["format"] == {
        "code": None, "version": None, "display_name": None, "rubbers_to_win": None,
    }
    assert view["rubbers"] == []


def test_corrupted_snapshot_blocks_scoring(conn, runtime_format):
    """快照损坏时不允许静默用默认值结算（防御性：接口拿不到获胜盘数就拒绝）。"""
    s = _setup(conn, runtime_format)
    view = _play(conn, s, 0, 2, 0)
    rubber2 = view["rubbers"][1]["id"]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber2, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber2)
    conn.execute("UPDATE team_ties SET format_snapshot = '{坏数据' WHERE id = ?", (s.tie_id,))
    conn.commit()
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.record_rubber_score(conn, s.tournament_id, s.tie_id, rubber2, 2, 0)
    assert excinfo.value.code == 409
    assert "赛制快照" in str(excinfo.value)
    assert repo.get_team_rubber(conn, rubber2)["status"] == "PLAYING"  # 没有半途写入


# --------------------------------------------------------------- 状态机失败场景

def test_second_playing_rubber_is_rejected(conn, runtime_format):
    s = _setup(conn, runtime_format)
    first, second = s.rubbers[0], s.rubbers[1]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, first, s.home_ids[:1], s.away_ids[:1])
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, second, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, first)

    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, second)
    assert excinfo.value.code == 409
    assert "同时只能进行一盘" in str(excinfo.value)
    # 第二盘仍是 READY，权限也反映"现在不能开始"
    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    assert view["rubbers"][1]["status"] == "READY"
    assert view["rubbers"][1]["permissions"]["can_start"] is False
    assert view["rubbers"][0]["permissions"]["can_start"] is False


def test_pending_rubber_cannot_start(conn, runtime_format):
    s = _setup(conn, runtime_format)
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, s.rubbers[0])
    assert excinfo.value.code == 409
    assert "阵容" in str(excinfo.value)


def test_ready_rubber_cannot_score_without_start(conn, runtime_format):
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.record_rubber_score(conn, s.tournament_id, s.tie_id, rubber, 2, 0)
    assert excinfo.value.code == 409
    assert "开始" in str(excinfo.value)


def test_finished_rubber_cannot_be_rescored(conn, runtime_format):
    s = _setup(conn, runtime_format)
    _play(conn, s, 0, 2, 0)
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.record_rubber_score(conn, s.tournament_id, s.tie_id, s.rubbers[0], 1, 2)
    assert excinfo.value.code == 409
    assert "改分" in str(excinfo.value)


def test_skipped_rubber_is_locked(conn, short_format):
    """提前结束后剩余盘是 SKIPPED：lineup / start / score 全部拒绝。"""
    s = _setup(conn, short_format)
    _play(conn, s, 0, 2, 0)
    view = _play(conn, s, 1, 2, 0)
    skipped = view["rubbers"][2]
    assert skipped["status"] == "SKIPPED"
    assert skipped["permissions"] == {
        "can_edit_lineup": False,
        "can_confirm_lineup": False,
        "can_start": False,
        "can_record_score": False,
        "can_revise_score": False,
    }
    for action in (
        lambda: runtime.set_lineup(
            conn, s.tournament_id, s.tie_id, skipped["id"], s.home_ids[:1], s.away_ids[:1]
        ),
        lambda: runtime.start_rubber(conn, s.tournament_id, s.tie_id, skipped["id"]),
        lambda: runtime.record_rubber_score(conn, s.tournament_id, s.tie_id, skipped["id"], 2, 0),
    ):
        with pytest.raises(runtime.TeamRuntimeError) as excinfo:
            action()
        assert excinfo.value.code == 409


def test_finished_tie_rejects_lineup_and_start(conn, short_format):
    s = _setup(conn, short_format)
    _play(conn, s, 0, 2, 0)
    view = _play(conn, s, 1, 2, 0)
    assert view["status"] == "FINISHED"
    # 找一个未完成的盘（第 3 盘已 SKIPPED）——对抗级守卫先于盘级守卫
    with pytest.raises(runtime.TeamRuntimeError) as lineup:
        runtime.set_lineup(
            conn, s.tournament_id, s.tie_id, s.rubbers[2], s.home_ids[:1], s.away_ids[:1]
        )
    assert lineup.value.code == 409 and "对抗已结束" in str(lineup.value)
    with pytest.raises(runtime.TeamRuntimeError) as start:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, s.rubbers[2])
    assert start.value.code == 409 and "对抗已结束" in str(start.value)


def test_lineup_is_locked_after_start(conn, runtime_format):
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[1:2], s.away_ids[:1])
    assert excinfo.value.code == 409
    assert "阵容已锁定" in str(excinfo.value)


def test_lineup_can_be_replaced_while_ready(conn, runtime_format):
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    view = runtime.set_lineup(
        conn, s.tournament_id, s.tie_id, rubber, s.home_ids[1:2], s.away_ids[1:2]
    )
    assert view["rubbers"][0]["status"] == "READY"  # 合法替换后仍是 READY
    assert view["rubbers"][0]["home_player_ids"] == s.home_ids[1:2]


def test_domain_conflict_when_two_rubbers_playing(conn, runtime_format):
    """绕过接口把两盘写成 PLAYING 时，结算必须在**任何写入之前**拒绝。

    Reviewer P2：旧实现先 mark_finished 再检查，抛出 409 时当前盘已经被改成 FINISHED
    （未提交的脏状态），与注释"拒绝继续而不是留脏状态"不一致。
    """
    s = _setup(conn, runtime_format)
    view = _play(conn, s, 0, 2, 0)
    second = view["rubbers"][1]["id"]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, second, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, second)
    # 绕过接口把第一盘也写成 PLAYING（模拟旧数据/直连写入造成的非法状态）
    conn.execute(
        "UPDATE team_rubbers SET status = 'PLAYING', started_at = datetime('now') WHERE id = ?",
        (s.rubbers[0],),
    )
    conn.commit()
    tie_before = repo.get_team_tie(conn, s.tie_id)

    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.record_rubber_score(conn, s.tournament_id, s.tie_id, second, 2, 0)
    assert excinfo.value.code == 409
    assert "拒绝自动结算" in str(excinfo.value)

    # 关键断言：失败后没有任何半成品写入
    current = repo.get_team_rubber(conn, second)
    assert current["status"] == "PLAYING"
    assert current["home_score"] is None and current["away_score"] is None
    assert current["finished_at"] is None
    assert repo.get_team_tie(conn, s.tie_id) == tie_before


# --------------------------------------------------------------- 阵容校验

def test_lineup_rejects_foreign_player(conn, runtime_format):
    s = _setup(conn, runtime_format)
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.set_lineup(
            conn, s.tournament_id, s.tie_id, s.rubbers[0], [s.away_ids[0]], s.away_ids[:1]
        )
    assert excinfo.value.code == 409
    assert "不属于" in str(excinfo.value)


def test_lineup_rejects_unknown_player(conn, runtime_format):
    s = _setup(conn, runtime_format)
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.set_lineup(conn, s.tournament_id, s.tie_id, s.rubbers[0], [987654], s.away_ids[:1])
    assert excinfo.value.code == 404


def test_lineup_count_must_match_rubber_type(conn, runtime_format):
    s = _setup(conn, runtime_format)
    singles = s.rubbers[0]
    doubles = s.rubbers[2]
    with pytest.raises(runtime.TeamRuntimeError) as too_many:
        runtime.set_lineup(
            conn, s.tournament_id, s.tie_id, singles, s.home_ids[:2], s.away_ids[:1]
        )
    assert too_many.value.code == 422
    assert "需要 1 名队员" in str(too_many.value)
    with pytest.raises(runtime.TeamRuntimeError) as too_few:
        runtime.set_lineup(conn, s.tournament_id, s.tie_id, doubles, s.home_ids[:1], s.away_ids[:2])
    assert too_few.value.code == 422
    assert "需要 2 名队员" in str(too_few.value)


def test_lineup_rejects_duplicate_player_on_same_side(conn, runtime_format):
    s = _setup(conn, runtime_format)
    doubles = s.rubbers[2]
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.set_lineup(
            conn,
            s.tournament_id,
            s.tie_id,
            doubles,
            [s.home_ids[0], s.home_ids[0]],
            s.away_ids[:2],
        )
    assert excinfo.value.code == 422
    assert "不能重复" in str(excinfo.value)


def test_lineup_rejects_withdrawn_team(conn, runtime_format):
    s = _setup(conn, runtime_format)
    entries_service.withdraw_from_tournament(conn, s.tournament_id, s.team_b, "主裁", "整队退赛")
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.set_lineup(conn, s.tournament_id, s.tie_id, s.rubbers[0], s.home_ids[:1], s.away_ids[:1])
    assert excinfo.value.code == 409
    assert "退出赛事" in str(excinfo.value)
    # 候选阵容也把该队全部标成不可用
    options = runtime.lineup_options(conn, s.tournament_id, s.tie_id, s.rubbers[0])
    assert options["away"] and all(not o["available"] for o in options["away"])
    assert all(o["unavailable_reason"] == "队伍已退出赛事" for o in options["away"])


def test_lineup_options_are_per_side_and_lock_after_start(conn, runtime_format):
    s = _setup(conn, runtime_format)
    options = runtime.lineup_options(conn, s.tournament_id, s.tie_id, s.rubbers[0])
    assert [o["player_id"] for o in options["home"]] == s.home_ids
    assert [o["player_id"] for o in options["away"]] == s.away_ids
    assert all(o["available"] and o["unavailable_reason"] is None for o in options["home"])
    assert all(o["name"] for o in options["home"])

    runtime.set_lineup(conn, s.tournament_id, s.tie_id, s.rubbers[0], s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, s.rubbers[0])
    locked = runtime.lineup_options(conn, s.tournament_id, s.tie_id, s.rubbers[0])
    assert all(not o["available"] for o in locked["home"])
    assert all(o["unavailable_reason"] for o in locked["home"])
    # 未冻结的规则不得偷偷生效：同一名选手仍可在别的盘出现（不实现"不能兼项"）
    other = runtime.lineup_options(conn, s.tournament_id, s.tie_id, s.rubbers[1])
    assert all(o["available"] for o in other["home"])


# --------------------------------------------------------------- 比分校验

@pytest.mark.parametrize("home,away", [(1, 0), (2, 2), (3, 0), (99, 0), (0, 99), (1, 1), (-1, 2)])
def test_invalid_rubber_scores_are_rejected(conn, runtime_format, home, away):
    """games_to_win=2 时只有 2:x / x:2 合法；这里复用个人赛同一套规则 → 422。"""
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.record_rubber_score(conn, s.tournament_id, s.tie_id, rubber, home, away)
    assert excinfo.value.code == 422
    assert repo.get_team_rubber(conn, rubber)["status"] == "PLAYING"  # 失败不落库


def test_valid_rubber_scores_follow_games_to_win(conn, runtime_format):
    s = _setup(conn, runtime_format, players=8)
    view = _play(conn, s, 0, 2, 1)  # 2:1 合法
    assert (view["rubbers"][0]["home_score"], view["rubbers"][0]["away_score"]) == (2, 1)


# --------------------------------------------------------------- 404 / 参数校验

def test_runtime_lookup_errors(conn, runtime_format):
    s = _setup(conn, runtime_format)
    other = _setup(conn, runtime_format)
    # 对抗不存在 / 不属于该赛事
    with pytest.raises(runtime.TeamRuntimeError) as tie_missing:
        runtime.runtime_view(conn, s.tournament_id, 987654)
    assert tie_missing.value.code == 404
    with pytest.raises(runtime.TeamRuntimeError) as tie_other:
        runtime.runtime_view(conn, other.tournament_id, s.tie_id)
    assert tie_other.value.code == 404
    # 盘不存在 / 盘属于另一场对抗
    with pytest.raises(runtime.TeamRuntimeError) as rubber_missing:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, 987654)
    assert rubber_missing.value.code == 404
    with pytest.raises(runtime.TeamRuntimeError) as rubber_other:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, other.rubbers[0])
    assert rubber_other.value.code == 404
    # 赛事不存在
    with pytest.raises(runtime.TeamRuntimeError) as tournament_missing:
        runtime.runtime_view(conn, 987654, s.tie_id)
    assert tournament_missing.value.code == 404


def test_runtime_requires_team_event(conn, runtime_format):
    singles = repo.create_tournament(conn, "单打", "2026-06-01", 4, 2, 1, event_type="SINGLES")
    conn.commit()
    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.runtime_view(conn, singles["id"], 1)
    assert excinfo.value.code == 409
    assert "TEAM" in str(excinfo.value)


# --------------------------------------------------------------- API 层 E2E

def _api_setup(client, *, spec_code: str = TEST_ONLY_FORMAT.code, players: int = 8):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "Runtime API",
            "date": "2026-06-01",
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
        f"/api/tournaments/{tid}/team-ties/{tie}/rubber-skeleton", json={"format_code": spec_code}
    )
    assert built.status_code == 200, built.text
    return tid, tie, a, b, built.json()


def test_runtime_api_end_to_end(client, runtime_format):
    tid, tie, team_a, team_b, view = _api_setup(client)
    assert view["target_wins"] == 3
    rubber1 = view["rubbers"][0]
    home_ids = [m["player_id"] for m in view["home_team"]["members"]]
    away_ids = [m["player_id"] for m in view["away_team"]["members"]]

    # 候选阵容
    options = client.get(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber1['id']}/lineup-options"
    )
    assert options.status_code == 200
    assert [o["player_id"] for o in options.json()["home"]] == home_ids

    # 提交阵容 → 完整运行态
    lineup = client.put(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber1['id']}/lineup",
        json={"home_player_ids": home_ids[:1], "away_player_ids": away_ids[:1]},
    )
    assert lineup.status_code == 200, lineup.text
    assert lineup.json()["rubbers"][0]["status"] == "READY"
    assert lineup.json()["rubbers"][0]["permissions"]["can_start"] is True

    # 开始 → PLAYING，对抗进入 PLAYING
    started = client.post(f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber1['id']}/start")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "PLAYING"
    assert started.json()["rubbers"][0]["permissions"]["can_record_score"] is True

    # 录分 → 累计
    scored = client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber1['id']}/score",
        json={"home_score": 2, "away_score": 0},
    )
    assert scored.status_code == 200, scored.text
    body = scored.json()
    assert (body["home_score"], body["away_score"]) == (1, 0)
    assert body["rubbers"][0]["winner_side"] == "HOME"
    assert body["rubbers"][0]["winner_entry_id"] == team_a

    # GET 详情返回同一个运行态契约（不存在第二套 runtime 路径）
    detail = client.get(f"/api/tournaments/{tid}/team-ties/{tie}")
    assert detail.status_code == 200
    assert detail.json() == body

    # 非法比分 / 状态冲突 / 不存在：错误契约
    assert client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber1['id']}/score",
        json={"home_score": 3, "away_score": 0},
    ).status_code == 409  # 已结束 → 状态冲突优先
    r2 = body["rubbers"][1]["id"]
    assert client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{r2}/score",
        json={"home_score": 2, "away_score": 0},
    ).status_code == 409  # 还没开始
    assert client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{r2}/start"
    ).status_code == 409  # 还没阵容
    assert client.put(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{r2}/lineup",
        json={"home_player_ids": home_ids[:2], "away_player_ids": away_ids[:1]},
    ).status_code == 422  # 单打盘填 2 人
    assert client.get(
        f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/987654/lineup-options"
    ).status_code == 404
    assert client.get(f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{r2}/lineup-options").status_code == 200
    assert client.get(f"/api/tournaments/999999/team-ties/{tie}").status_code == 404
    # 不存在"直接改对抗比分"的接口（避免两个真相源）
    assert client.post(
        f"/api/tournaments/{tid}/team-ties/{tie}/score", json={"home_score": 3, "away_score": 1}
    ).status_code == 404


def test_runtime_api_early_finish_and_skipped(client, short_format):
    tid, tie, team_a, _team_b, view = _api_setup(client, spec_code=short_format.code, players=6)
    home_ids = [m["player_id"] for m in view["home_team"]["members"]]
    away_ids = [m["player_id"] for m in view["away_team"]["members"]]

    latest = view
    for index in (0, 1):
        rubber = latest["rubbers"][index]
        need = 2 if rubber["rubber_type"] == "DOUBLES" else 1
        latest = client.put(
            f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber['id']}/lineup",
            json={"home_player_ids": home_ids[:need], "away_player_ids": away_ids[:need]},
        ).json()
        latest = client.post(
            f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber['id']}/start"
        ).json()
        latest = client.post(
            f"/api/tournaments/{tid}/team-ties/{tie}/rubbers/{rubber['id']}/score",
            json={"home_score": 2, "away_score": 0},
        ).json()

    assert latest["status"] == "FINISHED"
    assert latest["winner_entry_id"] == team_a
    assert (latest["home_score"], latest["away_score"]) == (2, 0)
    assert [r["status"] for r in latest["rubbers"]] == ["FINISHED", "FINISHED", "SKIPPED"]


# --------------------------------------------------------------- 升级 / 导出

A3_TEAM_RUBBERS_SQL = """
CREATE TABLE team_rubbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_tie_id INTEGER NOT NULL REFERENCES team_ties(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    rubber_type TEXT NOT NULL CHECK (rubber_type IN ('SINGLES','DOUBLES')),
    home_slots_json TEXT NOT NULL,
    away_slots_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','READY','PLAYING','FINISHED','SKIPPED')),
    match_id INTEGER REFERENCES matches(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (team_tie_id, sequence)
);
"""


def test_pr19_database_upgrades_runtime_columns(tmp_path, monkeypatch, runtime_format):
    """PR #19 已经建过的库（team_rubbers 没有运行态列）必须能直接升级，不要求删库重建。"""
    path = tmp_path / "pr19.db"
    monkeypatch.setenv("DEMO_DB_PATH", str(path))
    db_module.init_db()

    conn = db_module.connect()
    try:
        # 退回 PR #19 的 team_rubbers 结构，并保留已有数据
        tid = repo.create_tournament(
            conn, "旧结构", "2026-06-01", 4, 1, 1, event_type="TEAM", operation_mode="DEMO"
        )["id"]
        roster = [repo.add_player(conn, tid, f"P{i}", None, 1000) for i in range(1, 5)]
        a = teams_service.create_team_entry(conn, tid, "A队", [p["id"] for p in roster[:2]])
        b = teams_service.create_team_entry(conn, tid, "B队", [p["id"] for p in roster[2:]])
        tie = repo.create_team_tie(conn, tid, "GROUP", None, 1, 1, a["id"], b["id"])
        old_rubber = repo.create_team_rubber(conn, tie["id"], 1, "SINGLES", '["H1"]', '["A1"]')
        conn.commit()
        conn.execute("DROP TABLE team_rubbers")
        conn.executescript(A3_TEAM_RUBBERS_SQL)
        conn.execute(
            "INSERT INTO team_rubbers (id, team_tie_id, sequence, rubber_type, home_slots_json, "
            "away_slots_json, status) VALUES (?, ?, 1, 'SINGLES', '[\"H1\"]', '[\"A1\"]', 'PENDING')",
            (old_rubber["id"], tie["id"]),
        )
        conn.commit()
        before = {r[1] for r in conn.execute("PRAGMA table_info(team_rubbers)")}
        assert "home_player_ids_json" not in before
    finally:
        conn.close()

    db_module.init_db()  # 升级

    conn = db_module.connect()
    try:
        after = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(team_rubbers)")}
        for column, ddl in db_module.TEAM_RUBBER_RUNTIME_COLUMNS:
            assert column in after, column
        # 与新建库的列定义一致（语义级防漂移）
        fresh = sqlite3.connect(":memory:")
        fresh.executescript(db_module.TEAM_RUBBERS_TABLE_SQL)
        fresh_cols = {r[1]: r[2] for r in fresh.execute("PRAGMA table_info(team_rubbers)")}
        fresh.close()
        assert {k: v for k, v in after.items()} == fresh_cols
        # 旧数据保留，新列为 NULL
        row = dict(conn.execute("SELECT * FROM team_rubbers WHERE id = ?", (old_rubber["id"],)).fetchone())
        assert row["status"] == "PENDING"
        assert row["home_slots_json"] == '["H1"]'
        assert row["home_player_ids_json"] is None and row["home_score"] is None
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        # 升级后的库能直接跑 Runtime（引擎不需要额外的重建步骤）
        ties_service.build_rubber_skeleton(conn, tid, tie["id"], runtime_format.code, replace=True)
        view = runtime.runtime_view(conn, tid, tie["id"])
        home_ids = [m["player_id"] for m in view["home_team"]["members"]]
        away_ids = [m["player_id"] for m in view["away_team"]["members"]]
        latest = runtime.set_lineup(
            conn, tid, tie["id"], view["rubbers"][0]["id"], home_ids[:1], away_ids[:1]
        )
        latest = runtime.start_rubber(conn, tid, tie["id"], view["rubbers"][0]["id"])
        latest = runtime.record_rubber_score(
            conn, tid, tie["id"], view["rubbers"][0]["id"], 2, 0
        )
        assert latest["home_score"] == 1
    finally:
        conn.close()


def test_export_includes_runtime_fields_and_stays_read_only(conn, runtime_format):
    s = _setup(conn, runtime_format)
    _play(conn, s, 0, 2, 0)

    before = [dict(r) for r in conn.execute("SELECT * FROM team_rubbers ORDER BY id")]
    exported = tournament_export.get_export(conn, s.tournament_id)
    after = [dict(r) for r in conn.execute("SELECT * FROM team_rubbers ORDER BY id")]
    assert before == after  # 导出仍然只读

    rubber_rows = [r for r in exported["team_rubbers"] if r["team_tie_id"] == s.tie_id]
    assert len(rubber_rows) == 5
    first = rubber_rows[0]
    assert first["status"] == "FINISHED"
    assert (first["home_score"], first["away_score"]) == (2, 0)
    assert first["winner_entry_id"] == s.team_a
    assert json.loads(first["home_player_ids_json"]) == s.home_ids[:1]
    assert first["started_at"] and first["finished_at"]
    assert first["match_id"] is None
    # 对抗层：总分与胜者同步导出
    tie_row = next(t for t in exported["team_ties"] if t["id"] == s.tie_id)
    assert (tie_row["team_a_score"], tie_row["team_b_score"]) == (1, 0)
    assert tie_row["status"] == "PLAYING"


# ================================================================ PR #20 复审返工
# P1-1：名单冻结与 lineup 失效重校验
# P1-2：并发下的原子状态迁移
# P2  ：多盘 PLAYING 不变量必须在任何写入之前校验


def _run_in_parallel(*calls):
    """在两个独立 SQLite 连接（两个线程）上并发执行，返回 (结果 or 异常) 列表。"""

    def run(fn):
        worker_conn = db_module.connect()
        try:
            return ("ok", fn(worker_conn))
        except Exception as exc:  # noqa: BLE001 - 测试需要同时收集成功与业务错误
            return ("err", exc)
        finally:
            worker_conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, fn) for fn in calls]
        return [f.result() for f in futures]


# ---------------------------------------------------------------- P1-1 名单冻结

def test_ready_lineup_invalidated_when_member_removed(conn, runtime_format):
    """READY 之后把队员移出队伍：旧 lineup 不得再无条件 start（Reviewer P1-1 复现路径）。"""
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    removed = s.home_ids[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, [removed], s.away_ids[:1])

    # 对抗还没开始（WAITING），因此名单修正本身仍允许
    teams_service.update_team_entry(
        conn, s.tournament_id, s.team_a, member_ids=s.home_ids[1:]
    )
    assert removed not in [m["player_id"] for m in repo.get_entry(conn, s.team_a)["members"]]

    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    first = view["rubbers"][0]
    assert first["status"] == "READY"  # 盘状态没有被偷偷改掉
    assert first["home_player_ids"] == [removed]  # 保存的阵容也还在
    assert first["lineup_valid"] is False
    assert "失效" in first["lineup_invalid_reason"]
    # 权限必须与服务端守卫一致：不能开始
    assert first["permissions"]["can_start"] is False
    assert view["permissions"]["can_start"] is False

    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)
    assert excinfo.value.code == 409
    assert "阵容" in str(excinfo.value)
    assert repo.get_team_rubber(conn, rubber)["status"] == "READY"  # 没有半成品写入

    # 重新提交合法阵容后即可开始
    fixed = runtime.set_lineup(
        conn, s.tournament_id, s.tie_id, rubber, s.home_ids[1:2], s.away_ids[:1]
    )
    assert fixed["rubbers"][0]["lineup_valid"] is True
    assert fixed["rubbers"][0]["permissions"]["can_start"] is True
    started = runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)
    assert started["rubbers"][0]["status"] == "PLAYING"


def test_ready_lineup_invalidated_when_team_withdraws(conn, runtime_format):
    """READY 之后整队退赛：start 必须拒绝（Reviewer P1-1 提到的第二条路径）。"""
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    entries_service.withdraw_from_tournament(conn, s.tournament_id, s.team_b, "主裁", "整队退赛")

    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    assert view["rubbers"][0]["lineup_valid"] is False
    assert "已退出赛事" in view["rubbers"][0]["lineup_invalid_reason"]
    assert view["rubbers"][0]["permissions"]["can_start"] is False

    with pytest.raises(runtime.TeamRuntimeError) as excinfo:
        runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)
    assert excinfo.value.code == 409
    assert "已退出赛事" in str(excinfo.value)


def test_roster_frozen_after_tie_starts(conn, runtime_format):
    """对抗一旦进入 PLAYING，队员名单冻结；改名与积分不受影响。"""
    s = _setup(conn, runtime_format)
    _play(conn, s, 0, 2, 0)  # 第一盘打完 → 对抗 PLAYING

    with pytest.raises(teams_service.TeamError) as excinfo:
        teams_service.update_team_entry(
            conn, s.tournament_id, s.team_a, member_ids=s.home_ids[:1]
        )
    assert excinfo.value.code == 409
    assert "锁定" in str(excinfo.value)
    # 名单没有被改动
    assert [m["player_id"] for m in repo.get_entry(conn, s.team_a)["members"]] == s.home_ids

    renamed = teams_service.update_team_entry(
        conn, s.tournament_id, s.team_a, display_name="A队（改名）"
    )
    assert renamed["display_name"] == "A队（改名）"
    assert [m["player_id"] for m in renamed["members"]] == s.home_ids


def test_roster_stays_frozen_after_tie_finished(conn, short_format):
    """对抗结束后名单仍然冻结（历史 lineup 必须一直可解释）。"""
    s = _setup(conn, short_format)
    _play(conn, s, 0, 2, 0)
    view = _play(conn, s, 1, 2, 0)
    assert view["status"] == "FINISHED"

    with pytest.raises(teams_service.TeamError) as excinfo:
        teams_service.update_team_entry(
            conn, s.tournament_id, s.team_b, member_ids=s.away_ids[:1]
        )
    assert excinfo.value.code == 409


def test_delete_team_still_blocked_after_tie(conn, runtime_format):
    """删除队伍在对抗存在时始终被拒（P1-1 的另一条面：队伍级操作不能绕过）。"""
    s = _setup(conn, runtime_format)
    with pytest.raises(teams_service.TeamError) as excinfo:
        teams_service.delete_team_entry(conn, s.tournament_id, s.team_a)
    assert excinfo.value.code == 409


# ---------------------------------------------------------------- P1-2 原子状态迁移

def test_conditional_updates_cannot_resurrect_or_rescore(conn, runtime_format):
    """条件更新（带预期旧状态 + rowcount）在数据库层保证状态机。

    即使有人绕过服务层直接调用仓储函数：PLAYING 不能被写回 READY，FINISHED 不能被二次结算。
    """
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)
    saved = repo.get_team_rubber(conn, rubber)
    assert saved["status"] == "PLAYING"

    # ① 直接改阵容：不命中 → 不会把 PLAYING 反向写回 READY
    assert repo.set_team_rubber_lineup(conn, rubber, "[]", "[]") is False
    conn.commit()
    after = repo.get_team_rubber(conn, rubber)
    assert (after["status"], after["home_player_ids_json"]) == (
        "PLAYING", saved["home_player_ids_json"],
    )

    # ② 直接重复 start：不命中
    assert repo.mark_team_rubber_playing(conn, rubber) is False
    conn.commit()

    # ③ 结算一次成功，第二次不命中（本版不支持改分）
    assert repo.mark_team_rubber_finished(conn, rubber, 2, 0, s.team_a) is True
    conn.commit()
    assert repo.mark_team_rubber_finished(conn, rubber, 0, 2, s.team_b) is False
    conn.commit()
    final = repo.get_team_rubber(conn, rubber)
    assert final["status"] == "FINISHED"
    assert (final["home_score"], final["away_score"], final["winner_entry_id"]) == (2, 0, s.team_a)


def test_concurrent_double_start_allows_only_one(conn, runtime_format):
    """两个并发 start（不同盘、同一对抗）：只能有一盘进入 PLAYING。"""
    s = _setup(conn, runtime_format)
    for index in (0, 1):
        runtime.set_lineup(
            conn, s.tournament_id, s.tie_id, s.rubbers[index], s.home_ids[:1], s.away_ids[:1]
        )

    results = _run_in_parallel(
        lambda c: runtime.start_rubber(c, s.tournament_id, s.tie_id, s.rubbers[0]),
        lambda c: runtime.start_rubber(c, s.tournament_id, s.tie_id, s.rubbers[1]),
    )
    ok = [r for status, r in results if status == "ok"]
    err = [r for status, r in results if status == "err"]
    assert len(ok) == 1, [str(e) for e in err]
    assert len(err) == 1
    assert isinstance(err[0], runtime.TeamRuntimeError) and err[0].code == 409

    # 数据库层不变量：同一对抗最多一盘 PLAYING
    playing = repo.list_playing_team_rubbers(conn, s.tie_id)
    assert len(playing) == 1
    view = runtime.runtime_view(conn, s.tournament_id, s.tie_id)
    assert [r["status"] for r in view["rubbers"]].count("PLAYING") == 1
    assert [r["id"] for r in view["rubbers"] if r["status"] == "PLAYING"] == [playing[0]["id"]]
    assert view["status"] == "PLAYING"


def test_write_lock_contention_returns_readable_conflict(conn, runtime_format):
    """另一个连接持有写锁时返回可读的 409，而不是把 SQLite 锁错误漏成 500。"""
    s = _setup(conn, runtime_format)
    runtime.set_lineup(
        conn, s.tournament_id, s.tie_id, s.rubbers[0], s.home_ids[:1], s.away_ids[:1]
    )
    blocker = db_module.connect()
    other = sqlite3.connect(str(db_module._db_path()), timeout=0.2, check_same_thread=False)
    other.row_factory = sqlite3.Row
    other.execute("PRAGMA foreign_keys = ON")
    try:
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute("UPDATE team_rubbers SET sequence = sequence WHERE id = ?", (s.rubbers[0],))
        with pytest.raises(runtime.TeamRuntimeError) as excinfo:
            runtime.start_rubber(other, s.tournament_id, s.tie_id, s.rubbers[0])
        assert excinfo.value.code == 409
        assert "正在被另一个请求处理" in str(excinfo.value)
    finally:
        blocker.rollback()
        blocker.close()
        other.close()

    # 锁释放后照常可以开始
    view = runtime.start_rubber(conn, s.tournament_id, s.tie_id, s.rubbers[0])
    assert view["rubbers"][0]["status"] == "PLAYING"


def test_concurrent_double_score_keeps_first_result(conn, runtime_format):
    """同一 PLAYING 盘并发录两次分：只保留第一笔（P1-2 的"不允许改分"）。"""
    s = _setup(conn, runtime_format)
    rubber = s.rubbers[0]
    runtime.set_lineup(conn, s.tournament_id, s.tie_id, rubber, s.home_ids[:1], s.away_ids[:1])
    runtime.start_rubber(conn, s.tournament_id, s.tie_id, rubber)

    results = _run_in_parallel(
        lambda c: runtime.record_rubber_score(c, s.tournament_id, s.tie_id, rubber, 2, 0),
        lambda c: runtime.record_rubber_score(c, s.tournament_id, s.tie_id, rubber, 0, 2),
    )
    ok_indexes = [i for i, (status, _) in enumerate(results) if status == "ok"]
    errors = [r for status, r in results if status == "err"]
    assert len(ok_indexes) == 1, [str(e) for e in errors]
    assert isinstance(errors[0], runtime.TeamRuntimeError) and errors[0].code == 409

    # 落库结果必须**整笔**来自胜出的那一次请求，不能出现比分与胜者来自不同请求的混合
    stored = repo.get_team_rubber(conn, rubber)
    expected = (2, 0, s.team_a) if ok_indexes[0] == 0 else (0, 2, s.team_b)
    assert stored["status"] == "FINISHED"
    assert (stored["home_score"], stored["away_score"], stored["winner_entry_id"]) == expected
    # 对抗分只累计一次（没有被第二笔覆盖成 1:1 或两次累加）
    tie = repo.get_team_tie(conn, s.tie_id)
    assert (tie["team_a_score"], tie["team_b_score"]) == (
        (1, 0) if ok_indexes[0] == 0 else (0, 1)
    )

