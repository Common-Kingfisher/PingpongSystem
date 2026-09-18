"""A2 比赛时间基础：时间戳生命周期、旧库迁移、真实耗时样本与典型耗时。"""

from datetime import datetime, timedelta

import pytest

from app import db as db_module
from app import repository as repo
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import match_timing
from app.services import matches as matches_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


def _service_tournament(conn, *, players=24, group_count=4, table_count=6, qualify_per_group=2, **kwargs):
    tournament = repo.create_tournament(
        conn, "时间基础验收", "2025-06-01", table_count, group_count, qualify_per_group, **kwargs
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, table_count)
    for index in range(players):
        repo.add_player(conn, tid, f"P{index + 1:02d}", None)
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    return tid


def _set_times(conn, match_id, *, called=None, started=None, finished=None):
    """测试专用：直接写时间字段，用于构造受控的耗时样本。"""
    conn.execute(
        "UPDATE matches SET called_at = ?, started_at = ?, finished_at = ? WHERE id = ?",
        (called, started, finished, match_id),
    )
    conn.commit()


# ------------------------------------------------------------- 淘汰赛时间透传

def test_knockout_service_passes_through_match_times(conn):
    """淘汰赛读取路径必须透传时间字段（否则 KnockoutMatchOut 的默认 None 会静默丢时间）。"""
    tid = _service_tournament(conn, players=8, group_count=4, table_count=4, qualify_per_group=2)
    for match in repo.list_matches(conn, tid, stage="GROUP"):
        winner = min(match["player_a_id"], match["player_b_id"])
        score_a, score_b = (2, 0) if winner == match["player_a_id"] else (0, 2)
        scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
        scores_service.record_score(conn, match["id"], score_a, score_b)
    knockout_service.generate_knockout(conn, tid)

    first_round = [
        match for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["bracket"] == "MAIN" and match["round"] == 1
    ]
    target = first_round[0]
    scheduling_service.assign_table(conn, target["id"], repo.list_tables(conn, tid)[0]["id"])
    scores_service.record_score(conn, target["id"], 2, 0)
    stored = repo.get_match(conn, target["id"])
    assert stored["started_at"] is not None and stored["finished_at"] is not None

    tree = knockout_service.get_knockout(conn, tid)

    exported = next(
        match for match in tree["rounds"][0]["matches"] if match["id"] == target["id"]
    )
    assert exported["called_at"] == stored["called_at"]
    assert exported["started_at"] == stored["started_at"]
    assert exported["finished_at"] == stored["finished_at"]
    # 未开始的后续轮次时间必须保持为空，而不是被填充成估算值
    pending = [
        match for round_ in tree["rounds"][1:] for match in round_["matches"]
    ]
    assert pending and all(
        match["called_at"] is None and match["started_at"] is None
        and match["finished_at"] is None
        for match in pending
    )


def test_knockout_api_returns_times_recorded_in_database(client):
    """API 路径同样不能丢时间：淘汰赛录分后 GET /knockout 与数据库一致。"""
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "淘汰赛时间透传",
            "date": "2025-06-01",
            "table_count": 1,
            "group_count": 2,
            "qualify_per_group": 1,
        },
    ).json()["id"]
    for index in range(4):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    table_id = client.get(f"/api/tournaments/{tid}/dashboard").json()["tables"][0]["id"]
    for match in client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json():
        winner = min(match["player_a_id"], match["player_b_id"])
        score_a, score_b = (2, 0) if winner == match["player_a_id"] else (0, 2)
        client.post(f"/api/matches/{match['id']}/assign-table", json={"table_id": table_id})
        client.post(
            f"/api/matches/{match['id']}/score",
            json={"player_a_score": score_a, "player_b_score": score_b},
        )
    assert client.post(f"/api/tournaments/{tid}/generate-knockout").status_code == 200

    final = client.get(f"/api/tournaments/{tid}/knockout").json()["rounds"][0]["matches"][0]
    client.post(f"/api/matches/{final['id']}/assign-table", json={"table_id": table_id})
    client.post(
        f"/api/matches/{final['id']}/score",
        json={"player_a_score": 2, "player_b_score": 1},
    )

    round_one = client.get(f"/api/tournaments/{tid}/knockout").json()["rounds"][0]["matches"]
    exported = next(match for match in round_one if match["id"] == final["id"])
    db = db_module.connect()
    try:
        stored = repo.get_match(db, final["id"])
    finally:
        db.close()

    assert stored["started_at"] is not None and stored["finished_at"] is not None
    assert exported["called_at"] == stored["called_at"]
    assert exported["started_at"] == stored["started_at"]
    assert exported["finished_at"] == stored["finished_at"]
    assert exported["status"] == "FINISHED"


# ------------------------------------------------------------- 旧库迁移

def test_legacy_database_gets_time_columns_on_startup(tmp_path, monkeypatch):
    """旧库（无三列）启动后自动补列，且原有比赛数据保留。"""
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "legacy.db"))
    db_module.init_db()
    conn = db_module.connect()
    tid = _service_tournament(conn, players=4, group_count=2, table_count=2)
    match_id = repo.list_matches(conn, tid)[0]["id"]
    conn.commit()
    conn.close()

    # 模拟旧库：删掉 A2 新增的三列
    conn = db_module.connect()
    for column in ("called_at", "started_at", "finished_at"):
        conn.execute(f"ALTER TABLE matches DROP COLUMN {column}")
    conn.commit()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    assert {"called_at", "started_at", "finished_at"}.isdisjoint(columns)
    conn.close()

    # 重新启动 → 轻量迁移补列
    db_module.init_db()
    conn = db_module.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    assert {"called_at", "started_at", "finished_at"} <= columns
    match = repo.get_match(conn, match_id)
    assert match is not None and match["status"] == "WAITING"
    assert match["called_at"] is None and match["started_at"] is None
    assert match["finished_at"] is None
    assert len(repo.list_matches(conn, tid)) == 2  # 原有比赛数据保留
    conn.close()


# ------------------------------------------------------------- 时间状态机

def test_manual_assign_writes_called_and_started(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]

    updated = scheduling_service.assign_table(conn, match["id"], table["id"])

    assert updated["status"] == "PLAYING"
    assert updated["called_at"] is not None
    assert updated["started_at"] == updated["called_at"]
    assert updated["finished_at"] is None


def test_auto_schedule_writes_time_for_every_assignment(conn):
    tid = _service_tournament(conn, players=24, group_count=4, table_count=6)

    assignments = scheduling_service.schedule_next(conn, tid)

    assert len(assignments) == 6
    for match_id, _table_id in assignments:
        match = repo.get_match(conn, match_id)
        assert match["called_at"] is not None, "自动排台必须写 called_at"
        assert match["started_at"] == match["called_at"], "自动排台必须写 started_at"
        assert match["finished_at"] is None


def test_release_clears_started_but_keeps_called(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    assigned = scheduling_service.assign_table(conn, match["id"], table["id"])

    released = scheduling_service.release_match(conn, match["id"])

    assert released["status"] == "WAITING"
    assert released["table_id"] is None
    assert released["started_at"] is None, "下球台表示本次上台未形成有效进行中比赛"
    assert released["called_at"] == assigned["called_at"], "called_at 保留最近一次叫号事实"
    assert released["finished_at"] is None


def test_reassign_refreshes_clocks(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    scheduling_service.release_match(conn, match["id"])
    # 把叫号时间改成过去，便于验证"重新安排会刷新"
    _set_times(conn, match["id"], called="2020-01-01 00:00:00")

    reassigned = scheduling_service.assign_table(conn, match["id"], table["id"])

    assert reassigned["called_at"] != "2020-01-01 00:00:00"
    assert reassigned["started_at"] == reassigned["called_at"]
    assert reassigned["finished_at"] is None


def test_finish_from_playing_writes_only_finished_at(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    # 开始时间设为库内 UTC 时间的 12 分钟前，构造一个有效耗时样本
    # （时间戳统一为 UTC，不能用本机本地时间硬编码）
    conn.execute(
        "UPDATE matches SET called_at = datetime('now', '-12 minutes'), "
        "started_at = datetime('now', '-12 minutes') WHERE id = ?",
        (match["id"],),
    )
    conn.commit()
    started_before = repo.get_match(conn, match["id"])["started_at"]

    finished = scores_service.record_score(conn, match["id"], 2, 0)

    assert finished["status"] == "FINISHED"
    assert finished["called_at"] == started_before
    assert finished["started_at"] == started_before
    assert finished["finished_at"] is not None
    assert finished["finished_at"] != started_before
    assert match_timing.real_match_duration_seconds(finished) == 12 * 60


def test_waiting_direct_score_has_no_started_time(conn):
    """WAITING 直接录分（淘汰赛页面路径）：不伪造开始时间，也不进入耗时样本。"""
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]

    finished = scores_service.record_score(conn, match["id"], 2, 0)

    assert finished["status"] == "FINISHED"
    assert finished["started_at"] is None
    assert finished["called_at"] is None
    assert finished["finished_at"] is not None
    assert match_timing.real_match_duration_seconds(finished) is None
    assert match_timing.list_duration_samples(conn, tid) == []


def test_revise_score_preserves_times(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    scores_service.record_score(conn, match["id"], 2, 0)
    # 实际 15:10 结束，15:32 才来纠错
    _set_times(
        conn, match["id"],
        called="2026-09-18 14:55:00", started="2026-09-18 14:55:00",
        finished="2026-09-18 15:10:00",
    )

    revised = scores_service.revise_score(conn, match["id"], 2, 1)

    assert revised["called_at"] == "2026-09-18 14:55:00"
    assert revised["started_at"] == "2026-09-18 14:55:00"
    assert revised["finished_at"] == "2026-09-18 15:10:00"
    assert match_timing.real_match_duration_seconds(revised) == 15 * 60

    # 补录小分同样不得改动时间（决胜局必须排在最后一场）
    supplemented = scores_service.revise_score(
        conn, match["id"], None, None, games=[(11, 9), (9, 11), (11, 5)]
    )
    assert supplemented["finished_at"] == "2026-09-18 15:10:00"


@pytest.mark.parametrize(
    "result_type", ["FORFEIT", "WALKOVER", "NO_SHOW", "DISQUALIFIED"]
)
def test_abnormal_results_excluded_from_duration(conn, result_type):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    entries = repo.list_entries(conn, tid)
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    finished = scores_service.record_score(
        conn, match["id"], None, None,
        result_type=result_type, forfeit_entry_id=entries[0]["id"],
    )

    assert finished["status"] == "FINISHED"
    assert finished["result_type"] == result_type
    assert finished["started_at"] is not None, "先上台再异常结束仍保留开始时间"
    assert finished["finished_at"] is not None
    assert match_timing.real_match_duration_seconds(finished) is None
    assert match_timing.list_duration_samples(conn, tid) == []


def test_system_bye_has_no_times_and_no_duration(conn):
    """6 组 = 12 人 → 16 签：系统轮空是派生结果，不写时间、不进耗时样本。"""
    tid = _service_tournament(conn, players=12, group_count=6, table_count=4)
    for match in repo.list_matches(conn, tid, stage="GROUP"):
        scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
        scores_service.record_score(conn, match["id"], 2, 0)
    knockout_service.generate_knockout(conn, tid)

    byes = [
        match for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["result_type"] == "WALKOVER"
    ]
    assert len(byes) == 4
    for bye in byes:
        assert bye["called_at"] is None
        assert bye["started_at"] is None
        assert bye["finished_at"] is None, "轮空不产生真实结束时间"
        assert match_timing.real_match_duration_seconds(bye) is None


# ------------------------------------------------------------- 耗时与典型值

def test_duration_samples_require_sane_times(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    matches = repo.list_matches(conn, tid)
    _set_times(conn, matches[0]["id"], started="2026-09-18 10:00:00", finished="2026-09-18 10:12:00")
    _set_times(conn, matches[1]["id"], started="2026-09-18 10:00:00", finished="2026-09-18 10:00:00")
    _set_times(conn, matches[2]["id"], started="2026-09-18 10:00:00", finished="2026-09-18 09:59:00")
    _set_times(conn, matches[3]["id"], started="2026-09-18 10:00:00", finished=None)

    samples = match_timing.list_duration_samples(conn, tid)

    assert samples == [12 * 60]  # 只保留 12 分钟那一场


def test_typical_duration_uses_median_and_resists_outliers(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)
    durations = [10, 12, 14, 60]
    start = datetime(2026, 9, 18, 10, 0, 0)
    for match, minutes in zip(repo.list_matches(conn, tid), durations):
        finish = start + timedelta(minutes=minutes)
        _set_times(
            conn, match["id"],
            started=match_timing.format_utc(start),
            finished=match_timing.format_utc(finish),
        )

    typical = match_timing.typical_duration_seconds(conn, tid)

    assert typical["basis"] == "LIVE_MEDIAN"
    assert typical["sample_count"] == 4
    assert typical["seconds"] == 13 * 60, "中位数不应被 60 分钟极端值拖偏"
    mean_seconds = sum(d * 60 for d in durations) / len(durations)
    assert typical["seconds"] < mean_seconds


def test_typical_duration_cold_start_uses_format_default(conn):
    tid = _service_tournament(conn, players=6, group_count=1, table_count=1)

    typical = match_timing.typical_duration_seconds(conn, tid)

    assert typical["basis"] == "FORMAT_DEFAULT"
    assert typical["sample_count"] == 0
    expected = match_timing.DEFAULT_DURATION_SECONDS_BY_GAMES_TO_WIN[2]
    assert typical["seconds"] == expected

    # 赛制不同 → 冷启动估算不同（五局三胜比三局两胜长；21 分制按比例放大）
    assert match_timing.format_default_duration_seconds(3, 11) > expected
    assert match_timing.format_default_duration_seconds(2, 21) > expected
