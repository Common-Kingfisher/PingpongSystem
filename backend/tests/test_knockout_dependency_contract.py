"""可变出线人数与淘汰/排位签位依赖的回归测试。"""

import pytest

from app import repository as repo
from app.models import MatchStatus
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import scores as scores_service


def _prepare(
    conn,
    *,
    bronze_mode="BRONZE_MATCH",
    placement_mode="COMPLETE",
    players=8,
    group_count=4,
    qualify_per_group=2,
):
    tournament = repo.create_tournament(
        conn,
        "依赖验收赛",
        "2026-09-07",
        4,
        group_count,
        qualify_per_group,
        bronze_mode=bronze_mode,
        placement_mode=placement_mode,
    )
    repo.create_tables_for_tournament(conn, tournament["id"], 4)
    for index in range(players):
        repo.add_player(conn, tournament["id"], f"选手{index + 1:02d}", None)
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])
    for match in repo.list_matches(conn, tournament["id"], stage="GROUP"):
        score_a, score_b = (2, 0) if match["entry_a_id"] < match["entry_b_id"] else (0, 2)
        scores_service.record_score(conn, match["id"], score_a, score_b)
    return tournament["id"]


def _main_round(conn, tournament_id, round_no):
    return sorted(
        (
            match
            for match in repo.list_matches(conn, tournament_id, stage="KNOCKOUT")
            if match["bracket"] == "MAIN" and match["round"] == round_no
        ),
        key=lambda match: match["match_index"],
    )


def _score_a_wins(conn, match):
    scores_service.record_score(conn, match["id"], 2, 0)


def test_different_qualifier_counts_generate_power_of_two_bracket_with_byes(conn):
    tid = _prepare(conn, placement_mode="OFF", players=12)
    groups = repo.list_groups(conn, tid)
    for group, qualify_count in zip(groups, [1, 2, 1, 2]):
        repo.update_group_qualify_count(conn, group["id"], qualify_count)

    tree = knockout_service.generate_knockout(conn, tid)

    assert [len(round_["matches"]) for round_ in tree["rounds"]] == [4, 2, 1]
    first_round = _main_round(conn, tid, 1)
    participants = {
        participant
        for match in first_round
        for participant in (match["entry_a_id"], match["entry_b_id"])
        if participant is not None
    }
    assert len(participants) == 6
    assert sum(match["result_type"] == "WALKOVER" for match in first_round) == 2
    entry_groups = {
        entry["id"]: entry["group_id"] for entry in repo.list_entries(conn, tid)
    }
    real_matches = [
        match for match in first_round
        if match["entry_a_id"] is not None and match["entry_b_id"] is not None
    ]
    assert all(
        entry_groups[match["entry_a_id"]] != entry_groups[match["entry_b_id"]]
        for match in real_matches
    )


def test_qf_revision_updates_main_and_five_to_eight_sources(conn):
    tid = _prepare(conn)
    knockout_service.generate_knockout(conn, tid)
    quarterfinals = _main_round(conn, tid, 1)
    for match in quarterfinals:
        _score_a_wins(conn, match)

    qf = repo.get_match(conn, quarterfinals[0]["id"])
    old_winner, old_loser = qf["entry_a_id"], qf["entry_b_id"]
    scores_service.revise_score(conn, qf["id"], 0, 2)

    children = repo.list_matches_by_prev(conn, qf["id"])
    main_child = next(match for match in children if match["bracket"] == "MAIN")
    placement_child = next(match for match in children if match["bracket"] == "PLACEMENT")
    assert old_loser in (main_child["entry_a_id"], main_child["entry_b_id"])
    assert old_winner in (placement_child["entry_a_id"], placement_child["entry_b_id"])
    assert main_child["status"] == placement_child["status"] == MatchStatus.WAITING.value


def test_semifinal_revision_updates_final_and_bronze_sources(conn):
    tid = _prepare(conn)
    knockout_service.generate_knockout(conn, tid)
    for match in _main_round(conn, tid, 1):
        _score_a_wins(conn, match)
    semifinals = _main_round(conn, tid, 2)
    for match in semifinals:
        _score_a_wins(conn, match)

    semi = repo.get_match(conn, semifinals[0]["id"])
    old_winner, old_loser = semi["entry_a_id"], semi["entry_b_id"]
    scores_service.revise_score(conn, semi["id"], 0, 2)

    children = repo.list_matches_by_prev(conn, semi["id"])
    final = next(match for match in children if match["bracket"] == "MAIN")
    bronze = next(match for match in children if match.get("placement_min") == 3)
    assert old_loser in (final["entry_a_id"], final["entry_b_id"])
    assert old_winner in (bronze["entry_a_id"], bronze["entry_b_id"])
    assert final["status"] == bronze["status"] == MatchStatus.WAITING.value


def test_revision_is_blocked_after_dependent_placement_match_finishes(conn):
    tid = _prepare(conn)
    knockout_service.generate_knockout(conn, tid)
    quarterfinals = _main_round(conn, tid, 1)
    for match in quarterfinals:
        _score_a_wins(conn, match)
    qf = quarterfinals[0]
    placement = next(
        match
        for match in repo.list_matches_by_prev(conn, qf["id"])
        if match["bracket"] == "PLACEMENT"
    )
    _score_a_wins(conn, placement)

    with pytest.raises(scores_service.ScoreError, match="影响后续比赛"):
        scores_service.revise_score(conn, qf["id"], 0, 2)


def test_group_result_is_locked_after_knockout_generation(conn):
    tid = _prepare(conn)
    group_match = repo.list_matches(conn, tid, stage="GROUP")[0]
    knockout_service.generate_knockout(conn, tid)

    with pytest.raises(scores_service.ScoreError, match="淘汰赛已生成"):
        scores_service.revise_score(conn, group_match["id"], 0, 2)


def test_complete_sixteen_entry_draw_produces_every_rank_once(conn):
    tid = _prepare(
        conn,
        players=32,
        group_count=8,
        qualify_per_group=2,
        bronze_mode="BRONZE_MATCH",
    )
    tree = knockout_service.generate_knockout(conn, tid)
    assert [len(round_["matches"]) for round_ in tree["rounds"]] == [8, 4, 2, 1]

    for _ in range(20):
        matches = repo.list_matches(conn, tid, stage="KNOCKOUT")
        playable = [
            match for match in matches
            if match["status"] == MatchStatus.WAITING.value
            and match["entry_a_id"] is not None
            and match["entry_b_id"] is not None
        ]
        if not playable:
            break
        for match in playable:
            _score_a_wins(conn, match)

    tree = knockout_service.get_knockout(conn, tid)
    assert tree["tournament"]["stage"] == "FINISHED"
    assert [row["rank"] for row in tree["placements"]] == list(range(1, 17))
    ranked_entries = [row["entry"]["id"] for row in tree["placements"]]
    assert len(ranked_entries) == len(set(ranked_entries)) == 16
    ranges = {tuple(item["range"]) for item in tree["placement_matches"]}
    assert ranges == {(3, 4), (5, 8), (7, 8), (9, 16), (11, 12), (13, 16), (15, 16)}


def test_complete_placement_does_not_invent_ranks_for_bye_draw(conn):
    tid = _prepare(conn, players=12, group_count=4, qualify_per_group=2)
    for group, qualify_count in zip(repo.list_groups(conn, tid), [1, 2, 1, 2]):
        repo.update_group_qualify_count(conn, group["id"], qualify_count)
    knockout_service.generate_knockout(conn, tid)
    first_round = _main_round(conn, tid, 1)
    for match in first_round:
        if match["status"] != MatchStatus.FINISHED.value:
            _score_a_wins(conn, match)

    placement_ranges = {
        (match["placement_min"], match["placement_max"])
        for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["bracket"] == "PLACEMENT"
    }
    assert (5, 8) not in placement_ranges
