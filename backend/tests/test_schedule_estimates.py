"""A2 预计上场时间（ETA V1）：只读模拟、复用调度规则、冷启动与真实中位数。"""

from datetime import datetime, timedelta, timezone

from app import repository as repo
from app.services import eta as eta_service
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import match_timing
from app.services import matches as matches_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service

# 固定基准时间（UTC），避免依赖本机时钟；格式与库内时间戳一致。
BASE = datetime(2026, 9, 18, 2, 0, 0, tzinfo=timezone.utc)
BASE_TEXT = match_timing.format_utc(BASE)

FINGERPRINT_TABLES = [
    "tournaments",
    "groups",
    "players",
    "entries",
    "entry_members",
    "tables",
    "matches",
    "match_games",
    "score_requests",
    "qualification_decisions",
]


def _db_fingerprint(conn):
    """整库指纹：ETA 只读性校验（复用 A1 导出测试的思路）。"""
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in FINGERPRINT_TABLES
    }


def _tournament(conn, *, players=24, group_count=4, table_count=6, **kwargs):
    tournament = repo.create_tournament(
        conn, "ETA 验收", "2025-06-01", table_count, group_count, 2, **kwargs
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, table_count)
    for index in range(players):
        repo.add_player(conn, tid, f"P{index + 1:02d}", None)
    groups_service.auto_group_tournament(conn, tid)
    matches_service.generate_group_matches(conn, tid)
    return tid


def _rows_by_match(result):
    return {row["match_id"]: row for row in result["matches"]}


def test_cold_start_uses_format_default_and_first_batch_starts_now(conn):
    tid = _tournament(conn, players=24, group_count=4, table_count=4)

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    assert result["estimate_basis"] == "FORMAT_DEFAULT"
    assert result["sample_count"] == 0
    assert result["estimated_match_duration_seconds"] == 15 * 60  # 三局两胜冷启动估算
    assert len(result["matches"]) == 60  # 全部 WAITING 比赛都有记录
    first = [row for row in result["matches"] if row["estimated_wait_minutes"] == 0]
    assert len(first) == 4  # 4 张空闲球台 → 第一批 4 场立即开始
    for row in result["matches"]:
        assert row["estimated_start_at"] is not None
        assert row["estimate_basis"] == "FORMAT_DEFAULT"


def test_estimates_follow_scheduler_recommendation(conn):
    """ETA 第一批必须与 dashboard / schedule-next 的推荐一致（同一套规则）。"""
    tid = _tournament(conn, players=24, group_count=4, table_count=4)
    dashboard = scheduling_service.get_dashboard(conn, tid)
    recommended = {
        table["id"]: table["recommended_match_id"]
        for table in dashboard["tables"]
        if table["recommended_match_id"] is not None
    }

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    immediate = {
        row["match_id"] for row in result["matches"] if row["estimated_wait_minutes"] == 0
    }
    assert immediate == set(recommended.values())


def test_queue_ahead_counts_earlier_starts(conn):
    tid = _tournament(conn, players=24, group_count=4, table_count=4)
    typical = 15 * 60

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    rows = _rows_by_match(result)
    by_wait: dict[float, list[dict]] = {}
    for row in result["matches"]:
        by_wait.setdefault(row["estimated_wait_minutes"], []).append(row)
    # 4 台 × 15 分钟一批：0 / 15 / 30 / 45 … 直到全部 60 场排完
    assert sorted(by_wait)[0] == 0.0
    assert sorted(by_wait)[1] == 15.0
    assert sorted(by_wait)[-1] == 15.0 * 14  # 60 场 / 4 台 = 15 批
    assert len(by_wait[0.0]) == 4 and len(by_wait[15.0]) == 4 and len(by_wait[30.0]) == 4
    assert all(row["queue_ahead"] == 0 for row in by_wait[0.0])
    assert all(row["queue_ahead"] == 4 for row in by_wait[15.0])
    assert all(row["queue_ahead"] == 8 for row in by_wait[30.0])
    for row in by_wait[15.0]:
        start = match_timing.parse_utc(row["estimated_start_at"])
        assert int((start - BASE).total_seconds()) == typical


def test_live_median_basis_after_enough_real_samples(conn):
    tid = _tournament(conn, players=6, group_count=1, table_count=1)
    # 构造 3 场真实完成的比赛：10 / 12 / 14 分钟
    for match, minutes in zip(repo.list_matches(conn, tid), (10, 12, 14)):
        start = BASE - timedelta(minutes=minutes + 5)
        conn.execute(
            "UPDATE matches SET status = 'FINISHED', result_type = 'NORMAL', "
            "started_at = ?, finished_at = ? WHERE id = ?",
            (match_timing.format_utc(start), match_timing.format_utc(start + timedelta(minutes=minutes)), match["id"]),
        )
    conn.commit()

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    assert result["estimate_basis"] == "LIVE_MEDIAN"
    assert result["sample_count"] == 3
    assert result["estimated_match_duration_seconds"] == 12 * 60  # 中位数


def test_playing_match_uses_remaining_time_not_full_cycle(conn):
    """已打 13 分钟的进行中比赛，只剩约 2 分钟，不应再占满一个完整周期。"""
    tid = _tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    conn.execute(
        "UPDATE matches SET called_at = ?, started_at = ? WHERE id = ?",
        (match_timing.format_utc(BASE - timedelta(minutes=13)),
         match_timing.format_utc(BASE - timedelta(minutes=13)), match["id"]),
    )
    conn.commit()

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    assert result["initial_playing_matches"] == 1
    assert result["estimated_match_duration_seconds"] == 15 * 60
    # 球台被占用到约 T0+2min，之后第一批比赛才能开始
    waits = sorted({row["estimated_wait_minutes"] for row in result["matches"]})
    assert waits[0] == 2.0, f"剩余时间应按 15-13=2 分钟计算，实际 {waits[0]}"


def test_playing_match_without_started_at_falls_back_to_full_cycle(conn):
    """旧数据没有 started_at（A2 之前上台）：保守按完整周期处理。"""
    tid = _tournament(conn, players=6, group_count=1, table_count=1)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    conn.execute(
        "UPDATE matches SET started_at = NULL, called_at = NULL WHERE id = ?", (match["id"],)
    )
    conn.commit()

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    waits = sorted({row["estimated_wait_minutes"] for row in result["matches"]})
    assert waits[0] == 15.0


def test_pending_bracket_slots_have_null_estimate(conn):
    """签位未定的后续轮次宁可返回 null，也不编造时间。"""
    tid = _tournament(conn, players=16, group_count=4, table_count=4)
    for match in repo.list_matches(conn, tid, stage="GROUP"):
        winner = min(match["player_a_id"], match["player_b_id"])
        score_a, score_b = (2, 0) if winner == match["player_a_id"] else (0, 2)
        scheduling_service.assign_table(conn, match["id"], repo.list_tables(conn, tid)[0]["id"])
        scores_service.record_score(conn, match["id"], score_a, score_b)
    knockout_service.generate_knockout(conn, tid)

    result = eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    pending = [
        row for row in result["matches"]
        if row["stage"] == "KNOCKOUT" and row["round"] > 1
    ]
    assert pending, "应有后续轮次比赛"
    for row in pending:
        assert row["estimated_start_at"] is None
        assert row["estimated_wait_minutes"] is None
        assert row["queue_ahead"] is None
        assert row["estimate_basis"] is None
        assert row["unavailable_reason"] == eta_service.REASON_BRACKET_PENDING
    # 首轮淘汰赛双方已确定 → 必须有估算
    first_round = [
        row for row in result["matches"]
        if row["stage"] == "KNOCKOUT" and row["round"] == 1
    ]
    assert first_round and all(row["estimated_start_at"] is not None for row in first_round)


def test_estimates_are_read_only(conn):
    tid = _tournament(conn, players=24, group_count=4, table_count=3)
    scheduling_service.schedule_next(conn, tid)  # 制造进行中比赛
    before = _db_fingerprint(conn)

    eta_service.estimate_schedule(conn, tid, now=BASE_TEXT)

    assert _db_fingerprint(conn) == before, "ETA 必须是只读模拟"


def test_api_schedule_estimates_contract(client):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "ETA 接口",
            "date": "2025-06-01",
            "table_count": 2,
            "group_count": 2,
            "qualify_per_group": 1,
        },
    ).json()["id"]
    for index in range(4):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{index + 1}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    resp = client.get(f"/api/tournaments/{tid}/schedule-estimates")

    assert resp.status_code == 200
    body = resp.json()
    assert body["tournament_id"] == tid
    assert body["estimate_basis"] == "FORMAT_DEFAULT"
    assert body["estimated_match_duration_seconds"] > 0
    assert len(body["matches"]) == 2
    for row in body["matches"]:
        assert row["estimated_start_at"] is not None
        assert row["estimated_wait_minutes"] == 0
        assert row["queue_ahead"] == 0

    assert client.get("/api/tournaments/999999/schedule-estimates").status_code == 404
