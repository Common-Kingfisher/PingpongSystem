"""GROUP_KNOCKOUT 通过统一赛制入口的兼容性回归。"""

import pytest

from app import repository as repo
from app.services import formats
from app.services import entries as entries_service
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import qualification_decisions as decision_service
from app.services import rankings as rankings_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


def _grouped_tournament(conn, *, players: int = 8, groups: int = 4, qualify: int = 2) -> int:
    tournament = repo.create_tournament(conn, "赛制处理器", "2025-06-01", 4, groups, qualify)
    repo.create_tables_for_tournament(conn, tournament["id"], 4)
    for number in range(players):
        repo.add_player(conn, tournament["id"], f"P{number + 1}", None)
    groups_service.auto_group_tournament(conn, tournament["id"])
    return tournament["id"]


def _finish_playable_matches(conn, tournament_id: int) -> None:
    for _ in range(100):
        scheduling_service.schedule_next(conn, tournament_id)
        playing = repo.list_playing_matches(conn, tournament_id)
        if not playing:
            return
        for match in playing:
            score_a, score_b = (2, 0) if match["player_a_id"] < match["player_b_id"] else (0, 2)
            scores_service.record_score(conn, match["id"], score_a, score_b)
    raise AssertionError("比赛未在预期轮次内完成")


def _fully_tied_group(conn) -> tuple[int, int, list[int]]:
    """构造晋级线三人循环并列，不依赖其他测试文件的 helper。"""
    tournament = repo.create_tournament(conn, "晋级并列", "2025-06-01", 2, 1, 1)
    repo.create_tables_for_tournament(conn, tournament["id"], 2)
    for name in ("甲", "乙", "丙"):
        repo.add_player(conn, tournament["id"], name, None)
    groups_service.auto_group_tournament(conn, tournament["id"])
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)
    handler.generate_matches(conn, tournament["id"])

    entries = sorted(repo.list_entries(conn, tournament["id"]), key=lambda entry: entry["id"])
    first, second, third = [entry["id"] for entry in entries]
    winner_by_pair = {
        frozenset((first, second)): first,
        frozenset((second, third)): second,
        frozenset((first, third)): third,
    }
    for match in repo.list_matches(conn, tournament["id"]):
        winner = winner_by_pair[frozenset((match["entry_a_id"], match["entry_b_id"]))]
        score = (2, 0) if winner == match["entry_a_id"] else (0, 2)
        scores_service.record_score(conn, match["id"], *score)
        games = [(11, 5), (11, 5)] if winner == match["entry_a_id"] else [(5, 11), (5, 11)]
        scores_service.revise_score(conn, match["id"], None, None, games=games)
    group_id = repo.list_groups(conn, tournament["id"])[0]["id"]
    return tournament["id"], group_id, [entry["id"] for entry in entries]


def test_resolver_returns_group_knockout_handler():
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    assert isinstance(handler, formats.GroupKnockoutHandler)
    assert handler.format_code == formats.GROUP_KNOCKOUT


@pytest.mark.parametrize("players", [2, 3, 5, 8])
def test_round_robin_handler_generates_exactly_one_match_per_pair(conn, players):
    tournament = repo.create_tournament(conn, "循环赛", "2025-06-01", 4, 1, 1)
    for number in range(players):
        repo.add_player(conn, tournament["id"], f"RR{number + 1}", None)
    entries_service.confirm_roster(conn, tournament["id"])
    handler = formats.resolve_format_handler(formats.ROUND_ROBIN)

    result = handler.generate_matches(conn, tournament["id"])

    matches = repo.list_matches(conn, tournament["id"])
    pairs = {frozenset((match["entry_a_id"], match["entry_b_id"])) for match in matches}
    assert result == formats.MatchGenerationResult(players * (players - 1) // 2)
    assert len(matches) == len(pairs) == players * (players - 1) // 2
    with pytest.raises(formats.FormatHandlerError, match="循环赛已生成"):
        handler.generate_matches(conn, tournament["id"])


def test_single_elimination_handler_builds_byes_and_winner_chain(conn):
    tournament = repo.create_tournament(conn, "单淘汰", "2025-06-01", 4, 1, 1)
    for number in range(12):
        repo.add_player(conn, tournament["id"], f"SE{number + 1}", None)
    entries_service.confirm_roster(conn, tournament["id"])
    handler = formats.resolve_format_handler(formats.SINGLE_ELIMINATION)

    result = handler.generate_matches(conn, tournament["id"])

    main = repo.list_matches(conn, tournament["id"], stage="KNOCKOUT")
    first_round = [match for match in main if match["round"] == 1]
    assert result == formats.MatchGenerationResult(15)
    assert [len([m for m in main if m["round"] == round_no]) for round_no in range(1, 5)] == [8, 4, 2, 1]
    assert len([m for m in first_round if m["result_type"] == "WALKOVER"]) == 4
    assert all(match["prev_match_a_id"] or match["prev_match_b_id"] for match in main if match["round"] > 1)
    with pytest.raises(formats.FormatHandlerError, match="淘汰赛已生成"):
        handler.generate_matches(conn, tournament["id"])


def test_unknown_format_is_explicitly_rejected():
    with pytest.raises(formats.UnsupportedFormatError, match="不支持的个人赛赛制：UNKNOWN"):
        formats.resolve_format_handler("UNKNOWN")


def test_personal_format_handler_rejects_team_tournament(conn):
    tournament = repo.create_tournament(
        conn, "团体赛", "2025-06-01", 4, 2, 1, event_type="TEAM"
    )
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    with pytest.raises(formats.FormatHandlerError, match="团体赛不使用个人赛赛制处理器"):
        handler.validate_config(conn, tournament["id"])


def test_group_knockout_handler_wraps_existing_main_flow(conn):
    tournament_id = _grouped_tournament(conn)
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    assert handler.validate_config(conn, tournament_id)["id"] == tournament_id
    result = handler.generate_matches(conn, tournament_id)
    assert result == formats.MatchGenerationResult(
        matches_generated=4,
        per_group={"A组": 1, "B组": 1, "C组": 1, "D组": 1},
    )
    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "GROUP_STAGE_IN_PROGRESS", "can_advance": False, "completed": False
    }

    _finish_playable_matches(conn, tournament_id)
    rankings = handler.calculate_ranking(conn, tournament_id)
    assert all(group["finished_matches"] == group["total_matches"] for group in rankings)
    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "KNOCKOUT_READY", "can_advance": True, "completed": False
    }

    tree = handler.advance_participants(conn, tournament_id)
    assert [len(round_["matches"]) for round_ in tree["rounds"]] == [4, 2, 1]
    assert repo.get_tournament(conn, tournament_id)["stage"] == "KNOCKOUT"
    assert handler.handle_bye(conn, tournament_id) == {
        "handled_by": "existing_knockout_service", "walkover_match_ids": []
    }
    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "KNOCKOUT_IN_PROGRESS", "can_advance": False, "completed": False
    }

    _finish_playable_matches(conn, tournament_id)
    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "COMPLETED", "can_advance": False, "completed": True
    }


def test_group_knockout_handler_reports_existing_bye_processing(conn):
    # 3 个出线者不是 2 的幂：由既有 knockout 服务生成并推进 WALKOVER。
    tournament_id = _grouped_tournament(conn, players=6, groups=3, qualify=1)
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)
    handler.generate_matches(conn, tournament_id)
    _finish_playable_matches(conn, tournament_id)

    handler.advance_participants(conn, tournament_id)

    bye_result = handler.handle_bye(conn, tournament_id)
    assert bye_result["handled_by"] == "existing_knockout_service"
    assert bye_result["walkover_match_ids"]


def test_unresolved_qualification_blocks_completion_and_advancement(conn):
    tournament_id, _, _ = _fully_tied_group(conn)
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    ranking = rankings_service.get_rankings(conn, tournament_id)[0]
    assert ranking["finished_matches"] == ranking["total_matches"]
    assert ranking["ambiguous_qualification"] is True
    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "QUALIFICATION_UNRESOLVED", "can_advance": False, "completed": False
    }
    with pytest.raises(knockout_service.KnockoutError, match="并列"):
        handler.advance_participants(conn, tournament_id)


def test_manual_decision_does_not_make_unbuildable_bracket_ready(conn):
    tournament_id, group_id, entry_ids = _fully_tied_group(conn)
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    decision_service.create_decision(
        conn, tournament_id, group_id, [entry_ids[0]], "裁判抽签决定", "主裁判"
    )

    ranking = rankings_service.get_rankings(conn, tournament_id)[0]
    assert ranking["manually_resolved"] is True
    assert ranking["ambiguous_qualification"] is False
    assert handler.get_completion_state(conn, tournament_id) == {
        "state": "KNOCKOUT_NOT_READY", "can_advance": False, "completed": False
    }
    with pytest.raises(knockout_service.KnockoutError, match="至少需要 2 名晋级者"):
        handler.advance_participants(conn, tournament_id)
