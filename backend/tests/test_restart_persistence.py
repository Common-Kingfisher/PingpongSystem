"""D6A 重启持久化测试。

测试通过显式关闭连接、再次执行 ``init_db``、重新连接，证明关键业务状态不依赖
进程内内存；排名与晋级结果则由数据库中的比赛事实重新推导。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app import db as db_module
from app import repository as repo
from app.models import MatchStatus, SystemRole, TableStatus
from app.services import rankings as rankings_service
from app.services import scores as scores_service


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def test_restart_reloads_critical_state_and_rebuilds_rankings(tmp_path, monkeypatch):
    """重启后用户、赛事、报名、比赛、比分、球台、审计和排名均可恢复。"""
    database_path = tmp_path / "restart.db"
    monkeypatch.setenv("PINGPONG_DB_PATH", str(database_path))
    monkeypatch.delenv("DEMO_DB_PATH", raising=False)

    db_module.init_db()
    connection = _connect(database_path)
    try:
        owner = repo.create_user(
            connection,
            "restart-owner",
            "重启测试管理员",
            "restart-owner-password-hash",
            SystemRole.EVENT_ADMIN.value,
        )
        connection.commit()
        session = repo.create_user_session(
            connection,
            owner["id"],
            "restart-session-token-hash",
            "2026-12-31 23:59:59",
        )
        tournament = repo.create_tournament(
            connection,
            "D6A 重启持久化赛事",
            "2026-09-23",
            2,
            1,
            1,
            owner_user_id=owner["id"],
            registration_enabled=True,
        )
        tournament_id = tournament["id"]
        registration = repo.create_registration(
            connection,
            tournament_id,
            name="重启报名者",
            affiliation="D6A 学院",
            contact="13800000000",
            rating_points=1688,
        )
        connection.commit()

        first_player = repo.add_player(
            connection, tournament_id, "甲", "A 学院", 1688
        )
        second_player = repo.add_player(
            connection, tournament_id, "乙", "B 学院", 1611
        )
        first_entry = repo.create_entry(
            connection,
            tournament_id,
            "SINGLES",
            first_player["name"],
            first_player["rating_points"],
            [first_player["id"]],
        )
        second_entry = repo.create_entry(
            connection,
            tournament_id,
            "SINGLES",
            second_player["name"],
            second_player["rating_points"],
            [second_player["id"]],
        )
        group = repo.create_group(connection, tournament_id, "A组", 1)
        repo.set_player_group(connection, first_player["id"], group["id"])
        repo.set_player_group(connection, second_player["id"], group["id"])
        repo.set_entry_group(connection, first_entry["id"], group["id"])
        repo.set_entry_group(connection, second_entry["id"], group["id"])
        table = repo.create_tables_for_tournament(connection, tournament_id, 1)[0]
        connection.commit()

        finished_match = repo.create_match(
            connection,
            tournament_id,
            "GROUP",
            group["id"],
            1,
            1,
            first_player["id"],
            second_player["id"],
            entry_a_id=first_entry["id"],
            entry_b_id=second_entry["id"],
            bracket="GROUP",
        )
        connection.commit()
        scores_service.record_score(
            connection,
            finished_match["id"],
            2,
            0,
            games=[(11, 5), (11, 6)],
            request_id="restart-finished-score",
            operator_name="重启主裁",
            change_reason="重启前完赛",
        )

        playing_match = repo.create_match(
            connection,
            tournament_id,
            "GROUP",
            group["id"],
            1,
            2,
            first_player["id"],
            second_player["id"],
            entry_a_id=first_entry["id"],
            entry_b_id=second_entry["id"],
            bracket="GROUP",
        )
        connection.commit()
        repo.mark_match_playing(connection, playing_match["id"], table["id"])
        repo.update_table_status(
            connection, table["id"], TableStatus.OCCUPIED.value
        )
        connection.execute(
            "UPDATE matches SET player_a_score = 1, player_b_score = 0 WHERE id = ?",
            (playing_match["id"],),
        )
        connection.commit()

        before_rankings = rankings_service.get_rankings(connection, tournament_id)
        assert before_rankings[0]["finished_matches"] == 1
        qualified = next(
            entry
            for entry in before_rankings[0]["entries"]
            if entry["qualified"] and entry["entry_status"] == "ACTIVE"
        )
        repo.create_qualification_decision(
            connection,
            tournament_id,
            group["id"],
            json.dumps([qualified["entry_id"]], ensure_ascii=False),
            rankings_service.qualification_snapshot(before_rankings[0]),
            "重启前晋级裁定",
            "重启裁判长",
        )
        connection.commit()

        expected_ranking = [
            {
                "group_id": item["group_id"],
                "finished_matches": item["finished_matches"],
                "qualified_entry_ids": sorted(
                    entry["entry_id"]
                    for entry in item["entries"]
                    if entry["qualified"]
                ),
                "entry_ranks": sorted(
                    (entry["entry_id"], entry["rank"])
                    for entry in item["entries"]
                ),
            }
            for item in before_rankings
        ]
    finally:
        connection.close()

    # 模拟应用重启：服务端重新初始化 schema/migration，再建立全新连接。
    db_module.init_db()
    connection = _connect(database_path)
    try:
        restored_owner = repo.get_user_by_id(connection, owner["id"])
        restored_tournament = repo.get_tournament(connection, tournament_id)
        restored_player = repo.get_player(connection, first_player["id"])
        restored_entry = repo.get_entry(connection, first_entry["id"])
        restored_registration = repo.get_registration(
            connection, registration["id"]
        )
        restored_finished = repo.get_match(connection, finished_match["id"])
        restored_playing = repo.get_match(connection, playing_match["id"])
        restored_table = repo.get_table(connection, table["id"])
        restored_session = repo.get_user_session_by_token_hash(
            connection, "restart-session-token-hash"
        )
        audits = repo.list_score_audits(connection, finished_match["id"])
        games = connection.execute(
            "SELECT game_no, side_a_score, side_b_score, winner_entry_id "
            "FROM match_games WHERE match_id = ? ORDER BY game_no",
            (finished_match["id"],),
        ).fetchall()
        decisions = repo.list_qualification_decisions(
            connection, group["id"]
        )

        assert restored_owner is not None
        assert restored_owner["username"] == "restart-owner"
        assert restored_tournament is not None
        assert restored_tournament["name"] == "D6A 重启持久化赛事"
        assert restored_player is not None
        assert restored_player["name"] == "甲"
        assert restored_entry is not None
        assert restored_entry["display_name"] == "甲"
        assert restored_registration is not None
        assert restored_registration["name"] == "重启报名者"
        assert restored_session is not None
        assert restored_session["user_id"] == owner["id"]

        assert restored_finished is not None
        assert restored_finished["status"] == MatchStatus.FINISHED.value
        assert restored_finished["player_a_score"] == 2
        assert restored_finished["player_b_score"] == 0
        assert restored_playing is not None
        assert restored_playing["status"] == MatchStatus.PLAYING.value
        assert restored_playing["player_a_score"] == 1
        assert restored_playing["player_b_score"] == 0
        assert restored_table is not None
        assert restored_table["status"] == TableStatus.OCCUPIED.value
        assert len(games) == 2
        assert [(row["game_no"], row["side_a_score"], row["side_b_score"]) for row in games] == [
            (1, 11, 5),
            (2, 11, 6),
        ]
        assert any(audit["action"] == "RECORD" for audit in audits)
        assert len(decisions) == 1

        after_rankings = rankings_service.get_rankings(connection, tournament_id)
        assert [
            {
                "group_id": item["group_id"],
                "finished_matches": item["finished_matches"],
                "qualified_entry_ids": sorted(
                    entry["entry_id"]
                    for entry in item["entries"]
                    if entry["qualified"]
                ),
                "entry_ranks": sorted(
                    (entry["entry_id"], entry["rank"])
                    for entry in item["entries"]
                ),
            }
            for item in after_rankings
        ] == expected_ranking
    finally:
        connection.close()
