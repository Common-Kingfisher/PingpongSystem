"""比赛生成的并发与事务边界回归（PR #68 review Finding #1 / #2）。

## 为什么必须是这样测

Reviewer 的 High 是"生成流程仍是 read → check → write，没有从第一条 invariant 开始
持有 server-side write lock"。前端 `busy` 标志解决不了多标签页 / 多终端 / 两个管理员，
因此本文件的每个并发用例都使用：

- **独立 sqlite3 连接**（`db_module.connect()`，与 FastAPI 每请求一条连接一致）；
- `threading.Barrier` 同步起跑（不是"一个连接顺序调用两次"）；
- future 超时，避免锁等待把测试挂死。

覆盖（对应 review 第 7 节 A–E）：

| # | 场景 | 断言 |
| --- | --- | --- |
| A | ROUND_ROBIN canonical vs canonical | 恰好一个成功、一个 409；N*(N-1)/2 场且无重复对阵 |
| B | SINGLE_ELIMINATION 同时生成 | 只有一套 bracket（4/2/1），无重复 (round, match_index) |
| C | GROUP_KNOCKOUT canonical vs legacy | 恰好一个成功；只有一套小组比赛 |
| D | generation vs format update | 只允许两种 serialized 结果，绝不出现 format 与已生成赛制不一致 |
| E | 生成中途注入异常 | 整体回滚：Match = 0、stage 未推进、没有半套签表 |

## 边界

本文件只验证事务边界，不改动任何赛制算法、排名或比分规则。
`conn` 只用来做**前置搭建与事后断言**；真正的并发写全部在 worker 的独立连接上完成。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from typing import Callable, TypeVar

import pytest

from app import db as db_module
from app import repository as repo
from app.services import entries as entries_service
from app.services import formats as formats_service
from app.services import knockout as knockout_service
from app.services import tournaments as tournaments_service

T = TypeVar("T")


def _run_concurrently(workers: int, operation: Callable[[object, int], T]):
    """同步启动 workers 个**独立连接**，返回每个 worker 的 ``("ok"/"error", value)``。"""
    barrier = threading.Barrier(workers, timeout=5)

    def run(index: int):
        connection = db_module.connect()
        try:
            barrier.wait(timeout=5)
            try:
                return "ok", operation(connection, index)
            except Exception as exc:  # 业务错误由测试断言，不让 future 直接爆栈。
                return "error", exc
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run, index) for index in range(workers)]
        return [future.result(timeout=20) for future in futures]


def _assert_no_raw_sqlite_error(results: list[tuple[str, object]]) -> None:
    for kind, value in results:
        if kind == "error":
            assert not isinstance(value, sqlite3.Error), (
                "SQLite 错误泄漏到服务层，应转换为业务冲突", repr(value)
            )


def _partition(results):
    successes = [value for kind, value in results if kind == "ok"]
    errors = [value for kind, value in results if kind == "error"]
    return successes, errors


def _seed_tournament(
    conn,
    *,
    name: str,
    format_code: str,
    players: int,
    tables: int = 3,
    groups: int = 1,
    rule_config: dict | None = None,
) -> int:
    """把赛事搭到"名单已确认、等待生成"的状态，并**提交**（worker 才有机会抢到锁）。"""
    tournament = repo.create_tournament(
        conn,
        name,
        "2026-10-05",
        tables,
        groups,
        2,
        format_code=format_code,
        rule_config=rule_config or {},
        rule_version=1,
    )
    repo.create_tables_for_tournament(conn, tournament["id"], tables)
    for index in range(1, players + 1):
        repo.add_player(conn, tournament["id"], f"选手{index:02d}", None)
    entries_service.confirm_roster(conn, tournament["id"])
    conn.commit()
    assert repo.list_entries(conn, tournament["id"]), "前置：必须已有 ACTIVE 参赛位"
    assert repo.list_matches(conn, tournament["id"]) == [], "前置：不得预生成比赛"
    return tournament["id"]


# ------------------------------------------------------------- A. canonical vs canonical

def test_round_robin_concurrent_generation_has_exactly_one_winner(conn, test_db_path):
    """同一 ROUND_ROBIN 赛事两个并发 `/generate-matches`：恰好一个成功。"""
    tid = _seed_tournament(
        conn, name="并发-循环赛", format_code=formats_service.ROUND_ROBIN, players=6
    )

    results = _run_concurrently(
        2, lambda worker, _index: formats_service.generate_matches_for_tournament(worker, tid)
    )

    _assert_no_raw_sqlite_error(results)
    successes, errors = _partition(results)
    assert len(successes) == 1, [repr(value) for value in errors]
    assert len(errors) == 1, results
    # 失败方必须是业务 409（锁竞争或"已生成"守卫），不能是 500。
    assert getattr(errors[0], "code", None) == 409, repr(errors[0])
    assert successes[0].matches_generated == 15

    matches = repo.list_matches(conn, tid)
    assert len(matches) == 15, f"6 人单循环应恰好 15 场，实际 {len(matches)}"
    pairs = {frozenset((m["entry_a_id"], m["entry_b_id"])) for m in matches}
    assert len(pairs) == 15, "出现重复对阵（双写）"
    assert all(m["entry_a_id"] != m["entry_b_id"] for m in matches)
    # 阶段只推进一次，且是生成的终态。
    assert repo.get_tournament(conn, tid)["stage"] == "GROUP_STAGE"


def test_group_knockout_concurrent_generation_has_exactly_one_winner(conn, test_db_path):
    """GROUP_KNOCKOUT canonical 并发：只有一套小组比赛。"""
    tid = _seed_tournament(
        conn, name="并发-小组淘汰", format_code=formats_service.GROUP_KNOCKOUT,
        players=8, groups=2, tables=4,
    )
    # 小组淘汰需要先分组（分组本身由既有服务负责，不在本文件的验证范围内）。
    from app.services import groups as groups_service

    groups_service.auto_group_tournament(conn, tid)
    conn.commit()

    results = _run_concurrently(
        2, lambda worker, _index: formats_service.generate_matches_for_tournament(worker, tid)
    )

    _assert_no_raw_sqlite_error(results)
    successes, errors = _partition(results)
    assert len(successes) == 1, [repr(value) for value in errors]
    assert getattr(errors[0], "code", None) == 409, repr(errors[0])

    matches = repo.list_matches(conn, tid)
    assert len(matches) == 12, f"2 组 × 4 人单循环应恰好 12 场，实际 {len(matches)}"
    pairs = {frozenset((m["entry_a_id"], m["entry_b_id"])) for m in matches}
    assert len(pairs) == 12, "出现重复对阵（双写）"


# ------------------------------------------------------------- B. 单淘汰同时生成

def test_single_elimination_concurrent_generation_keeps_one_bracket(conn, test_db_path):
    """同一 SINGLE_ELIMINATION 赛事两个并发生成：只有一套 bracket，BYE 不重复。"""
    tid = _seed_tournament(
        conn, name="并发-单淘汰", format_code=formats_service.SINGLE_ELIMINATION,
        players=8, tables=4, rule_config={"draw_seed": 20261005},
    )

    results = _run_concurrently(
        2, lambda worker, _index: formats_service.generate_matches_for_tournament(worker, tid)
    )

    _assert_no_raw_sqlite_error(results)
    successes, errors = _partition(results)
    assert len(successes) == 1, [repr(value) for value in errors]
    assert getattr(errors[0], "code", None) == 409, repr(errors[0])

    knockout = repo.list_matches(conn, tid, "KNOCKOUT")
    assert len(knockout) == 7, f"8 人主签应恰好 7 场，实际 {len(knockout)}"
    # 不得出现第二套 bracket：每个签位唯一。
    positions = [(m["round"], m["match_index"]) for m in knockout]
    assert len(set(positions)) == len(positions), "出现重复签位（两套 bracket）"
    per_round = [len([m for m in knockout if m["round"] == r]) for r in (1, 2, 3)]
    assert per_round == [4, 2, 1]
    assert repo.get_tournament(conn, tid)["stage"] == "KNOCKOUT"


def test_single_elimination_concurrent_generation_six_entries_keeps_byes_single(
    conn, test_db_path
):
    """6 人（非 2 幂）并发生成：BYE / WALKOVER 不得重复登记。"""
    tid = _seed_tournament(
        conn, name="并发-单淘汰-六人", format_code=formats_service.SINGLE_ELIMINATION,
        players=6, rule_config={"draw_seed": 20261005},
    )

    results = _run_concurrently(
        2, lambda worker, _index: formats_service.generate_matches_for_tournament(worker, tid)
    )

    _assert_no_raw_sqlite_error(results)
    successes, errors = _partition(results)
    assert len(successes) == 1, [repr(value) for value in errors]
    assert getattr(errors[0], "code", None) == 409, repr(errors[0])

    knockout = repo.list_matches(conn, tid, "KNOCKOUT")
    assert len(knockout) == 7
    walkovers = [m for m in knockout if m.get("result_type") == "WALKOVER"]
    assert len(walkovers) == 2, f"轮空应恰好 2 场，实际 {len(walkovers)}"


# ------------------------------------------------------------- C. canonical vs legacy

def test_canonical_and_legacy_generation_race_has_exactly_one_winner(conn, test_db_path):
    """GROUP_KNOCKOUT：`/generate-matches` 与 legacy `/generate-group-matches` 并发。

    两个入口最终进入同一个事务安全生成边界，因此只能有一个成功；
    另一个 409，且不得出现第二套小组比赛。
    """
    tid = _seed_tournament(
        conn, name="并发-canonical-vs-legacy", format_code=formats_service.GROUP_KNOCKOUT,
        players=8, groups=2, tables=4,
    )
    from app.services import groups as groups_service

    groups_service.auto_group_tournament(conn, tid)
    conn.commit()

    def operation(worker, index):
        if index == 0:
            return formats_service.generate_matches_for_tournament(worker, tid)
        return formats_service.generate_group_matches_compat(worker, tid)

    results = _run_concurrently(2, operation)

    _assert_no_raw_sqlite_error(results)
    successes, errors = _partition(results)
    assert len(successes) == 1, [repr(value) for value in errors]
    assert getattr(errors[0], "code", None) == 409, repr(errors[0])

    matches = repo.list_matches(conn, tid)
    assert len(matches) == 12, f"应恰好一套小组比赛（12 场），实际 {len(matches)}"
    pairs = {frozenset((m["entry_a_id"], m["entry_b_id"])) for m in matches}
    assert len(pairs) == 12, "canonical 与 legacy 双写产生重复对阵"


# ------------------------------------------------------------- D. generation vs format update

def test_format_update_after_generation_is_rejected(conn, test_db_path):
    """CASE A（确定性顺序）：先生成 → 后改赛制必须 409，赛制不得变化。"""
    tid = _seed_tournament(
        conn, name="顺序-先生成后改赛制", format_code=formats_service.ROUND_ROBIN, players=6
    )
    assert formats_service.generate_matches_for_tournament(conn, tid).matches_generated == 15

    with pytest.raises(tournaments_service.TournamentFormatError) as excinfo:
        tournaments_service.update_format_config(
            conn, tid, formats_service.SINGLE_ELIMINATION, {}
        )
    assert excinfo.value.code == 409
    assert "已产生比赛" in str(excinfo.value)

    tournament = repo.get_tournament(conn, tid)
    assert tournament["format_code"] == formats_service.ROUND_ROBIN
    assert len(repo.list_matches(conn, tid, "GROUP")) == 15


def test_generation_after_format_update_uses_new_handler(conn, test_db_path):
    """CASE B（确定性顺序）：先改赛制 → 后生成必须使用**新** Handler。

    生成的比赛必须与已持久化的 `format_code` 一致：
    绝不出现 `format_code = SINGLE_ELIMINATION` 而库里是 GROUP 小组赛。
    """
    tid = _seed_tournament(
        conn, name="顺序-先改赛制后生成", format_code=formats_service.ROUND_ROBIN, players=8
    )
    tournaments_service.update_format_config(
        conn, tid, formats_service.SINGLE_ELIMINATION, {"draw_seed": 20261005}
    )
    assert repo.get_tournament(conn, tid)["format_code"] == formats_service.SINGLE_ELIMINATION

    result = formats_service.generate_matches_for_tournament(conn, tid)
    assert result.matches_generated == 7  # 8 人单淘汰主签，不是 28 场循环赛

    assert repo.list_matches(conn, tid, "GROUP") == [], "单淘汰不得生成小组赛"
    assert len(repo.list_matches(conn, tid, "KNOCKOUT")) == 7
    assert repo.get_tournament(conn, tid)["stage"] == "KNOCKOUT"


def test_generation_and_format_update_race_never_mismatch(conn, test_db_path):
    """真并发：一个请求生成、一个请求改赛制。

    只允许两种 serialized 结果之一，绝不出现"赛制已改但按旧赛制生成"：
    - 生成先拿锁 → 改赛制后拿锁时发现已有比赛 → 409，赛制不变；
    - 改赛制先拿锁 → 生成后拿锁时重新读取新 `format_code` → 按新 Handler 生成。
    """
    tid = _seed_tournament(
        conn, name="并发-生成与改赛制", format_code=formats_service.ROUND_ROBIN, players=8
    )

    def operation(worker, index):
        if index == 0:
            return formats_service.generate_matches_for_tournament(worker, tid)
        return tournaments_service.update_format_config(
            worker, tid, formats_service.SINGLE_ELIMINATION, {"draw_seed": 20261005}
        )

    results = _run_concurrently(2, operation)

    _assert_no_raw_sqlite_error(results)
    successes, errors = _partition(results)
    # 至少一个成功；两个都成功也是合法的 serialized 结果（改赛制先完成）。
    assert len(successes) >= 1, [repr(value) for value in errors]
    for error in errors:
        assert getattr(error, "code", None) == 409, repr(error)

    format_code = repo.get_tournament(conn, tid)["format_code"]
    group_matches = repo.list_matches(conn, tid, "GROUP")
    knockout_matches = repo.list_matches(conn, tid, "KNOCKOUT")
    stage = repo.get_tournament(conn, tid)["stage"]

    if format_code == formats_service.ROUND_ROBIN:
        # CASE A：赛制没改成 → 生成必须是循环赛，且不能有淘汰签。
        assert knockout_matches == []
        assert len(group_matches) == 28  # 8 × 7 / 2
        assert stage == "GROUP_STAGE"
    elif format_code == formats_service.SINGLE_ELIMINATION:
        # CASE B：赛制先改成单淘汰 → 必须按新 Handler 生成，库里不能是小组赛。
        assert group_matches == [], "赛制已是单淘汰，却生成了小组赛（用了旧 Handler）"
        assert len(knockout_matches) == 7
        assert stage == "KNOCKOUT"
    else:  # pragma: no cover - 只有出现新赛制才可能走到
        raise AssertionError(f"意外的 format_code：{format_code!r}")


# ------------------------------------------------------------- E. 整体回滚

def test_round_robin_generation_failure_rolls_back_everything(
    conn, test_db_path, monkeypatch
):
    """循环赛生成中途注入异常：Match = 0、阶段未推进。"""
    tid = _seed_tournament(
        conn, name="回滚-循环赛", format_code=formats_service.ROUND_ROBIN, players=6
    )
    original = repo.create_match
    calls = {"count": 0}

    def fail_after_a_few(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] >= 4:
            raise RuntimeError("注入失败：循环赛生成中途异常")
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, "create_match", fail_after_a_few)
    with pytest.raises(RuntimeError, match="注入失败"):
        formats_service.generate_matches_for_tournament(conn, tid)
    monkeypatch.setattr(repo, "create_match", original)

    assert repo.list_matches(conn, tid) == [], "失败后仍残留半套循环赛"
    assert repo.get_tournament(conn, tid)["stage"] == "REGISTRATION", "阶段被提前推进"


def test_single_elimination_generation_failure_rolls_back_bracket(
    conn, test_db_path, monkeypatch
):
    """单淘汰建签中途注入异常：不得留下半套 bracket，阶段也不得推进。

    这是"内层提前 commit"最容易暴露的场景：若 locked 实现自己提交，
    已写入的前几轮签表会被永久留下。
    """
    tid = _seed_tournament(
        conn, name="回滚-单淘汰", format_code=formats_service.SINGLE_ELIMINATION,
        players=8, tables=4, rule_config={"draw_seed": 20261005},
    )
    original = repo.create_match
    calls = {"count": 0}

    def fail_after_a_few(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] >= 3:
            raise RuntimeError("注入失败：建签中途异常")
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, "create_match", fail_after_a_few)
    with pytest.raises(RuntimeError, match="注入失败"):
        formats_service.generate_matches_for_tournament(conn, tid)
    monkeypatch.setattr(repo, "create_match", original)

    assert repo.list_matches(conn, tid, "KNOCKOUT") == [], "失败后仍残留半套签表"
    assert repo.get_tournament(conn, tid)["stage"] == "REGISTRATION"
    # 既有守卫仍然生效：回滚之后可以重新正常生成。
    assert formats_service.generate_matches_for_tournament(conn, tid).matches_generated == 7
    assert len(repo.list_matches(conn, tid, "KNOCKOUT")) == 7


# ------------------------------------------------------------- 边界：内层不再提前提交

def test_locked_implementations_do_not_commit(conn, test_db_path):
    """结构性断言：locked 实现不得自己结束事务（否则写锁会被提前释放）。

    只要 `_generate_*_locked` 里出现 `conn.commit()`，外层写锁就会在
    invariant → generation → stage update 走完之前释放，Finding #1 的修复即失效。
    """
    import inspect

    locked_functions = [
        ("app/services/matches.py", __import__(
            "app.services.matches", fromlist=["x"]
        )._generate_group_matches_locked),
        ("app/services/matches.py", __import__(
            "app.services.matches", fromlist=["x"]
        )._generate_round_robin_matches_locked),
        ("app/services/knockout.py", knockout_service._generate_single_elimination_locked),
    ]
    for path, function in locked_functions:
        source = inspect.getsource(function)
        assert "conn.commit()" not in source, f"{path}::{function.__name__} 不得自行提交"
        assert "conn.rollback()" not in source, f"{path}::{function.__name__} 不得自行回滚"
        assert "BEGIN IMMEDIATE" not in source, f"{path}::{function.__name__} 不得自己开事务"


def test_generation_holds_the_write_lock_across_the_whole_flow(conn, test_db_path):
    """写锁必须覆盖"读到已提交 format_code"到"生成 + 阶段推进"的全过程。

    做法：在生成过程中（Handler 已解析、写第一场比赛之前）从一个**独立连接**尝试
    立即取写锁；此时它必须拿不到锁（BUSY），证明锁确实被本事务持有。
    """
    tid = _seed_tournament(
        conn, name="持锁-全过程", format_code=formats_service.ROUND_ROBIN, players=6
    )
    observed: dict[str, object] = {}
    original = formats_service.resolve_format_handler

    def spy(format_code):
        handler = original(format_code)
        # 此刻外层已经 BEGIN IMMEDIATE 且已读到已提交的 format_code；
        # 用一个全新连接尝试写操作：必须因写锁被持有而失败。
        probe = db_module.connect()
        try:
            probe.execute("BEGIN IMMEDIATE")
            observed["lock_free"] = True
            probe.rollback()
        except sqlite3.OperationalError as exc:
            observed["lock_free"] = False
            observed["error"] = str(exc)
        finally:
            probe.close()
        return handler

    import app.services.formats as formats_module

    formats_module.resolve_format_handler = spy
    try:
        assert formats_service.generate_matches_for_tournament(conn, tid).matches_generated == 15
    finally:
        formats_module.resolve_format_handler = original

    assert observed.get("lock_free") is False, (
        "生成过程中写锁没有被持有：另一个连接仍能取到写锁", observed
    )
    assert "lock" in str(observed.get("error", "")).lower() or "busy" in str(
        observed.get("error", "")
    ).lower()
