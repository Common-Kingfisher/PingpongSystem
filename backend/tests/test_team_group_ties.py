"""A6.1：团体小组循环 TeamTie 自动生成（Group Tie Generator）。

本文件锁死的行为（对应验收标准）：

1. **只做小组内单循环**：4 队单组 → 6 场；两个 4 队组 → 12 场；不跨组、不自己打自己、
   每个 unordered pair 恰好一次；3 队 / 5 队（奇数）不制造 `队伍 vs NULL` 的假对抗。
2. **确定性**：`round` 从 1 开始、`match_index` 是轮内从 1 开始的稳定场序，
   且与复用的小组赛算法（`domain/round_robin.round_robin`）逐场一致。
3. **生成前校验**：赛事不存在 → 404；非 TEAM → 409；
   有任何**未分组**的 ACTIVE 队伍 → 409 且**整批拒绝**（0 条新增）；
   已有任何 `stage=GROUP` 对抗（手工的也算）→ 409，不补齐 / 不覆盖 / 不重新生成。
4. **原子性与并发**：整个生成是一个 `BEGIN IMMEDIATE` 写事务；两个并发生成请求
   恰好一个成功、另一个拿到 409，绝不出现两套赛程、也绝不把 SQLite 锁错误漏成 500。
5. **不改赛事阶段**：本批次只生成 TeamTie，`tournaments.stage` 保持原样
   （TEAM 的 REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED 推进规则未冻结）。
6. **与既有 Runtime 兼容**：自动生成的对抗可以继续走
   `LOCAL_CLASSIC_5_V1` → rubber skeleton → 阵容 → start → 录分。

刻意**不在**这里测试（因为本批次**没有**实现，见 docs/TEAM_DOMAIN.md）：
团体小组积分/排名/出线、团体淘汰赛、团体 Scheduler/ETA、自动批量生成 rubber skeleton。
"""

import concurrent.futures
import itertools
import sqlite3
import threading

import pytest

from app import db as db_module
from app import repository as repo
from app.domain import round_robin
from app.models import EventType, MatchStage
from app.services import team_runtime as runtime
from app.services import team_ties as tie_service
from app.services import teams as teams_service

FORMAT_CODE = "LOCAL_CLASSIC_5_V1"
GENERATE_URL = "/api/tournaments/{tid}/team-ties/generate-group-ties"


# ------------------------------------------------------------------ 夹具与工具

def _team_tournament(conn, *, players: int, name: str = "团体小组循环验收", group_count: int = 1) -> int:
    tournament = repo.create_tournament(
        conn, name, "2026-08-01", 4, group_count, 1,
        event_type=EventType.TEAM.value, operation_mode="DEMO",
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 4)
    for index in range(1, players + 1):
        repo.add_player(conn, tid, f"选手{index:02d}", "计算机学院", 1000 + index)
    conn.commit()
    return tid


def _make_teams(conn, tid: int, count: int, *, size: int = 1) -> list[dict]:
    """建立 count 支队伍（每队 size 人），返回按 id 升序的队伍列表。"""
    players = repo.list_players(conn, tid)
    teams = []
    for index in range(count):
        members = [p["id"] for p in players[index * size : (index + 1) * size]]
        teams.append(teams_service.create_team_entry(conn, tid, f"{index + 1}队", members))
    return teams


def _group_all(conn, tid: int, teams: list[dict], size: int) -> list[dict]:
    """把队伍按每组 size 支依次装进 A组 / B组……。"""
    groups = [
        repo.create_group(conn, tid, f"第{chr(ord('A') + i)}组", i)
        for i in range(len(teams) // size)
    ]
    for index, entry in enumerate(teams):
        repo.set_entry_group(conn, entry["id"], groups[index // size]["id"])
    conn.commit()
    return groups


def _group_members(conn, tid: int, group_id: int) -> list[int]:
    """该组里的在赛队伍（按 id 升序）——生成器用的就是这份稳定顺序。"""
    return sorted(
        e["id"]
        for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value)
        if e["status"] == "ACTIVE" and e["group_id"] == group_id
    )


def _ties_fingerprint(conn, tid: int, group_id: int) -> list[tuple[int, int, int, int]]:
    """(round, match_index, entry_a_id, entry_b_id) —— 用于"未变过"的断言。"""
    return [
        (t["round"], t["match_index"], t["entry_a_id"], t["entry_b_id"])
        for t in repo.list_group_team_ties(conn, tid, group_id)
    ]


def _assert_group_schedule_matches_algorithm(conn, tid: int, group_id: int) -> None:
    """该组落库的对抗必须与 `round_robin` 的输出**逐场一致**（round / match_index / 双方）。

    这是"生成器没有自己发明第二份编排算法"的可执行证明：顺序、序号、配对全部对齐。
    """
    members = _group_members(conn, tid, group_id)
    expected = round_robin.round_robin(members)
    rows = repo.list_group_team_ties(conn, tid, group_id)
    assert len(rows) == len(expected)

    seen_in_round: dict[int, set[int]] = {}
    for (round_num, a, b), row in zip(expected, rows):
        assert (row["round"], row["entry_a_id"], row["entry_b_id"]) == (round_num, a, b)
        assert row["stage"] == MatchStage.GROUP.value
        assert row["group_id"] == group_id
        assert row["status"] == "WAITING"  # 只生成对抗，不预填比分/状态/赛制
        assert row["match_index"] is not None and row["match_index"] >= 1
        # 同一轮内同一支队伍最多出场一次
        played = seen_in_round.setdefault(round_num, set())
        assert a not in played and b not in played
        played.update((a, b))

    # match_index 在每个 round 内从 1 连续递增
    by_round: dict[int, list[int]] = {}
    for row in rows:
        by_round.setdefault(row["round"], []).append(row["match_index"])
    for indexes in by_round.values():
        assert indexes == list(range(1, len(indexes) + 1))
    assert sorted(by_round) == sorted({r for r, _, _ in expected})


def _assert_every_pair_once(conn, tid: int, group_id: int) -> None:
    """组内每个 unordered pair 恰好出现一次，且没有自己打自己 / 跨组。"""
    members = _group_members(conn, tid, group_id)
    rows = repo.list_group_team_ties(conn, tid, group_id)
    pairs = [frozenset((r["entry_a_id"], r["entry_b_id"])) for r in rows]
    assert all(len(pair) == 2 for pair in pairs), "出现自己打自己"
    assert len(pairs) == len(set(pairs)), "出现重复对阵"
    assert set(pairs) == {frozenset(pair) for pair in itertools.combinations(members, 2)}
    for row in rows:
        assert row["entry_a_id"] in members and row["entry_b_id"] in members, "出现跨组对阵"


def _run_in_parallel(*calls):
    """在两个独立 SQLite 连接（两个线程）上并发执行服务调用。

    用一个 `Barrier` 让两个线程尽量**同时**进入服务调用（否则第二个线程可能在第一个
    线程提交之后才开始，那就只测到了"重复生成"这条守卫，而没有压到并发路径）。
    """

    def run(fn, barrier):
        worker_conn = db_module.connect()
        try:
            barrier.wait(timeout=15)
            return ("ok", fn(worker_conn))
        except Exception as exc:  # noqa: BLE001 - 测试需要同时收集成功与业务错误
            return ("err", exc)
        finally:
            worker_conn.close()

    barrier = threading.Barrier(len(calls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, fn, barrier) for fn in calls]
        return [f.result() for f in futures]


# ------------------------------------------------------------------ Case 1：4 队单组

def test_case1_four_teams_one_group_generates_six_ties(conn):
    tid = _team_tournament(conn, players=4)
    teams = _make_teams(conn, tid, 4)
    groups = _group_all(conn, tid, teams, 4)
    group = groups[0]

    result = tie_service.generate_group_ties(conn, tid)

    assert result["ties_generated"] == 6
    assert result["per_group"] == {group["name"]: 6}
    _assert_group_schedule_matches_algorithm(conn, tid, group["id"])
    _assert_every_pair_once(conn, tid, group["id"])

    # 3 轮 × 2 场（4 队 = n-1 轮，每轮 n/2 场）
    assert sorted({t["round"] for t in repo.list_group_team_ties(conn, tid, group["id"])}) == [1, 2, 3]
    # 只生成 TeamTie：没有 Match、没有 rubber 骨架、对抗也没有被预置赛制
    ties = repo.list_team_ties(conn, tid)
    assert len(ties) == 6
    assert all(
        (t["format_code"], t["team_a_score"], t["team_b_score"], t["winner_entry_id"])
        == (None, 0, 0, None)
        for t in ties
    )
    assert repo.list_matches(conn, tid) == []
    assert repo.list_tournament_team_rubbers(conn, tid) == []


# ------------------------------------------------------------------ Case 2：两个 4 队组

def test_case2_two_groups_of_four_generate_twelve_ties_without_cross_group(conn):
    tid = _team_tournament(conn, players=8, group_count=2)
    teams = _make_teams(conn, tid, 8)
    groups = _group_all(conn, tid, teams, 4)
    assert len(groups) == 2

    result = tie_service.generate_group_ties(conn, tid)

    assert result["ties_generated"] == 12
    assert result["per_group"] == {groups[0]["name"]: 6, groups[1]["name"]: 6}
    for group in groups:
        _assert_group_schedule_matches_algorithm(conn, tid, group["id"])
        _assert_every_pair_once(conn, tid, group["id"])

    # 绝不跨组：每条对抗的 group_id 必须等于双方队伍所在的小组
    group_of_entry = {
        e["id"]: e["group_id"]
        for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value)
    }
    for tie in repo.list_team_ties(conn, tid):
        assert group_of_entry[tie["entry_a_id"]] == tie["group_id"]
        assert group_of_entry[tie["entry_b_id"]] == tie["group_id"]
    assert len(repo.list_team_ties(conn, tid)) == 12


# ------------------------------------------------------------------ Case 3 / 4：奇数队伍

def test_case3_three_teams_one_group_generates_three_ties_without_bye_rows(conn):
    tid = _team_tournament(conn, players=3)
    teams = _make_teams(conn, tid, 3)
    group = _group_all(conn, tid, teams, 3)[0]

    result = tie_service.generate_group_ties(conn, tid)

    assert result["ties_generated"] == 3
    ties = repo.list_team_ties(conn, tid)
    assert len(ties) == 3
    # 3 队 = 3 轮 × 1 场，每轮 1 队轮空；轮空**不落库**
    _assert_every_pair_once(conn, tid, group["id"])
    assert sorted({t["round"] for t in ties}) == [1, 2, 3]
    assert all(t["entry_a_id"] is not None and t["entry_b_id"] is not None for t in ties)
    for tie in ties:
        assert tie["entry_a_id"] != tie["entry_b_id"]
    assert all(tie["match_index"] == 1 for tie in ties)


def test_case4_five_teams_one_group_generates_ten_ties(conn):
    tid = _team_tournament(conn, players=5)
    teams = _make_teams(conn, tid, 5)
    group = _group_all(conn, tid, teams, 5)[0]

    result = tie_service.generate_group_ties(conn, tid)

    assert result["ties_generated"] == 10  # 5×4/2
    assert result["per_group"] == {group["name"]: 10}
    _assert_every_pair_once(conn, tid, group["id"])
    # 5 队 = 5 轮 × 2 场 + 每轮 1 队轮空（轮空不产生对抗）
    rows = repo.list_group_team_ties(conn, tid, group["id"])
    assert sorted({t["round"] for t in rows}) == [1, 2, 3, 4, 5]
    assert all(len({r["entry_a_id"], r["entry_b_id"]}) == 2 for r in rows)
    assert all(t["entry_a_id"] is not None and t["entry_b_id"] is not None for t in rows)


# ------------------------------------------------------------------ Case 5：未分组队伍

def test_case5_ungrouped_active_team_blocks_the_whole_generation(conn):
    """只要还有 ACTIVE 队伍没分组，就不能"给已分组的队伍先生成一部分"。"""
    tid = _team_tournament(conn, players=4, group_count=1)
    teams = _make_teams(conn, tid, 4)
    group = _group_all(conn, tid, teams, 4)[0]
    # 把最后一支队伍退回"未分组"
    repo.set_entry_group(conn, teams[-1]["id"], None)
    conn.commit()

    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.generate_group_ties(conn, tid)
    assert excinfo.value.code == 409
    assert "未完成分组" in str(excinfo.value)
    assert "1 支" in str(excinfo.value)

    # 数据库保持原状：0 条新增
    assert repo.list_team_ties(conn, tid) == []
    assert repo.list_group_team_ties(conn, tid, group["id"]) == []

    # 未分组的队伍被剔除后（分组完成）才允许生成
    repo.set_entry_group(conn, teams[-1]["id"], group["id"])
    conn.commit()
    assert tie_service.generate_group_ties(conn, tid)["ties_generated"] == 6


def test_no_groups_at_all_is_rejected(conn):
    tid = _team_tournament(conn, players=4)
    _make_teams(conn, tid, 4)
    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.generate_group_ties(conn, tid)
    assert excinfo.value.code == 409
    assert "请先完成分组" in str(excinfo.value)
    assert repo.list_team_ties(conn, tid) == []


# ------------------------------------------------------------------ Case 6：非 TEAM 赛事

def test_case6_non_team_tournament_is_rejected(conn):
    singles = repo.create_tournament(conn, "单打赛", "2026-08-01", 4, 1, 1, event_type="SINGLES")
    conn.commit()
    singles_id = singles["id"]
    repo.create_group(conn, singles_id, "A组", 0)
    conn.commit()

    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.generate_group_ties(conn, singles_id)
    assert excinfo.value.code == 409
    assert "TEAM" in str(excinfo.value)
    assert repo.list_team_ties(conn, singles_id) == []

    with pytest.raises(tie_service.TeamTieError) as missing:
        tie_service.generate_group_ties(conn, 999999)
    assert missing.value.code == 404


# ------------------------------------------------------------------ Case 7：重复生成

def test_case7_second_generation_is_rejected_and_does_not_double(conn):
    tid = _team_tournament(conn, players=4)
    _group_all(conn, tid, _make_teams(conn, tid, 4), 4)
    assert tie_service.generate_group_ties(conn, tid)["ties_generated"] == 6

    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.generate_group_ties(conn, tid)
    assert excinfo.value.code == 409
    assert "不能重复生成" in str(excinfo.value)

    # 数量没有翻倍，而且逐场完全没变
    assert len(repo.list_team_ties(conn, tid)) == 6
    first = repo.list_team_ties(conn, tid)
    with pytest.raises(tie_service.TeamTieError):
        tie_service.generate_group_ties(conn, tid)
    assert repo.list_team_ties(conn, tid) == first


# ------------------------------------------------------------------ Case 8：已有手工对抗

def test_case8_manually_created_group_tie_blocks_auto_generation(conn):
    """手工赛程 + 自动赛程混在一起会产生重复对阵 / round 与场序冲突，因此整体 409。"""
    tid = _team_tournament(conn, players=4)
    teams = _make_teams(conn, tid, 4)
    group = _group_all(conn, tid, teams, 4)[0]
    manual = tie_service.create_team_tie(
        conn, tid, teams[0]["id"], teams[1]["id"],
        stage=MatchStage.GROUP.value, group_id=group["id"], round_num=1, match_index=1,
    )
    before = _ties_fingerprint(conn, tid, group["id"])

    with pytest.raises(tie_service.TeamTieError) as excinfo:
        tie_service.generate_group_ties(conn, tid)
    assert excinfo.value.code == 409
    assert "不能重复生成" in str(excinfo.value)

    # 不补齐（没有变成 6 条）、不覆盖、不删除
    assert _ties_fingerprint(conn, tid, group["id"]) == before
    assert repo.list_team_ties(conn, tid) == [repo.get_team_tie(conn, manual["id"])]
    assert len(repo.list_team_ties(conn, tid)) == 1


def test_knockout_tie_does_not_block_group_generation(conn):
    """重复生成的守卫只认 `stage=GROUP`：淘汰赛对抗不参与小组赛编排。"""
    tid = _team_tournament(conn, players=4)
    teams = _make_teams(conn, tid, 4)
    group = _group_all(conn, tid, teams, 4)[0]
    tie_service.create_team_tie(
        conn, tid, teams[0]["id"], teams[1]["id"], stage=MatchStage.KNOCKOUT.value
    )

    result = tie_service.generate_group_ties(conn, tid)
    assert result["ties_generated"] == 6
    stages = [t["stage"] for t in repo.list_team_ties(conn, tid)]
    assert stages.count(MatchStage.KNOCKOUT.value) == 1
    assert stages.count(MatchStage.GROUP.value) == 6
    _assert_group_schedule_matches_algorithm(conn, tid, group["id"])


# ------------------------------------------------------------------ Case 9：退赛队伍

def test_case9_withdrawn_team_gets_no_new_tie(conn):
    """退赛语义沿用既有规则：已退赛队伍不参与生成，其余队伍照常单循环。"""
    tid = _team_tournament(conn, players=4)
    teams = _make_teams(conn, tid, 4)
    group = _group_all(conn, tid, teams, 4)[0]
    withdrawn = teams[3]["id"]
    repo.withdraw_entry(conn, withdrawn, "主裁判", "伤病退赛")
    conn.commit()

    result = tie_service.generate_group_ties(conn, tid)

    assert result["ties_generated"] == 3  # 剩下 3 支在赛队伍 → 3×2/2
    remaining = [t for t in teams if t["id"] != withdrawn]
    rows = repo.list_group_team_ties(conn, tid, group["id"])
    assert {r["entry_a_id"] for r in rows} | {r["entry_b_id"] for r in rows} == {
        t["id"] for t in remaining
    }
    assert all(withdrawn not in (r["entry_a_id"], r["entry_b_id"]) for r in rows)
    # 已退赛队伍的对抗不会被"补"出来，也不会被伪造
    assert repo.list_matches(conn, tid) == []


def test_group_left_with_one_active_team_produces_no_tie(conn):
    """某组退赛到只剩 1 支队伍 → 该组 0 场（不是错误，也不伪造对抗）。"""
    tid = _team_tournament(conn, players=2, group_count=1)
    teams = _make_teams(conn, tid, 2)
    group = _group_all(conn, tid, teams, 2)[0]
    repo.withdraw_entry(conn, teams[1]["id"], "主裁判", "退赛")
    conn.commit()

    result = tie_service.generate_group_ties(conn, tid)
    assert result == {"ties_generated": 0, "per_group": {group["name"]: 0}}
    assert repo.list_team_ties(conn, tid) == []


# ------------------------------------------------------------------ Case 10：并发生成

def test_case10_concurrent_generation_leaves_exactly_one_schedule(conn):
    """两个独立连接同时生成：一个成功、另一个 409；最终恰好一套对抗（不翻倍、不 500）。

    跑多轮以覆盖两条并发路径（两条都必须是"一个成功 + 一个可读的 409"）：

    - 两个请求都通过了事务前的快速校验（都读到"还没有对抗"），进入写事务后串行化；
      后拿到写锁的请求读到前者**已提交**的对抗 → 409「已经生成…不能重复生成」；
    - 或者后一个请求压根拿不到写锁（前者还在写）→ 409「正在被另一个请求生成」。

    无论哪条路径，落库结果都必须是**恰好一套** 12 条对抗，且错误永远是业务异常
    （`TeamTieError` / 409），绝不出现 `sqlite3.Error` 或 500。
    """
    duplicate_path_seen = 0
    for attempt in range(5):
        tid = _team_tournament(conn, players=8, name=f"并发生成 {attempt}", group_count=2)
        _group_all(conn, tid, _make_teams(conn, tid, 8), 4)

        results = _run_in_parallel(
            lambda c: tie_service.generate_group_ties(c, tid),
            lambda c: tie_service.generate_group_ties(c, tid),
        )
        ok = [value for status, value in results if status == "ok"]
        err = [value for status, value in results if status == "err"]

        assert len(ok) == 1, [str(e) for e in err]
        assert len(err) == 1
        assert isinstance(err[0], tie_service.TeamTieError), repr(err[0])
        assert err[0].code == 409
        assert not isinstance(err[0], sqlite3.Error), repr(err[0])
        assert ok[0]["ties_generated"] == 12

        # 数据库最终恰好一套：12 条，两两不重复，round/match_index 结构完整
        ties = repo.list_team_ties(conn, tid)
        assert len(ties) == 12
        pairs = [frozenset((t["entry_a_id"], t["entry_b_id"])) for t in ties]
        assert len(set(pairs)) == 12
        by_group: dict[int, int] = {}
        for tie in ties:
            by_group[tie["group_id"]] = by_group.get(tie["group_id"], 0) + 1
        assert sorted(by_group.values()) == [6, 6]
        if "不能重复生成" in str(err[0]):
            duplicate_path_seen += 1
    # 至少有一轮真的走到了"后提交者看到前者已提交结果"这条路径上（否则说明并发压力不够）
    assert duplicate_path_seen >= 1, "并发用例没有覆盖 read-check-write 竞态路径"


def test_write_lock_contention_reports_readable_conflict(conn):
    """另一个连接持有写锁时返回可读 409，而不是把 SQLite 锁错误漏成 500。"""
    tid = _team_tournament(conn, players=4)
    _group_all(conn, tid, _make_teams(conn, tid, 4), 4)

    blocker = db_module.connect()
    other = sqlite3.connect(str(db_module._db_path()), timeout=0.2, check_same_thread=False)
    other.row_factory = sqlite3.Row
    other.execute("PRAGMA foreign_keys = ON")
    try:
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute("UPDATE team_ties SET round = round")
        with pytest.raises(tie_service.TeamTieError) as excinfo:
            tie_service.generate_group_ties(other, tid)
        assert excinfo.value.code == 409
        assert "正在被另一个请求生成" in str(excinfo.value)
    finally:
        blocker.rollback()
        blocker.close()
        other.close()

    # 锁释放后照常可以生成
    assert tie_service.generate_group_ties(conn, tid)["ties_generated"] == 6
    assert len(repo.list_team_ties(conn, tid)) == 6


# ------------------------------------------------------------------ 不推进赛事阶段

def test_generation_does_not_touch_tournament_stage_or_roster_flag(conn):
    """TEAM 阶段推进规则未冻结：本操作只生成 TeamTie，不改 stage / roster_confirmed。"""
    tid = _team_tournament(conn, players=4)
    _group_all(conn, tid, _make_teams(conn, tid, 4), 4)
    before = repo.get_tournament(conn, tid)
    assert before["stage"] == "REGISTRATION"

    tie_service.generate_group_ties(conn, tid)

    after = repo.get_tournament(conn, tid)
    assert after["stage"] == before["stage"]
    assert after["roster_confirmed"] == before["roster_confirmed"]
    # 团体赛永远不进入个人赛引擎
    assert repo.list_matches(conn, tid) == []


# ------------------------------------------------------------------ 与既有 Runtime 的兼容

def test_generated_tie_continues_into_production_runtime(conn):
    """自动生成的对抗必须与手工 `create_team_tie` 得到的运行态完全兼容。"""
    # 生产赛制包含双打盘，因此每队至少准备 2 名不同队员。
    tid = _team_tournament(conn, players=8)
    teams = _make_teams(conn, tid, 4, size=2)
    group = _group_all(conn, tid, teams, 4)[0]
    tie_service.generate_group_ties(conn, tid)

    auto_tie = repo.list_group_team_ties(conn, tid, group["id"])[0]
    tie_id = auto_tie["id"]

    # ① 生产赛制建盘（LOCAL_CLASSIC_5_V1 = 5 盘、先赢 3 盘）
    built = tie_service.build_rubber_skeleton(conn, tid, tie_id, FORMAT_CODE)
    assert built["format_code"] == FORMAT_CODE
    assert built["format_version"] == 1
    assert len(built["rubbers"]) == 5
    assert [r["status"] for r in built["rubbers"]] == ["PENDING"] * 5

    # ② 进入 Runtime：阵容 → start → 录分（不需要打完 5 盘）
    view = runtime.runtime_view(conn, tid, tie_id)
    assert view["group_id"] == group["id"]
    assert view["stage"] == MatchStage.GROUP.value
    assert view["target_wins"] == 3
    home_ids = [m["player_id"] for m in view["home_team"]["members"]]
    away_ids = [m["player_id"] for m in view["away_team"]["members"]]

    first = view["rubbers"][0]
    runtime.set_lineup(conn, tid, tie_id, first["id"], home_ids[:1], away_ids[:1])
    started = runtime.start_rubber(conn, tid, tie_id, first["id"])
    assert started["status"] == "PLAYING"
    assert [r["status"] for r in started["rubbers"]][0] == "PLAYING"

    scored = runtime.record_rubber_score(conn, tid, tie_id, first["id"], 2, 0)
    assert (scored["home_score"], scored["away_score"]) == (1, 0)
    assert scored["rubbers"][0]["status"] == "FINISHED"
    assert scored["rubbers"][0]["winner_entry_id"] == auto_tie["entry_a_id"]
    # 一盘不是一场 Match：整个闭环里没有产生任何普通比赛
    assert repo.list_matches(conn, tid) == []


# ------------------------------------------------------------------ API 层

def _api_team_tournament(client, *, players: int, group_count: int = 1) -> tuple[int, list[int]]:
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "团体小组循环 API",
            "date": "2026-08-01",
            "table_count": 4,
            "group_count": group_count,
            "qualify_per_group": 1,
            "event_type": "TEAM",
            "operation_mode": "DEMO",
        },
    ).json()["id"]
    ids = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, players + 1)
    ]
    return tid, ids


def _api_group_teams(client, tid: int, group_count: int, per_group: int) -> list[dict]:
    """按"每队 1 人"建队，然后按自动分组结果把队伍真正分到组里（不依赖自动分组顺序）。

    返回 [{"id": group_id, "name": group_name, "teams": [entry_id, ...]}, ...]。
    自动分组对"每队 1 人"的 TEAM 赛事会把每支队伍分到不同组，因此这里先建队再自动分组，
    然后用**直接改库**的方式把队伍放进指定的组（编排的正确性由服务层用例逐场校验，
    API 用例只验证接口契约）。
    """
    players = client.get(f"/api/tournaments/{tid}/players").json()
    team_of_player: dict[int, int] = {}
    for index in range(group_count * per_group):
        resp = client.post(
            f"/api/tournaments/{tid}/teams",
            json={"display_name": f"{index + 1}队", "member_ids": [players[index]["id"]]},
        )
        assert resp.status_code == 201, resp.text
        team_of_player[players[index]["id"]] = resp.json()["id"]

    grouped = client.post(f"/api/tournaments/{tid}/auto-group")
    assert grouped.status_code == 200, grouped.text
    payload = grouped.json()["groups"]
    assert len(payload) == group_count

    conn = db_module.connect()
    try:
        result = []
        for group in payload:
            members = [team_of_player[p["id"]] for p in group["players"]]
            for entry_id in members:
                repo.set_entry_group(conn, entry_id, group["id"])
            conn.commit()
            result.append({"id": group["id"], "name": group["name"], "teams": sorted(members)})
        return result
    finally:
        conn.close()


def test_api_generates_group_ties_and_rejects_second_call(client):
    tid, _ = _api_team_tournament(client, players=4)
    groups = _api_group_teams(client, tid, group_count=1, per_group=4)

    first = client.post(GENERATE_URL.format(tid=tid))
    assert first.status_code == 200, first.text
    assert first.json() == {"ties_generated": 6, "per_group": {groups[0]["name"]: 6}}

    listed = client.get(f"/api/tournaments/{tid}/team-ties").json()
    assert len(listed) == 6
    assert {t["group_id"] for t in listed} == {groups[0]["id"]}
    assert {t["stage"] for t in listed} == {"GROUP"}
    assert {t["status"] for t in listed} == {"WAITING"}
    # 每一场都必须是该组两支真实队伍之间的对抗（API 契约层也要挡住跨组/自打）
    for tie in listed:
        assert tie["entry_a_id"] != tie["entry_b_id"]
        assert {tie["entry_a_id"], tie["entry_b_id"]} <= set(groups[0]["teams"])
    assert {tie["round"] for tie in listed} == {1, 2, 3}
    for round_num in (1, 2, 3):
        indexes = [t["match_index"] for t in listed if t["round"] == round_num]
        assert sorted(indexes) == [1, 2]

    second = client.post(GENERATE_URL.format(tid=tid))
    assert second.status_code == 409
    assert "不能重复生成" in second.json()["detail"]
    assert len(client.get(f"/api/tournaments/{tid}/team-ties").json()) == 6
    # 赛事阶段没有被本接口偷偷推进
    assert client.get(f"/api/tournaments/{tid}").json()["stage"] == "REGISTRATION"


def test_api_rejects_ungrouped_team_without_partial_schedule(client):
    tid, _ = _api_team_tournament(client, players=4)
    _api_group_teams(client, tid, group_count=1, per_group=4)
    # 清空全部分组（走真实接口），模拟"还没分完组就点生成"
    assert client.post(f"/api/tournaments/{tid}/ungroup").status_code == 204

    resp = client.post(GENERATE_URL.format(tid=tid))
    assert resp.status_code == 409
    assert "请先完成分组" in resp.json()["detail"]
    assert client.get(f"/api/tournaments/{tid}/team-ties").json() == []


def test_api_rejects_singles_tournament_and_missing_tournament(client):
    singles = client.post(
        "/api/tournaments",
        json={
            "name": "单打赛",
            "date": "2026-08-01",
            "table_count": 4,
            "group_count": 1,
            "qualify_per_group": 1,
            "event_type": "SINGLES",
        },
    ).json()["id"]
    resp = client.post(GENERATE_URL.format(tid=singles))
    assert resp.status_code == 409
    assert "TEAM" in resp.json()["detail"]

    assert client.post(GENERATE_URL.format(tid=999999)).status_code == 404
