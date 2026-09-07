"""比分修改时裁判备注的三态语义回归测试。"""

from app import repository as repo
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import scores as scores_service


def _finished_match_with_note(conn) -> int:
    tournament = repo.create_tournament(conn, "备注语义测试", "2026-09-07", 1, 1, 2)
    repo.create_tables_for_tournament(conn, tournament["id"], 1)
    for i in range(1, 5):
        repo.add_player(conn, tournament["id"], f"P{i}", None)
    groups_service.auto_group_tournament(conn, tournament["id"])
    matches_service.generate_group_matches(conn, tournament["id"])
    match = repo.list_matches(conn, tournament["id"])[0]
    saved = scores_service.record_score(conn, match["id"], 2, 1, note="原裁判备注")
    assert saved["result_note"] == "原裁判备注"
    return match["id"]


def test_revise_score_omitted_note_preserves_existing_note(conn):
    match_id = _finished_match_with_note(conn)

    updated = scores_service.revise_score(conn, match_id, 2, 0)

    assert updated["result_note"] == "原裁判备注"


def test_revise_score_empty_note_explicitly_clears_existing_note(conn):
    match_id = _finished_match_with_note(conn)

    updated = scores_service.revise_score(conn, match_id, 2, 0, note="")

    assert updated["result_note"] == ""


def test_revise_score_new_note_replaces_existing_note(conn):
    match_id = _finished_match_with_note(conn)

    updated = scores_service.revise_score(conn, match_id, 2, 0, note="新裁判备注")

    assert updated["result_note"] == "新裁判备注"
