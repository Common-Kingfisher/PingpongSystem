"""D6A 并发、事务回滚与失败注入自动化证据。

覆盖目标：
- 5 个并发写请求不会形成同一业务事实的双写；
- request_id 幂等/冲突语义在并发下稳定；
- 同一球台不会被两场 WAITING 比赛同时占用；
- 名单确认与迟到确认不会产生半状态；
- 多表写链路在失败注入后整体回滚。

所有 worker 都使用独立 sqlite3 连接，并通过 Barrier 同步起跑；future 设置
超时，测试不会因锁等待无限挂住。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import sqlite3
import threading
from typing import Callable, TypeVar

import pytest

from app import db as db_module
from app import repository as repo
from app.models import MatchStatus, SystemRole, TableStatus
from app.services import entries as entries_service
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import players as players_service
from app.services import qualification_decisions as decision_service
from app.services import registrations as registrations_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service
from app.services import tournaments as tournaments_service


T = TypeVar("T")


def _run_concurrently(workers: int, operation: Callable[[object, int], T]):
    """同步启动 workers 个独立连接，返回每个 worker 的 ``("ok"/"error", value)``。"""
    barrier = threading.Barrier(workers, timeout=5)

    def run(index: int):
        connection = db_module.connect()
        try:
            barrier.wait(timeout=5)
            try:
                return "ok", operation(connection, index)
            except Exception as exc:  # 由测试断言业务错误，而不是让 future 直接爆栈。
                return "error", exc
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run, index) for index in range(workers)]
        return [future.result(timeout=15) for future in futures]


def _service_tournament(
    conn,
    *,
    name: str = "D6A 并发赛事",
    players: int = 6,
    tables: int = 6,
    groups: int = 1,
    registration_enabled: bool = False,
    schedule: bool = True,
) -> int:
    tournament = repo.create_tournament(
        conn,
        name,
        "2026-09-23",
        tables,
        groups,
        1,
        registration_enabled=registration_enabled,
    )
    repo.create_tables_for_tournament(conn, tournament["id"], tables)
    for index in range(1, players + 1):
        repo.add_player(conn, tournament["id"], f"选手{index:02d}", None)
    conn.commit()
    if schedule:
        groups_service.auto_group_tournament(conn, tournament["id"])
        matches_service.generate_group_matches(conn, tournament["id"])
    conn.commit()
    return tournament["id"]


def _ensure_test_user(conn, username: str = "d6a-test-user") -> dict:
    """创建真实用户，满足 Registration.confirmed_by_user_id 的外键约束。"""
    user = repo.get_user_by_username(conn, username)
    if user is None:
        user = repo.create_user(
            conn,
            username,
            "D6A 测试用户",
            "d6a-test-password-hash",
            SystemRole.EVENT_ADMIN.value,
        )
        conn.commit()
    return user


def _registration(conn, tournament_id: int, name: str = "并发报名者") -> dict:
    registration = repo.create_registration(
        conn,
        tournament_id,
        name=name,
        affiliation="D6A 测试学院",
        contact="13900000000",
        rating_points=1600,
    )
    conn.commit()
    return registration


def _score_match(conn, tournament_id: int) -> dict:
    match = repo.list_matches(conn, tournament_id)[0]
    conn.commit()
    return match


def _fully_tied_group(conn) -> tuple[int, int, list[int]]:
    """构造三人循环互克且无小分区分的真实人工裁定前置状态。"""
    tournament_id = _service_tournament(
        conn,
        name="D6A 人工裁定并发",
        players=3,
        tables=2,
        groups=1,
        schedule=True,
    )
    entries = sorted(
        repo.list_entries(conn, tournament_id), key=lambda item: item["id"]
    )
    entry_ids = [entry["id"] for entry in entries]
    first, second, third = entry_ids
    winner_by_pair = {
        frozenset((first, second)): first,
        frozenset((second, third)): second,
        frozenset((first, third)): third,
    }
    for match in repo.list_matches(conn, tournament_id):
        side_a, side_b = match["entry_a_id"], match["entry_b_id"]
        winner = winner_by_pair[frozenset((side_a, side_b))]
        score = (2, 0) if winner == side_a else (0, 2)
        scores_service.record_score(conn, match["id"], *score)
        games = [(11, 5), (11, 5)] if winner == side_a else [(5, 11), (5, 11)]
        scores_service.revise_score(conn, match["id"], None, None, games=games)

    group_id = repo.list_groups(conn, tournament_id)[0]["id"]
    return tournament_id, group_id, entry_ids


def _assert_no_raw_sqlite_error(results: list[tuple[str, object]]) -> None:
    for kind, value in results:
        if kind == "error":
            assert not isinstance(value, sqlite3.Error), (
                "SQLite 错误泄漏到服务层，应转换为业务冲突", repr(value)
            )


def test_d6a_registration_confirm_5_workers_creates_one_player(conn, test_db_path):
    tournament_id = _service_tournament(
        conn,
        name="D6A 五人确认同一报名",
        players=0,
        registration_enabled=True,
        schedule=False,
    )
    registration = _registration(conn, tournament_id)
    owner_id = _ensure_test_user(conn)["id"]

    results = _run_concurrently(
        5,
        lambda worker, _: registrations_service.confirm_registration(
            worker,
            tournament_id,
            registration["id"],
            confirmed_by_user_id=owner_id,
        ),
    )

    _assert_no_raw_sqlite_error(results)
    successes = [value for kind, value in results if kind == "ok"]
    assert len(successes) == 1, [repr(value) for kind, value in results if kind == "error"]
    assert len(repo.list_players(conn, tournament_id)) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE id = ? AND status = 'CONFIRMED'",
        (registration["id"],),
    ).fetchone()[0] == 1


def test_d6a_registration_confirm_6_workers_creates_one_player(conn, test_db_path):
    tournament_id = _service_tournament(
        conn,
        name="D6A 六人确认同一报名",
        players=0,
        registration_enabled=True,
        schedule=False,
    )
    registration = _registration(conn, tournament_id)
    owner_id = _ensure_test_user(conn)["id"]

    results = _run_concurrently(
        6,
        lambda worker, _: registrations_service.confirm_registration(
            worker,
            tournament_id,
            registration["id"],
            confirmed_by_user_id=owner_id,
        ),
    )

    _assert_no_raw_sqlite_error(results)
    successes = [value for kind, value in results if kind == "ok"]
    assert len(successes) == 1, [repr(value) for kind, value in results if kind == "error"]
    players = repo.list_players(conn, tournament_id)
    assert len(players) == 1
    stored = repo.get_registration(conn, registration["id"])
    assert stored["status"] == "CONFIRMED"
    assert stored["confirmed_player_id"] == players[0]["id"]


def test_d6a_confirm_multiple_registrations_concurrently(conn, test_db_path):
    tournament_id = _service_tournament(
        conn,
        name="D6A 并发确认不同报名",
        players=0,
        registration_enabled=True,
        schedule=False,
    )
    registrations = [
        _registration(conn, tournament_id, f"并发报名者{index}")
        for index in range(5)
    ]
    owner_id = _ensure_test_user(conn)["id"]

    results = _run_concurrently(
        5,
        lambda worker, index: registrations_service.confirm_registration(
            worker,
            tournament_id,
            registrations[index]["id"],
            confirmed_by_user_id=owner_id,
        ),
    )

    _assert_no_raw_sqlite_error(results)
    assert all(kind == "ok" for kind, _ in results), [
        repr(value) for kind, value in results if kind == "error"
    ]
    stored = [repo.get_registration(conn, item["id"]) for item in registrations]
    assert all(item["status"] == "CONFIRMED" for item in stored)
    confirmed_player_ids = [item["confirmed_player_id"] for item in stored]
    assert all(player_id is not None for player_id in confirmed_player_ids)
    assert len(set(confirmed_player_ids)) == 5
    assert {player["id"] for player in repo.list_players(conn, tournament_id)} == set(
        confirmed_player_ids
    )


def test_d6a_record_score_5_workers_single_business_fact(conn, test_db_path):
    tournament_id = _service_tournament(conn, name="D6A 五人抢录同一比分")
    match = _score_match(conn, tournament_id)

    results = _run_concurrently(
        5,
        lambda worker, index: scores_service.record_score(
            worker, match["id"], 2, 1, request_id=f"d6a-record-{index}"
        ),
    )

    _assert_no_raw_sqlite_error(results)
    successes = [value for kind, value in results if kind == "ok"]
    assert len(successes) == 1, [repr(value) for kind, value in results if kind == "error"]
    assert conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE match_id = ?", (match["id"],)
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM score_requests WHERE match_id = ?", (match["id"],)
    ).fetchone()[0] == 1
    stored = repo.get_match(conn, match["id"])
    assert stored["status"] == MatchStatus.FINISHED.value
    assert (stored["player_a_score"], stored["player_b_score"]) == (2, 1)


def test_d6a_same_request_id_same_payload_is_idempotent(conn, test_db_path):
    tournament_id = _service_tournament(conn, name="D6A request_id 幂等")
    match = _score_match(conn, tournament_id)
    request_id = "d6a-same-request-same-payload"

    results = _run_concurrently(
        5,
        lambda worker, _: scores_service.record_score(
            worker, match["id"], 2, 0, request_id=request_id
        ),
    )

    _assert_no_raw_sqlite_error(results)
    assert all(kind == "ok" for kind, _ in results), results
    assert conn.execute(
        "SELECT COUNT(*) FROM score_requests WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == 1


def test_d6a_same_request_id_different_payload_is_409(conn, test_db_path):
    tournament_id = _service_tournament(conn, name="D6A request_id 冲突")
    match = _score_match(conn, tournament_id)
    request_id = "d6a-same-request-different-payload"

    def operation(worker, index):
        return scores_service.record_score(
            worker,
            match["id"],
            2 if index == 0 else 0,
            0 if index == 0 else 2,
            request_id=request_id,
        )

    results = _run_concurrently(2, operation)
    _assert_no_raw_sqlite_error(results)
    successes = [value for kind, value in results if kind == "ok"]
    errors = [value for kind, value in results if kind == "error"]
    assert len(successes) == 1, results
    assert len(errors) == 1, results
    assert errors[0].code == 409
    assert conn.execute(
        "SELECT COUNT(*) FROM score_requests WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == 1


def test_d6a_two_matches_compete_for_one_table(conn, test_db_path):
    tournament_id = _service_tournament(
        conn, name="D6A 球台抢占", players=4, tables=1, groups=2
    )
    table = repo.list_tables(conn, tournament_id)[0]
    matches = repo.list_matches(conn, tournament_id)
    assert len(matches) == 2
    conn.commit()

    results = _run_concurrently(
        2,
        lambda worker, index: scheduling_service.assign_table(
            worker, matches[index]["id"], table["id"]
        ),
    )

    _assert_no_raw_sqlite_error(results)
    successes = [value for kind, value in results if kind == "ok"]
    assert len(successes) == 1, [repr(value) for kind, value in results if kind == "error"]
    assert repo.get_table(conn, table["id"])["status"] == TableStatus.OCCUPIED.value
    playing = [
        match for match in repo.list_matches(conn, tournament_id)
        if match["status"] == MatchStatus.PLAYING.value
    ]
    assert len(playing) == 1
    assert playing[0]["table_id"] == table["id"]


def test_d6a_confirm_roster_and_late_confirmation_do_not_create_half_state(conn, test_db_path):
    tournament_id = _service_tournament(
        conn, name="D6A 名单锁定竞态", players=2, tables=2, groups=1,
        registration_enabled=True, schedule=False,
    )
    registration = _registration(conn, tournament_id, "迟到确认者")
    owner_id = _ensure_test_user(conn)["id"]

    def operation(worker, index):
        if index == 0:
            return entries_service.confirm_roster(worker, tournament_id)
        return registrations_service.confirm_registration(
            worker, tournament_id, registration["id"], confirmed_by_user_id=owner_id
        )

    results = _run_concurrently(2, operation)
    _assert_no_raw_sqlite_error(results)

    tournament = repo.get_tournament(conn, tournament_id)
    registration_row = repo.get_registration(conn, registration["id"])
    players = repo.list_players(conn, tournament_id)
    assert len(players) in (2, 3)
    assert not (
        registration_row["status"] == "CONFIRMED"
        and registration_row["confirmed_player_id"] is None
    )
    if tournament["roster_confirmed"]:
        assert registration_row["status"] in ("PENDING", "CONFIRMED")
    if registration_row["status"] == "CONFIRMED":
        assert registration_row["confirmed_player_id"] is not None
        assert any(player["id"] == registration_row["confirmed_player_id"] for player in players)


def test_d6a_concurrent_revise_keeps_score_and_games_consistent(conn, test_db_path):
    tournament_id = _service_tournament(conn, name="D6A 并发改分")
    match = _score_match(conn, tournament_id)
    scores_service.record_score(conn, match["id"], 2, 1)

    results = _run_concurrently(
        2,
        lambda worker, index: scores_service.revise_score(
            worker,
            match["id"],
            2 if index == 0 else 0,
            0 if index == 0 else 2,
        ),
    )

    _assert_no_raw_sqlite_error(results)
    assert any(kind == "ok" for kind, _ in results), results
    stored = repo.get_match(conn, match["id"])
    assert (stored["player_a_score"], stored["player_b_score"]) in ((2, 0), (0, 2))
    assert stored["status"] == MatchStatus.FINISHED.value
    games = conn.execute(
        "SELECT COUNT(*) FROM match_games WHERE match_id = ?", (match["id"],)
    ).fetchone()[0]
    assert games in (0, 1, 2)


def test_d6a_concurrent_qualification_decisions_keep_one_active(conn, test_db_path):
    tournament_id, group_id, entry_ids = _fully_tied_group(conn)

    results = _run_concurrently(
        2,
        lambda worker, index: decision_service.create_decision(
            worker,
            tournament_id,
            group_id,
            [entry_ids[index]],
            f"并发人工裁定{index}",
            f"主裁{index}",
        ),
    )

    _assert_no_raw_sqlite_error(results)
    assert all(kind == "ok" for kind, _ in results), [
        repr(value) for kind, value in results if kind == "error"
    ]
    history = repo.list_qualification_decisions(conn, group_id)
    active = repo.get_active_qualification_decision(conn, group_id)
    assert len(history) == 2
    assert sum(item["invalidated_at"] is None for item in history) == 1
    assert active is not None
    assert active["id"] == max(item["id"] for item in history)


def test_d6a_qualification_decision_failure_keeps_previous_active(
    conn, test_db_path, monkeypatch
):
    tournament_id, group_id, entry_ids = _fully_tied_group(conn)
    first = decision_service.create_decision(
        conn,
        tournament_id,
        group_id,
        [entry_ids[0]],
        "先创建一条有效裁定",
        "主裁甲",
    )

    def fail_create_decision(*args, **kwargs):
        raise RuntimeError("D6A 注入：旧裁定失效后、新裁定插入前失败")

    monkeypatch.setattr(repo, "create_qualification_decision", fail_create_decision)
    with pytest.raises(RuntimeError, match="D6A 注入"):
        decision_service.create_decision(
            conn,
            tournament_id,
            group_id,
            [entry_ids[1]],
            "该裁定应当整体回滚",
            "主裁乙",
        )

    history = repo.list_qualification_decisions(conn, group_id)
    active = repo.get_active_qualification_decision(conn, group_id)
    assert len(history) == 1
    assert active is not None
    assert active["id"] == first["id"]
    assert active["selected_entry_ids"] == f"[{entry_ids[0]}]"


def test_d6a_registration_confirm_failure_rolls_back_player(conn, test_db_path, monkeypatch):
    tournament_id = _service_tournament(
        conn,
        name="D6A 报名确认失败回滚",
        players=0,
        registration_enabled=True,
        schedule=False,
    )
    registration = _registration(conn, tournament_id)
    owner_id = _ensure_test_user(conn)["id"]
    original_confirm = repo.confirm_registration

    def fail_after_player_insert(*args, **kwargs):
        raise RuntimeError("D6A 注入：Player 已写入，Registration 更新前失败")

    monkeypatch.setattr(repo, "confirm_registration", fail_after_player_insert)
    with pytest.raises(RuntimeError, match="D6A 注入"):
        registrations_service.confirm_registration(
            conn, tournament_id, registration["id"], confirmed_by_user_id=owner_id
        )
    monkeypatch.setattr(repo, "confirm_registration", original_confirm)

    assert repo.list_players(conn, tournament_id) == []
    assert repo.get_registration(conn, registration["id"])["status"] == "PENDING"


def test_d6a_revise_failure_rolls_back_match_and_match_games(conn, test_db_path, monkeypatch):
    tournament_id = _service_tournament(conn, name="D6A 改分失败回滚")
    match = _score_match(conn, tournament_id)
    scores_service.record_score(conn, match["id"], 2, 1)

    def fail_after_match_update(*args, **kwargs):
        raise RuntimeError("D6A 注入：Match 已更新，审计写入前失败")

    monkeypatch.setattr(repo, "create_score_audit", fail_after_match_update)
    with pytest.raises(RuntimeError, match="D6A 注入"):
        scores_service.revise_score(conn, match["id"], 0, 2)

    stored = repo.get_match(conn, match["id"])
    assert (stored["player_a_score"], stored["player_b_score"]) == (2, 1)
    assert conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE match_id = ?", (match["id"],)
    ).fetchone()[0] == 1


def test_d6a_create_tournament_failure_before_owner_grant_rolls_back(conn, test_db_path, monkeypatch):
    owner_id = _ensure_test_user(conn)["id"]

    def fail_owner_grant(*args, **kwargs):
        raise RuntimeError("D6A 注入：Tournament 已插入，OWNER grant 前失败")

    monkeypatch.setattr(repo, "upsert_tournament_admin", fail_owner_grant)
    before = conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0]
    with pytest.raises(RuntimeError, match="D6A 注入"):
        tournaments_service.create_tournament_with_tables(
            conn,
            "D6A 创建失败回滚",
            dt.date(2026, 9, 23),
            2,
            1,
            1,
            owner_user_id=owner_id,
        )
    after = conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0]
    assert after == before


def test_d6a_withdrawal_failure_rolls_back_entry_and_table(conn, test_db_path, monkeypatch):
    tournament_id = _service_tournament(conn, name="D6A 退赛失败回滚")
    match = _score_match(conn, tournament_id)
    table = repo.list_tables(conn, tournament_id)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    entry_id = match["player_a_id"]
    entry = repo.get_entry(conn, entry_id)
    assert entry is not None

    def fail_release_table_after_withdraw(*args, **kwargs):
        raise RuntimeError("D6A 注入：Entry 已退赛，释放球台前失败")

    monkeypatch.setattr(repo, "update_table_status", fail_release_table_after_withdraw)
    with pytest.raises(RuntimeError, match="D6A 注入"):
        entries_service.withdraw_from_tournament(
            conn, tournament_id, entry_id, "D6A 主裁", "注入失败"
        )

    assert repo.get_entry(conn, entry_id)["status"] == "ACTIVE"
    assert repo.get_match(conn, match["id"])["status"] == MatchStatus.PLAYING.value
    assert repo.get_table(conn, table["id"])["status"] == TableStatus.OCCUPIED.value
