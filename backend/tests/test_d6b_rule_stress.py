"""D6B 规则压力测试：通过公开赛制服务验证大规模规则主链。"""

import random

import pytest

from app import repository as repo
from app.models import MatchBracket, MatchStage, MatchStatus
from app.services import formats
from app.services import entries as entries_service
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


DRAW_SEED = 20260923


def _create_group_knockout_tournament(conn, *, players: int, group_count: int, qualify: int) -> int:
    tournament = repo.create_tournament(
        conn,
        "D6B 规则压力赛",
        "2026-09-23",
        15,
        group_count,
        qualify,
        format_code=formats.GROUP_KNOCKOUT,
        rule_config={},
        rule_version=1,
    )
    repo.create_tables_for_tournament(conn, tournament["id"], 15)
    for index in range(players):
        repo.add_player(conn, tournament["id"], f"D6B选手{index + 1}", f"单位{index % 8}")
    groups_service.auto_group_tournament(conn, tournament["id"], rng=random.Random(DRAW_SEED))
    return tournament["id"]


def _finish_scheduled_matches(conn, tournament_id: int) -> None:
    """以确定性胜者完成调度出的比赛，不依赖实际时间。"""
    for _ in range(200):
        scheduling_service.schedule_next(conn, tournament_id)
        playing = repo.list_playing_matches(conn, tournament_id)
        if playing:
            for match in playing:
                score = (2, 0) if match["entry_a_id"] < match["entry_b_id"] else (0, 2)
                scores_service.record_score(conn, match["id"], *score)
            continue
        unfinished = [
            match
            for match in repo.list_matches(conn, tournament_id)
            if match["status"] != MatchStatus.FINISHED.value
        ]
        if not unfinished:
            return
    raise AssertionError("比赛未在预期调度轮次内完成")


def _create_single_elimination_tournament(conn, *, players: int) -> tuple[int, formats.FormatHandler]:
    tournament = repo.create_tournament(
        conn,
        f"D6B {players}人单淘汰",
        "2026-09-23",
        15,
        1,
        1,
        format_code=formats.SINGLE_ELIMINATION,
        rule_config={"draw_seed": DRAW_SEED},
        rule_version=1,
    )
    repo.create_tables_for_tournament(conn, tournament["id"], 15)
    for index in range(players):
        repo.add_player(conn, tournament["id"], f"D6B单淘汰选手{index + 1}", f"单位{index % 8}")
    entries_service.confirm_roster(conn, tournament["id"])
    return tournament["id"], formats.resolve_format_handler(formats.SINGLE_ELIMINATION)


def _normalized_first_round(conn, tournament_id: int) -> list[tuple[int | None, int | None]]:
    entry_order = {
        entry["id"]: index
        for index, entry in enumerate(repo.list_entries(conn, tournament_id), start=1)
    }
    first_round = sorted(
        (
            match
            for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
            if match["bracket"] == MatchBracket.MAIN.value and match["round"] == 1
        ),
        key=lambda match: match["match_index"],
    )
    return [
        (entry_order.get(match["entry_a_id"]), entry_order.get(match["entry_b_id"]))
        for match in first_round
    ]


def _assign_and_record(conn, match_id: int, score_a: int, score_b: int) -> None:
    table = next(table for table in repo.list_tables(conn, repo.get_match(conn, match_id)["tournament_id"])
                 if table["status"] == "FREE")
    scheduling_service.assign_table(conn, match_id, table["id"])
    scores_service.record_score(conn, match_id, score_a, score_b)


def _two_finished_first_round_matches(conn) -> tuple[int, list[dict]]:
    tournament_id, handler = _create_single_elimination_tournament(conn, players=32)
    handler.generate_matches(conn, tournament_id)
    first_two = sorted(
        (
            match
            for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
            if match["bracket"] == MatchBracket.MAIN.value and match["round"] == 1
        ),
        key=lambda match: match["match_index"],
    )[:2]
    for match in first_two:
        _assign_and_record(conn, match["id"], 2, 0)
    return tournament_id, first_two


def test_64_player_group_knockout_completes_without_duplicate_qualification(conn):
    """64 人主链：96 场小组赛、32 人晋级、32 强完整推进到唯一冠军。"""
    tournament_id = _create_group_knockout_tournament(
        conn, players=64, group_count=16, qualify=2
    )
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    generation = handler.generate_matches(conn, tournament_id)
    assert generation.matches_generated == 96
    assert generation.per_group == {f"{chr(65 + index)}组": 6 for index in range(16)}

    _finish_scheduled_matches(conn, tournament_id)

    rankings = handler.calculate_ranking(conn, tournament_id)
    qualified_ids = [
        entry["entry_id"]
        for group in rankings
        for entry in group["entries"]
        if entry["qualified"]
    ]
    assert len(qualified_ids) == 32
    assert len(set(qualified_ids)) == 32
    assert all(len([entry for entry in group["entries"] if entry["qualified"]]) == 2 for group in rankings)

    handler.advance_participants(conn, tournament_id)
    knockout_matches = [
        match
        for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value
    ]
    assert [
        len([match for match in knockout_matches if match["round"] == round_no])
        for round_no in range(1, 6)
    ] == [16, 8, 4, 2, 1]
    first_round_entries = [
        entry_id
        for match in knockout_matches
        if match["round"] == 1
        for entry_id in (match["entry_a_id"], match["entry_b_id"])
    ]
    assert sorted(first_round_entries) == sorted(qualified_ids)
    assert all(
        match["prev_match_a_id"] is not None and match["prev_match_b_id"] is not None
        for match in knockout_matches
        if match["round"] > 1
    )

    _finish_scheduled_matches(conn, tournament_id)

    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "COMPLETED",
        "can_advance": False,
        "completed": True,
    }
    assert knockout_service.get_knockout(conn, tournament_id)["champion"] is not None


@pytest.mark.parametrize(
    ("players", "bracket_size", "expected_byes"),
    [(12, 16, 4), (33, 64, 31)],
)
def test_non_power_of_two_single_elimination_has_one_path_per_entry_and_one_champion(
    conn, players, bracket_size, expected_byes
):
    """12/33 人签表复用既有 BYE/WALKOVER 机制，不能生成幽灵或重复晋级。"""
    tournament_id, handler = _create_single_elimination_tournament(conn, players=players)

    handler.generate_matches(conn, tournament_id)
    main_matches = [
        match
        for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value
    ]
    first_round = [match for match in main_matches if match["round"] == 1]
    active_entry_ids = {entry["id"] for entry in repo.list_entries(conn, tournament_id)}
    first_round_entry_ids = [
        entry_id
        for match in first_round
        for entry_id in (match["entry_a_id"], match["entry_b_id"])
        if entry_id is not None
    ]

    assert len(main_matches) == bracket_size - 1
    assert len(first_round) == bracket_size // 2
    assert len([match for match in first_round if match["result_type"] == "WALKOVER"]) == expected_byes
    assert first_round_entry_ids == list(dict.fromkeys(first_round_entry_ids))
    assert set(first_round_entry_ids) == active_entry_ids
    assert handler.handle_bye(conn, tournament_id)["walkover_match_ids"]

    replay_tournament_id, replay_handler = _create_single_elimination_tournament(conn, players=players)
    replay_handler.generate_matches(conn, replay_tournament_id)
    assert _normalized_first_round(conn, tournament_id) == _normalized_first_round(
        conn, replay_tournament_id
    )

    _finish_scheduled_matches(conn, tournament_id)
    assert handler.get_completion_state(conn, tournament_id)["state"] == "COMPLETED"
    assert knockout_service.get_knockout(conn, tournament_id)["champion"] is not None


def test_first_round_winner_change_updates_waiting_downstream_slot(conn):
    """胜者反转仅在下游未开始时传播，新胜者替换旧胜者。"""
    _, first_two = _two_finished_first_round_matches(conn)
    first_match = first_two[0]
    downstream = repo.list_matches_by_prev(conn, first_match["id"])[0]
    old_winner = repo.get_match(conn, first_match["id"])["winner_entry_id"]

    scores_service.revise_score(conn, first_match["id"], 0, 2)

    changed_downstream = repo.get_match(conn, downstream["id"])
    assert changed_downstream["status"] == MatchStatus.WAITING.value
    assert first_match["entry_b_id"] in (
        changed_downstream["entry_a_id"],
        changed_downstream["entry_b_id"],
    )
    assert old_winner not in (changed_downstream["entry_a_id"], changed_downstream["entry_b_id"])


def test_first_round_winner_change_is_atomic_when_downstream_is_playing(conn):
    """下游已 PLAYING 时，换人改分必须拒绝且不留下半写入。"""
    tournament_id, first_two = _two_finished_first_round_matches(conn)
    first_match = first_two[0]
    downstream = repo.list_matches_by_prev(conn, first_match["id"])[0]
    table = next(table for table in repo.list_tables(conn, tournament_id) if table["status"] == "FREE")
    scheduling_service.assign_table(conn, downstream["id"], table["id"])
    before_upstream = repo.get_match(conn, first_match["id"])
    before_downstream = repo.get_match(conn, downstream["id"])

    with pytest.raises(scores_service.ScoreError, match="影响后续比赛"):
        scores_service.revise_score(conn, first_match["id"], 0, 2)

    assert repo.get_match(conn, first_match["id"]) == before_upstream
    assert repo.get_match(conn, downstream["id"]) == before_downstream


def test_first_round_winner_change_is_atomic_when_deep_downstream_is_finished(conn):
    """32 人链路已完赛后反转首轮胜者，不能破坏已结束的深层比赛。"""
    tournament_id, handler = _create_single_elimination_tournament(conn, players=32)
    handler.generate_matches(conn, tournament_id)
    _finish_scheduled_matches(conn, tournament_id)
    first_match = next(
        match
        for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value and match["round"] == 1
    )
    final = next(
        match
        for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value and match["round"] == 5
    )
    before_upstream = repo.get_match(conn, first_match["id"])
    before_final = repo.get_match(conn, final["id"])
    reversal = (0, 2) if before_upstream["winner_entry_id"] == first_match["entry_a_id"] else (2, 0)

    with pytest.raises(scores_service.ScoreError, match="影响后续比赛"):
        scores_service.revise_score(conn, first_match["id"], *reversal)

    assert repo.get_match(conn, first_match["id"]) == before_upstream
    assert repo.get_match(conn, final["id"]) == before_final
    assert handler.get_completion_state(conn, tournament_id)["state"] == "COMPLETED"


def test_first_round_score_revision_preserves_playing_downstream_when_winner_is_unchanged(conn):
    """只改比分、不换胜者时，已开打下游必须保持参赛者、状态和球台。"""
    tournament_id, first_two = _two_finished_first_round_matches(conn)
    first_match = first_two[0]
    downstream = repo.list_matches_by_prev(conn, first_match["id"])[0]
    table = next(table for table in repo.list_tables(conn, tournament_id) if table["status"] == "FREE")
    scheduling_service.assign_table(conn, downstream["id"], table["id"])
    before_downstream = repo.get_match(conn, downstream["id"])

    scores_service.revise_score(conn, first_match["id"], 2, 1)

    after_downstream = repo.get_match(conn, downstream["id"])
    assert after_downstream["status"] == MatchStatus.PLAYING.value
    assert after_downstream["table_id"] == before_downstream["table_id"]
    assert (after_downstream["entry_a_id"], after_downstream["entry_b_id"]) == (
        before_downstream["entry_a_id"],
        before_downstream["entry_b_id"],
    )


def test_knockout_score_request_replay_does_not_repeat_winner_propagation(conn):
    """淘汰赛已产生冠军后重放首轮 request_id，不得新增业务副作用。"""
    tournament_id, handler = _create_single_elimination_tournament(conn, players=4)
    handler.generate_matches(conn, tournament_id)
    first_match = next(
        match
        for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value and match["round"] == 1
    )
    request_id = "d6b-0001-knockout-record-replay"
    table = next(table for table in repo.list_tables(conn, tournament_id) if table["status"] == "FREE")
    scheduling_service.assign_table(conn, first_match["id"], table["id"])
    first = scores_service.record_score(conn, first_match["id"], 2, 0, request_id=request_id)
    downstream = repo.list_matches_by_prev(conn, first_match["id"])[0]

    _finish_scheduled_matches(conn, tournament_id)
    before_replay_match_count = len(repo.list_matches(conn, tournament_id))
    before_replay_downstream = repo.get_match(conn, downstream["id"])
    before_replay_audit_count = conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE request_id = ?", (request_id,)
    ).fetchone()[0]
    champion_before = knockout_service.get_knockout(conn, tournament_id)["champion"]

    replay = scores_service.record_score(conn, first_match["id"], 2, 0, request_id=request_id)

    assert replay["id"] == first["id"]
    assert len(repo.list_matches(conn, tournament_id)) == before_replay_match_count
    assert repo.get_match(conn, downstream["id"]) == before_replay_downstream
    assert conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == before_replay_audit_count == 1
    assert len(
        [row for row in repo.list_tournament_score_requests(conn, tournament_id) if row["request_id"] == request_id]
    ) == 1
    assert knockout_service.get_knockout(conn, tournament_id)["champion"] == champion_before
    assert handler.get_completion_state(conn, tournament_id)["state"] == "COMPLETED"


def test_knockout_revision_request_replay_preserves_downstream(conn):
    """胜者不变的改分重放不能重置已就绪的下游比赛。"""
    tournament_id, first_two = _two_finished_first_round_matches(conn)
    first_match = first_two[0]
    downstream = repo.list_matches_by_prev(conn, first_match["id"])[0]
    request_id = "d6b-0002-knockout-revise-replay"

    first = scores_service.revise_score(
        conn,
        first_match["id"],
        2,
        1,
        request_id=request_id,
        operator_name="主裁",
        change_reason="补录局分",
    )
    before_replay_downstream = repo.get_match(conn, downstream["id"])
    replay = scores_service.revise_score(
        conn,
        first_match["id"],
        2,
        1,
        request_id=request_id,
        operator_name="主裁",
        change_reason="补录局分",
    )

    assert replay["id"] == first["id"]
    assert repo.get_match(conn, downstream["id"]) == before_replay_downstream
    assert len(
        [row for row in repo.list_tournament_score_requests(conn, tournament_id) if row["request_id"] == request_id]
    ) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM score_audits WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == 1


def test_knockout_forfeit_request_replay_does_not_duplicate_winner_propagation(conn):
    """异常赛果重放不能重复传播 WALKOVER/FORFEIT 的胜者。"""
    tournament_id, handler = _create_single_elimination_tournament(conn, players=4)
    handler.generate_matches(conn, tournament_id)
    first_match = next(
        match
        for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value and match["round"] == 1
    )
    request_id = "d6b-0003-knockout-forfeit-replay"

    first = scores_service.record_score(
        conn,
        first_match["id"],
        None,
        None,
        result_type="FORFEIT",
        forfeit_entry_id=first_match["entry_a_id"],
        request_id=request_id,
    )
    downstream = repo.list_matches_by_prev(conn, first_match["id"])[0]
    before_replay_downstream = repo.get_match(conn, downstream["id"])
    replay = scores_service.record_score(
        conn,
        first_match["id"],
        None,
        None,
        result_type="FORFEIT",
        forfeit_entry_id=first_match["entry_a_id"],
        request_id=request_id,
    )

    assert replay["id"] == first["id"]
    assert replay["result_type"] == "FORFEIT"
    assert repo.get_match(conn, downstream["id"]) == before_replay_downstream
    assert len(
        [row for row in repo.list_tournament_score_requests(conn, tournament_id) if row["request_id"] == request_id]
    ) == 1
    assert handler.get_completion_state(conn, tournament_id)["state"] == "KNOCKOUT_IN_PROGRESS"
