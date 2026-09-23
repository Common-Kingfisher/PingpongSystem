"""D7B 发布候选：验证 16 人、4 组、每组前 2 的个人赛完整闭环。"""

import random

from app import repository as repo
from app.models import MatchBracket, MatchStage, MatchStatus
from app.services import formats
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


DRAW_SEED = 20260923


def _finish_scheduled_matches(conn, tournament_id: int) -> None:
    """用确定性胜者完成所有当前可调度比赛，直到赛事没有未完成比赛。"""
    for _ in range(100):
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


def test_16_player_four_group_top2_group_knockout_release_acceptance(conn):
    tournament = repo.create_tournament(
        conn,
        "D7B 16人小组淘汰发布验收",
        "2026-09-23",
        4,
        4,
        2,
        format_code=formats.GROUP_KNOCKOUT,
        rule_config={},
        rule_version=1,
    )
    repo.create_tables_for_tournament(conn, tournament["id"], 4)
    for index in range(16):
        repo.add_player(conn, tournament["id"], f"D7B选手{index + 1}", f"单位{index % 4}")
    groups_service.auto_group_tournament(conn, tournament["id"], rng=random.Random(DRAW_SEED))
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    generation = handler.generate_matches(conn, tournament["id"])
    assert generation.matches_generated == 24
    assert len(generation.per_group) == 4
    assert set(generation.per_group.values()) == {6}

    _finish_scheduled_matches(conn, tournament["id"])

    rankings = handler.calculate_ranking(conn, tournament["id"])
    qualified_ids = [
        entry["entry_id"]
        for group in rankings
        for entry in group["entries"]
        if entry["qualified"]
    ]
    assert len(qualified_ids) == 8
    assert len(set(qualified_ids)) == 8
    assert all(sum(entry["qualified"] for entry in group["entries"]) == 2 for group in rankings)

    handler.advance_participants(conn, tournament["id"])
    knockout_matches = [
        match
        for match in repo.list_matches(conn, tournament["id"], MatchStage.KNOCKOUT.value)
        if match["bracket"] == MatchBracket.MAIN.value
    ]
    assert [
        sum(match["round"] == round_no for match in knockout_matches)
        for round_no in range(1, 4)
    ] == [4, 2, 1]
    first_round_entry_ids = [
        entry_id
        for match in knockout_matches
        if match["round"] == 1
        for entry_id in (match["entry_a_id"], match["entry_b_id"])
    ]
    assert sorted(first_round_entry_ids) == sorted(qualified_ids)

    _finish_scheduled_matches(conn, tournament["id"])

    assert handler.get_completion_state(conn, tournament["id"]) == {
        "state": "COMPLETED",
        "can_advance": False,
        "completed": True,
    }
    assert knockout_service.get_knockout(conn, tournament["id"])["champion"] is not None
