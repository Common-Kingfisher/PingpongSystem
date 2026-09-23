"""D6A 数据库级备份、停服恢复与 migration 升级测试。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app import repository as repo
from app.main import app
from app.models import MatchStatus, SystemRole, TableStatus
from app.services import database_backup
from app.services import rankings as rankings_service
from app.services import scores as scores_service


BUSINESS_TABLES = tuple(
    sorted(set(database_backup.REQUIRED_TABLES) | {"system_state"})
)


@contextmanager
def _database(path: Path):
    """打开带外键校验的 SQLite 连接，并保证测试结束后关闭。"""
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _initialize(path: Path) -> None:
    database_backup._initialize_database_path(path)
    assert path.is_file()


def _snapshot(
    path: Path, tables: tuple[str, ...] = BUSINESS_TABLES
) -> dict[str, tuple[tuple[object, ...], ...]]:
    """按 rowid 输出稳定快照，用于证明恢复前后的业务内容完全一致。"""
    result: dict[str, tuple[tuple[object, ...], ...]] = {}
    with _database(path) as connection:
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table in tables:
            assert table in existing, f"缺少业务表: {table}"
            rows = connection.execute(
                f'SELECT * FROM "{table}" ORDER BY rowid'
            ).fetchall()
            result[table] = tuple(tuple(row) for row in rows)
    return result


def _seed_registration_state(path: Path) -> dict[str, int]:
    with _database(path) as connection:
        owner = repo.create_user(
            connection,
            "d6a-owner",
            "D6A Owner",
            "owner-password-hash",
            SystemRole.EVENT_ADMIN.value,
        )
        admin = repo.create_user(
            connection,
            "d6a-admin",
            "D6A Admin",
            "admin-password-hash",
            SystemRole.EVENT_ADMIN.value,
        )
        tournament = repo.create_tournament(
            connection,
            "D6A 报名恢复赛事",
            "2026-09-23",
            2,
            1,
            1,
            owner_user_id=owner["id"],
            registration_enabled=True,
        )
        repo.upsert_tournament_admin(
            connection,
            tournament["id"],
            admin["id"],
            "ADMIN",
            created_by_user_id=owner["id"],
        )
        registration = repo.create_registration(
            connection,
            tournament["id"],
            name="待确认报名者",
            affiliation="D6A 测试学院",
            contact="13800000000",
            rating_points=1688,
        )
        repo.upsert_organization(
            connection,
            tournament["id"],
            name="D6A 主办方",
            contact_name="组织联系人",
            contact="010-12345678",
            note="报名阶段恢复",
        )
        repo.upsert_venue(
            connection,
            tournament["id"],
            name="D6A 体育馆",
            address="测试路 1 号",
            contact_name="场馆联系人",
            contact="13900000000",
            note="一号馆",
        )
        session = repo.create_user_session(
            connection,
            owner["id"],
            "d6a-owner-session-token-hash",
            "2026-12-31 23:59:59",
        )
        connection.commit()
        return {
            "tournament_id": tournament["id"],
            "registration_id": registration["id"],
            "session_id": session["id"],
        }


def _seed_live_state(path: Path) -> dict[str, int]:
    with _database(path) as connection:
        tournament = repo.create_tournament(
            connection, "D6A 进行中恢复赛事", "2026-09-23", 2, 1, 1
        )
        tournament_id = tournament["id"]
        repo.update_tournament_stage(connection, tournament_id, "GROUP_STAGE")
        table = repo.create_tables_for_tournament(connection, tournament_id, 1)[0]
        first_player = repo.add_player(connection, tournament_id, "甲", "A 学院")
        second_player = repo.add_player(connection, tournament_id, "乙", "B 学院")
        first_entry = repo.create_entry(
            connection,
            tournament_id,
            "SINGLES",
            "甲",
            1000,
            [first_player["id"]],
        )
        second_entry = repo.create_entry(
            connection,
            tournament_id,
            "SINGLES",
            "乙",
            1000,
            [second_player["id"]],
        )
        group = repo.create_group(connection, tournament_id, "A组", 1)
        for entry, player in (
            (first_entry, first_player),
            (second_entry, second_player),
        ):
            repo.set_entry_group(connection, entry["id"], group["id"])
            repo.set_player_group(connection, player["id"], group["id"])
        match = repo.create_match(
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
        repo.mark_match_playing(connection, match["id"], table["id"])
        repo.update_table_status(connection, table["id"], TableStatus.OCCUPIED.value)
        connection.execute(
            "UPDATE matches SET player_a_score = 1, player_b_score = 0 WHERE id = ?",
            (match["id"],),
        )
        connection.execute(
            "INSERT INTO match_games "
            "(match_id, game_no, side_a_score, side_b_score, winner_entry_id) "
            "VALUES (?, 1, 11, 7, ?)",
            (match["id"], first_entry["id"]),
        )
        repo.claim_score_request(
            connection,
            "d6a-live-request",
            match["id"],
            "RECORD",
            "d6a-live-fingerprint",
        )
        repo.create_score_audit(
            connection,
            match["id"],
            "RECORD",
            json.dumps({"status": "PLAYING"}, ensure_ascii=False),
            json.dumps({"status": "PLAYING", "games": [[11, 7]]}, ensure_ascii=False),
            "D6A 主裁",
            "进行中快照",
            "d6a-live-request",
        )
        connection.commit()
        return {
            "tournament_id": tournament_id,
            "match_id": match["id"],
            "table_id": table["id"],
        }


def _seed_finished_state(path: Path) -> dict[str, int]:
    with _database(path) as connection:
        tournament = repo.create_tournament(
            connection, "D6A 完赛恢复赛事", "2026-09-23", 2, 1, 1
        )
        tournament_id = tournament["id"]
        repo.update_tournament_stage(connection, tournament_id, "GROUP_STAGE")
        group = repo.create_group(connection, tournament_id, "A组", 1)
        players = [
            repo.add_player(connection, tournament_id, name, f"{name}学院")
            for name in ("甲", "乙", "丙")
        ]
        entries = [
            repo.create_entry(
                connection,
                tournament_id,
                "SINGLES",
                player["name"],
                player["rating_points"],
                [player["id"]],
            )
            for player in players
        ]
        for player, entry in zip(players, entries):
            repo.set_player_group(connection, player["id"], group["id"])
            repo.set_entry_group(connection, entry["id"], group["id"])

        pairs = ((0, 1), (0, 2), (1, 2))
        winners = (0, 0, 1)
        group_matches = []
        for index, ((a_index, b_index), winner_index) in enumerate(
            zip(pairs, winners), start=1
        ):
            group_matches.append(
                repo.create_match(
                    connection,
                    tournament_id,
                    "GROUP",
                    group["id"],
                    1,
                    index,
                    players[a_index]["id"],
                    players[b_index]["id"],
                    entry_a_id=entries[a_index]["id"],
                    entry_b_id=entries[b_index]["id"],
                    bracket="GROUP",
                )
            )
        connection.commit()

        for match, winner_index in zip(group_matches, winners):
            if match["entry_a_id"] == entries[winner_index]["id"]:
                score, games = (2, 0), [(11, 5), (11, 6)]
            else:
                score, games = (0, 2), [(5, 11), (6, 11)]
            scores_service.record_score(
                connection,
                match["id"],
                score[0],
                score[1],
                games=games,
                request_id=f"d6a-finished-{match['id']}",
                operator_name="D6A 主裁",
                change_reason="完赛快照",
            )

        rankings = rankings_service.get_rankings(connection, tournament_id)
        assert rankings[0]["finished_matches"] == 3
        qualified = next(
            entry for entry in rankings[0]["entries"] if entry["qualified"]
        )
        repo.create_qualification_decision(
            connection,
            tournament_id,
            group["id"],
            json.dumps([qualified["entry_id"]], ensure_ascii=False),
            rankings_service.qualification_snapshot(rankings[0]),
            "D6A 完赛裁定快照",
            "D6A 裁判长",
        )
        connection.commit()

        knockout = repo.create_match(
            connection,
            tournament_id,
            "KNOCKOUT",
            None,
            1,
            1,
            players[0]["id"],
            players[1]["id"],
            entry_a_id=entries[0]["id"],
            entry_b_id=entries[1]["id"],
            bracket="MAIN",
        )
        connection.commit()
        scores_service.record_score(
            connection,
            knockout["id"],
            2,
            0,
            games=[(11, 8), (11, 9)],
            request_id="d6a-knockout-final",
            operator_name="D6A 主裁",
            change_reason="淘汰赛完赛",
        )
        connection.commit()
        return {
            "tournament_id": tournament_id,
            "group_id": group["id"],
            "qualified_entry_id": qualified["entry_id"],
            "knockout_match_id": knockout["id"],
        }


def _backup_mutate_restore(
    database_path: Path, backup_dir: Path
) -> tuple[
    dict[str, tuple[tuple[object, ...], ...]],
    database_backup.BackupResult,
    database_backup.RestoreResult,
]:
    before = _snapshot(database_path)
    backup = database_backup.backup_database(database_path, backup_dir)
    with _database(database_path) as connection:
        connection.execute("DELETE FROM tournaments")
        connection.execute("DELETE FROM users")
    assert _snapshot(database_path) != before, "测试必须先制造可检测的数据变化"
    restored = database_backup.restore_database(
        backup.backup_path,
        database_path,
        backup_dir,
        service_stopped=True,
    )
    assert _snapshot(database_path) == before
    return before, backup, restored


def test_empty_database_backup_restore_and_app_startup(tmp_path, monkeypatch):
    source = tmp_path / "empty.db"
    target = tmp_path / "restored.db"
    backup_dir = tmp_path / "backups"
    _initialize(source)
    before = _snapshot(source)

    backup = database_backup.backup_database(source, backup_dir)
    restored = database_backup.restore_database(
        backup.backup_path, target, backup_dir, service_stopped=True
    )

    assert backup.integrity_check == ("ok",)
    assert backup.foreign_key_violations == 0
    assert backup.schema_version == database_backup.SCHEMA_VERSION
    assert restored.integrity_check == ("ok",)
    assert restored.foreign_key_violations == 0
    assert _snapshot(target) == before

    monkeypatch.setenv("PINGPONG_DB_PATH", str(target))
    monkeypatch.delenv("DEMO_DB_PATH", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_registration_state_round_trip(tmp_path):
    database_path = tmp_path / "registration.db"
    backup_dir = tmp_path / "backups"
    _initialize(database_path)
    ids = _seed_registration_state(database_path)

    _, backup, restored = _backup_mutate_restore(database_path, backup_dir)

    assert restored.pre_restore_backup_path is not None
    assert restored.pre_restore_backup_path.is_file()
    with _database(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM users WHERE id IN (?, ?)",
            (1, 2),
        ).fetchone()[0] == 2
        assert repo.get_registration(connection, ids["registration_id"]) is not None
        assert repo.get_organization(connection, ids["tournament_id"]) is not None
        assert repo.get_venue(connection, ids["tournament_id"]) is not None
        assert connection.execute(
            "SELECT COUNT(*) FROM user_sessions WHERE id = ?", (ids["session_id"],)
        ).fetchone()[0] == 1
    assert backup.schema_version == database_backup.SCHEMA_VERSION



def test_live_match_state_round_trip(tmp_path):
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    _initialize(database_path)
    ids = _seed_live_state(database_path)

    _, _, restored = _backup_mutate_restore(database_path, backup_dir)

    assert restored.schema_version == database_backup.SCHEMA_VERSION
    with _database(database_path) as connection:
        match = repo.get_match(connection, ids["match_id"])
        table = repo.get_table(connection, ids["table_id"])
        assert match["status"] == MatchStatus.PLAYING.value
        assert (match["player_a_score"], match["player_b_score"]) == (1, 0)
        assert table["status"] == TableStatus.OCCUPIED.value
        assert connection.execute(
            "SELECT COUNT(*) FROM match_games WHERE match_id = ?", (match["id"],)
        ).fetchone()[0] == 1


def test_finished_state_round_trip(tmp_path):
    database_path = tmp_path / "finished.db"
    backup_dir = tmp_path / "backups"
    _initialize(database_path)
    ids = _seed_finished_state(database_path)

    _, _, restored = _backup_mutate_restore(database_path, backup_dir)

    assert restored.schema_version == database_backup.SCHEMA_VERSION
    with _database(database_path) as connection:
        rankings = rankings_service.get_rankings(connection, ids["tournament_id"])
        qualified = [entry for entry in rankings[0]["entries"] if entry["qualified"]]
        assert [entry["entry_id"] for entry in qualified] == [ids["qualified_entry_id"]]
        knockout = repo.get_match(connection, ids["knockout_match_id"])
        assert knockout["status"] == MatchStatus.FINISHED.value
        assert connection.execute(
            "SELECT COUNT(*) FROM score_audits WHERE match_id = ?",
            (ids["knockout_match_id"],),
        ).fetchone()[0] >= 1
        assert len(repo.list_qualification_decisions(connection, ids["group_id"])) == 1
        assert len(repo.list_matches(connection, ids["tournament_id"], "KNOCKOUT")) == 1


def test_corrupt_backup_is_rejected_without_overwriting_target(tmp_path):
    database_path = tmp_path / "target.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _initialize(database_path)
    _seed_registration_state(database_path)
    original_bytes = database_path.read_bytes()
    corrupt_backup = backup_dir / "corrupt.db"
    corrupt_backup.write_bytes(b"this is not a sqlite database")

    with pytest.raises(database_backup.DatabaseRestoreError, match="数据库校验失败"):
        database_backup.restore_database(
            corrupt_backup,
            database_path,
            backup_dir,
            service_stopped=True,
        )

    assert database_path.read_bytes() == original_bytes


def test_restore_requires_explicit_service_stopped_confirmation(tmp_path):
    database_path = tmp_path / "target.db"
    _initialize(database_path)
    backup = database_backup.backup_database(database_path, tmp_path / "backups")

    with pytest.raises(database_backup.DatabaseRestoreError, match="必须停止服务"):
        database_backup.restore_database(
            backup.backup_path,
            database_path,
            tmp_path / "backups",
        )


def test_old_migration_backup_is_upgraded_without_data_loss(tmp_path):
    old_backup = tmp_path / "old-v4.db"
    restored_path = tmp_path / "restored-v5.db"
    backup_dir = tmp_path / "backups"
    _initialize(old_backup)
    with _database(old_backup) as connection:
        tournament = repo.create_tournament(
            connection, "旧版本保留赛事", "2026-09-20", 2, 1, 1
        )
        player = repo.add_player(
            connection, tournament["id"], "旧版本保留选手", "历史学院", 1314
        )
        entry = repo.create_entry(
            connection,
            tournament["id"],
            "SINGLES",
            player["name"],
            player["rating_points"],
            [player["id"]],
        )
        connection.commit()

    with _database(old_backup) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE registrations")
        connection.execute("DROP TABLE organizations")
        connection.execute("DROP TABLE venues")
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")
        connection.commit()

    result = database_backup.restore_database(
        old_backup,
        restored_path,
        backup_dir,
        service_stopped=True,
    )

    assert result.schema_version == database_backup.SCHEMA_VERSION
    with _database(restored_path) as connection:
        restored_tournament = repo.get_tournament(connection, tournament["id"])
        restored_player = repo.get_player(connection, player["id"])
        restored_entry = repo.get_entry(connection, entry["id"])
        assert restored_tournament["name"] == "旧版本保留赛事"
        assert restored_player["name"] == "旧版本保留选手"
        assert restored_entry["display_name"] == "旧版本保留选手"
        for table in ("registrations", "organizations", "venues"):
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()[0] == 1


def test_atomic_replace_failure_keeps_target_database(tmp_path, monkeypatch):
    database_path = tmp_path / "target.db"
    backup_dir = tmp_path / "backups"
    _initialize(database_path)
    _seed_registration_state(database_path)
    backup = database_backup.backup_database(database_path, backup_dir)

    with _database(database_path) as connection:
        connection.execute("DELETE FROM tournaments")
        connection.execute("DELETE FROM users")
    before_failure = database_path.read_bytes()

    real_replace = database_backup.os.replace

    def fail_target_replace(source, target):
        if Path(target) == database_path:
            raise OSError("D6A 注入：原子替换前失败")
        return real_replace(source, target)

    monkeypatch.setattr(database_backup.os, "replace", fail_target_replace)
    with pytest.raises(database_backup.DatabaseRestoreError, match="原数据库保持不变"):
        database_backup.restore_database(
            backup.backup_path,
            database_path,
            backup_dir,
            service_stopped=True,
        )

    assert database_path.read_bytes() == before_failure
    assert list(tmp_path.glob(f".{database_path.name}.restore-*.tmp")) == []