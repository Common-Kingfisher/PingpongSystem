"""GROUP_KNOCKOUT 通过统一赛制入口的兼容性回归。"""

import pytest

from app import repository as repo
from app.services import formats
from app.services import groups as groups_service
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


def test_resolver_returns_group_knockout_handler():
    handler = formats.resolve_format_handler(formats.GROUP_KNOCKOUT)

    assert isinstance(handler, formats.GroupKnockoutHandler)
    assert handler.format_code == formats.GROUP_KNOCKOUT


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
