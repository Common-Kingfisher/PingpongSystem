"""A6.4 团体淘汰签（Team Knockout Bracket）。

规则源：`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`。本文件覆盖任务书要求的四类用例：

1. **Case 1 生成 8 队签**：4 场 Quarter Final、2 场 Semi Final、1 场 Final；
2. **Case 2 重复生成**：409，且不补齐、不覆盖、数量不翻倍；
3. **Case 3 未确认 Qualification**：禁止生成（409），且不落任何对抗；
4. **Case 4 确定性**：相同输入 → 输出完全一致（无随机、不按 id 排序）。

另外覆盖：签表来源只认 A6.3 确认结果（不猜晋级者）；跨组交叉对阵正确；
后续轮次槽位为空（由上游胜者产生）；复用 `team_ties`（`stage='KNOCKOUT'`、
`group_id` 为 NULL）、**不创建任何普通 Match**；非 TEAM / 赛事不存在；
已退赛队伍被拒绝；2 组 × 2 队的 4 签；以及 A6.1 → A6.2 → A6.3 → A6.4 端到端。

刻意**不**在这里测试（A6.4 范围外）：Scheduler / 自动排台 / ETA、
实时运行态 UI、高级种子算法（rating / 历史积分 / 跨赛事排名）、自动处理并列晋级。
"""

import pytest

from app import repository as repo
from app.models import EventType, MatchStage
from app.services import team_knockout as knockout_service
from app.services import team_qualification as qual_service
from app.services import team_runtime as runtime
from app.services import team_standings as standings_service
from app.services import team_ties as tie_service
from app.services import teams as teams_service

FORMAT_CODE = "LOCAL_CLASSIC_5_V1"
GENERATE_TIES_URL = "/api/tournaments/{tid}/team-ties/generate-group-ties"
CONFIRM_URL = "/api/tournaments/{tid}/qualification/confirm"
GENERATE_KO_URL = "/api/tournaments/{tid}/team-knockout/generate"
GET_KO_URL = "/api/tournaments/{tid}/team-knockout"


# ------------------------------------------------------------------ 夹具

def _team_tournament(
    conn, *, teams: int, group_count: int, per_group: int | tuple[int, ...], name: str,
    qualify_per_group: int = 2,
) -> int:
    """建 TEAM 赛事。

    `per_group` 可以传整数（各组等人数）或元组（各组不等人数，例如 `(3, 4)`）——
    后者用于构造"某组 3 队全并列、另一组名次唯一"的种子歧义场景。
    """
    tournament = repo.create_tournament(
        conn, name, "2026-11-01", 4, group_count, qualify_per_group,
        event_type=EventType.TEAM.value, operation_mode="DEMO",
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 4)
    for index in range(1, teams * 4 + 1):
        repo.add_player(conn, tid, f"选手{index:03d}", "计算机学院", 1000 + index)
    conn.commit()
    for index in range(teams):
        members = [p["id"] for p in repo.list_players(conn, tid)[index * 4 : (index + 1) * 4]]
        teams_service.create_team_entry(conn, tid, f"T{index + 1:02d}", members)

    groups = [repo.create_group(conn, tid, f"第{chr(ord('A') + i)}组", i) for i in range(group_count)]
    entries = sorted(
        repo.list_entries_by_type(conn, tid, EventType.TEAM.value), key=lambda e: e["id"]
    )
    if isinstance(per_group, int):
        sizes = [per_group] * group_count
    else:
        sizes = list(per_group)
    assert sum(sizes) == teams, f"每组人数之和 {sum(sizes)} != 队伍数 {teams}"
    index = 0
    for group, size in zip(groups, sizes):
        for entry in entries[index : index + size]:
            repo.set_entry_group(conn, entry["id"], group["id"])
        index += size
    conn.commit()
    return tid


def _group_teams(conn, tid: int, group_id: int) -> list[int]:
    return sorted(
        e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value)
        if e["group_id"] == group_id
    )


def _finish_tie(conn, tid: int, tie_id: int, winner: int) -> None:
    """真打完一场对抗（3 盘 2:0，其余 SKIPPED）。"""
    tie = repo.get_team_tie(conn, tie_id)
    tie_service.build_rubber_skeleton(conn, tid, tie_id, FORMAT_CODE)
    home_won = winner == tie["entry_a_id"]
    for index in range(1, 4):
        view = runtime.runtime_view(conn, tid, tie_id)
        rubber = next(r for r in view["rubbers"] if r["sequence"] == index)
        need = 2 if rubber["rubber_type"] == "DOUBLES" else 1
        home_ids = [m["player_id"] for m in view["home_team"]["members"]][:need]
        away_ids = [m["player_id"] for m in view["away_team"]["members"]][:need]
        runtime.set_lineup(conn, tid, tie_id, rubber["id"], home_ids, away_ids)
        runtime.start_rubber(conn, tid, tie_id, rubber["id"])
        runtime.record_rubber_score(
            conn, tid, tie_id, rubber["id"], 2 if home_won else 0, 0 if home_won else 2
        )
        if repo.get_team_tie(conn, tie_id)["status"] == "FINISHED":
            break


def _finish_group(conn, tid: int, group_id: int, *, transitive: bool = True) -> None:
    """把某组全部对抗打完。

    `transitive=True`：计算顺序在前者通吃 → 组内名次唯一（无并列）。
    `transitive=False`：**第 1 名通吃其余三队，其余三队两两循环** →
        standings[0] 独自第 1 名，standings[1..3] 三项统计完全相同（并列 2–4 名）。
        用于构造"第 2 名（甚至第 1 名）不唯一"的种子歧义场景。
    """
    if transitive:
        for tie in repo.list_group_team_ties(conn, tid, group_id):
            a, b = tie["entry_a_id"], tie["entry_b_id"]
            _finish_tie(conn, tid, tie["id"], a if a < b else b)
        return

    members = _group_teams(conn, tid, group_id)
    assert len(members) == 4, "并列构造需要 4 支队伍（1 强 + 3 循环）"
    first, rest = members[0], members[1:]
    winners: dict[frozenset, int] = {frozenset((first, other)): first for other in rest}
    winners[frozenset((rest[0], rest[1]))] = rest[0]
    winners[frozenset((rest[1], rest[2]))] = rest[1]
    winners[frozenset((rest[0], rest[2]))] = rest[2]
    for tie in repo.list_group_team_ties(conn, tid, group_id):
        pair = frozenset((tie["entry_a_id"], tie["entry_b_id"]))
        _finish_tie(conn, tid, tie["id"], winners[pair])


def _finish_cycle_group(conn, tid: int, group_id: int, *, teams: int) -> None:
    """循环构造：`teams` 支队伍首尾相接循环（T1>T2>T3>…>T1），每场 3:0。

    每支队伍"赢一场 3:0、输一场 0:3"，因此整组**三项统计完全相同** →
    名次区间覆盖整组（例如 3 队 → 全部并列 1–3 名），用于构造种子歧义场景。
    """
    members = _group_teams(conn, tid, group_id)
    assert len(members) == teams
    winners: dict[frozenset, int] = {}
    for index in range(teams):
        winner = members[index]
        loser = members[(index + 1) % teams]
        winners[frozenset((winner, loser))] = winner
    for tie in repo.list_group_team_ties(conn, tid, group_id):
        pair = frozenset((tie["entry_a_id"], tie["entry_b_id"]))
        _finish_tie(conn, tid, tie["id"], winners[pair])


def _setup_confirmed(
    conn, *, teams: int, group_count: int, per_group: int, name: str,
    qualify_per_group: int = 2,
) -> tuple[int, list[dict], list[int]]:
    """端到端准备：建赛 → A6.1 生成小组赛 → 打完 → A6.3 确认晋级。

    返回 (tid, 小组列表, 已确认晋级队伍 id)（按系统结论确认，因此名次无并列）。
    """
    tid = _team_tournament(
        conn, teams=teams, group_count=group_count, per_group=per_group,
        name=name, qualify_per_group=qualify_per_group,
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    for group in groups:
        _finish_group(conn, tid, group["id"])

    state = qual_service.get_qualification(conn, tid)
    picks = [t for g in state["groups"] for t in g["auto_qualified_team_ids"]]
    qual_service.confirm_qualification(conn, tid, picks)
    return tid, groups, picks


def _knockout_ties(conn, tid: int) -> list[dict]:
    return [
        tie for tie in repo.list_team_ties(conn, tid)
        if tie["stage"] == MatchStage.KNOCKOUT.value
    ]


# ==================================================================== Case 1：8 队生成

def test_case1_eight_teams_generates_qf_sf_final(conn):
    """4 组 × 每组 4 队、每组前 2 → 8 支 → 4 QF + 2 SF + 1 Final。

    本版本建立**首轮 4 场**真实对抗；SF/Final 在读取时按签表几何补全为待定轮次
    （`match_count` 给出应有场次数、`matches` 为空）。
    """
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Case1 8 队"
    )
    assert len(picks) == 8

    payload = knockout_service.generate_team_knockout(conn, tid)
    assert payload["generated"] is True

    planned = [(r["round"], r["round_name"], r["match_count"], len(r["matches"])) for r in payload["rounds"]]
    assert planned == [
        (1, "Quarter Final", 4, 4),
        (2, "Semi Final", 2, 0),
        (3, "Final", 1, 0),
    ]
    # 已建立的对抗：4 场首轮
    assert len(payload["ties"]) == 4
    assert all(tie["round"] == 1 for tie in payload["ties"])

    first_round = payload["rounds"][0]["matches"]
    assert all(m["teams_decided"] and m["team_a"] and m["team_b"] for m in first_round)
    assert all(m["status"] == "WAITING" for m in first_round)

    # 首轮恰好覆盖全部 8 支已确认队伍，且每人只出现一次
    seeded = [t for m in first_round for t in (m["team_a"]["team_entry_id"], m["team_b"]["team_entry_id"])]
    assert sorted(seeded) == sorted(picks)

    # 跨组交叉：A1-B2、B1-A2、C1-D2、D1-C2
    g = [_group_teams(conn, tid, group["id"]) for group in groups]
    a1, a2 = g[0][0], g[0][1]
    b1, b2 = g[1][0], g[1][1]
    c1, c2 = g[2][0], g[2][1]
    d1, d2 = g[3][0], g[3][1]
    actual = [(m["team_a"]["team_entry_id"], m["team_b"]["team_entry_id"]) for m in first_round]
    assert actual == [(a1, b2), (b1, a2), (c1, d2), (d1, c2)]


def test_case1_knockout_reuses_team_ties_and_creates_no_match(conn):
    """淘汰签复用 `team_ties`（stage=KNOCKOUT、group_id=NULL），不创建任何普通 Match。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Case1 复用 TeamTie"
    )
    knockout_service.generate_team_knockout(conn, tid)

    ties = _knockout_ties(conn, tid)
    assert len(ties) == 4          # 只建立首轮（见 service docstring）
    assert all(tie["group_id"] is None for tie in ties)
    assert all(tie["round"] == 1 for tie in ties)
    assert all(tie["status"] == "WAITING" for tie in ties)
    assert all(tie["team_a_score"] == 0 and tie["team_b_score"] == 0 for tie in ties)
    assert all(tie["winner_entry_id"] is None for tie in ties)
    # 未自动建盘：淘汰对抗的赛制仍为空（小组赛阶段的盘骨架不属于本批次）
    assert all(tie["format_code"] is None for tie in ties)
    knockout_tie_ids = {tie["id"] for tie in ties}
    assert [
        r for r in repo.list_tournament_team_rubbers(conn, tid)
        if r["team_tie_id"] in knockout_tie_ids
    ] == []
    # 一场普通比赛都没有创建
    assert repo.list_matches(conn, tid) == []
    # 小组赛对抗不受影响
    assert repo.count_team_ties(conn, tid, stage=MatchStage.GROUP.value) == 24  # 4 组 × 6 场


def test_case1_first_round_tie_can_start_runtime(conn):
    """淘汰赛的 TeamTie 与小组赛同构：可以按生产赛制建盘并进入 Runtime。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Case1 进入 Runtime"
    )
    knockout_service.generate_team_knockout(conn, tid)
    tie = _knockout_ties(conn, tid)[0]

    built = tie_service.build_rubber_skeleton(conn, tid, tie["id"], FORMAT_CODE)
    assert built["format_code"] == FORMAT_CODE
    assert len(built["rubbers"]) == 5

    view = runtime.runtime_view(conn, tid, tie["id"])
    assert view["stage"] == MatchStage.KNOCKOUT.value
    assert view["group_id"] is None
    assert view["target_wins"] == 3
    assert [r["status"] for r in view["rubbers"]] == ["PENDING"] * 5


def test_case1_two_groups_generate_four_team_bracket(conn):
    """2 组 × 每组 2 → 4 支 → 2 SF + 1 Final（建立 2 场首轮）。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=8, group_count=2, per_group=4, name="Case1 4 队"
    )
    payload = knockout_service.generate_team_knockout(conn, tid)
    assert [(r["round"], r["round_name"], r["match_count"]) for r in payload["rounds"]] == [
        (1, "Semi Final", 2),
        (2, "Final", 1),
    ]
    assert len(payload["ties"]) == 2

    g = [_group_teams(conn, tid, group["id"]) for group in groups]
    actual = [
        (m["team_a"]["team_entry_id"], m["team_b"]["team_entry_id"])
        for m in payload["rounds"][0]["matches"]
    ]
    assert actual == [(g[0][0], g[1][1]), (g[1][0], g[0][1])]


# ==================================================================== Case 2：重复生成

def test_case2_duplicate_generation_is_rejected(conn):
    """第二次生成 → 409，且对抗数量不翻倍、原有对抗不变。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Case2 重复生成"
    )
    first = knockout_service.generate_team_knockout(conn, tid)
    before = [
        (t["id"], t["round"], t["match_index"], t["entry_a_id"], t["entry_b_id"])
        for t in _knockout_ties(conn, tid)
    ]
    assert len(before) == 4

    with pytest.raises(knockout_service.ServiceError) as excinfo:
        knockout_service.generate_team_knockout(conn, tid)
    assert excinfo.value.code == 409
    assert "不能重复生成" in str(excinfo.value)

    after = [
        (t["id"], t["round"], t["match_index"], t["entry_a_id"], t["entry_b_id"])
        for t in _knockout_ties(conn, tid)
    ]
    assert after == before
    assert len(after) == 4
    assert first["generated"] is True


# ==================================================================== Case 3：未确认晋级

def test_case3_generation_requires_confirmed_qualification(conn):
    """未确认晋级 → 409，且一条淘汰对抗都不落库。"""
    tid = _team_tournament(
        conn, teams=16, group_count=4, per_group=4, name="Case3 未确认", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid)
    for group in repo.list_groups(conn, tid):
        _finish_group(conn, tid, group["id"])

    # 小组已打完、晋级可自动确认，但**尚未确认**
    state = qual_service.get_qualification(conn, tid)
    assert state["can_confirm"] is True
    assert state["confirmed"] == []

    with pytest.raises(knockout_service.ServiceError) as excinfo:
        knockout_service.generate_team_knockout(conn, tid)
    assert excinfo.value.code == 409
    assert "尚未确认" in str(excinfo.value)
    assert _knockout_ties(conn, tid) == []

    # 确认之后可以生成
    picks = [t for g in state["groups"] for t in g["auto_qualified_team_ids"]]
    qual_service.confirm_qualification(conn, tid, picks)
    assert knockout_service.generate_team_knockout(conn, tid)["generated"] is True


def test_case3_provisional_group_blocks_generation(conn):
    """小组未打完（provisional）→ 既不能确认，也不能生成淘汰签。"""
    tid = _team_tournament(
        conn, teams=16, group_count=4, per_group=4, name="Case3 provisional", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    _finish_group(conn, tid, groups[0]["id"])  # 只打完 A 组

    with pytest.raises(knockout_service.ServiceError) as excinfo:
        knockout_service.generate_team_knockout(conn, tid)
    assert excinfo.value.code == 409
    assert _knockout_ties(conn, tid) == []


# ==================================================================== Case 4：确定性

def test_case4_same_input_gives_identical_bracket(conn):
    """相同输入 → 输出完全一致（两次独立生成，逐场比对）。"""
    tid_a, _, _ = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Case4 确定性 A"
    )
    tid_b = _team_tournament(
        conn, teams=16, group_count=4, per_group=4, name="Case4 确定性 B", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid_b)
    for group in repo.list_groups(conn, tid_b):
        _finish_group(conn, tid_b, group["id"])

    # 两个赛事的"组内计算顺序"结构完全一致，因此晋级结构也一致；
    # 逐场比较"第几轮第几场由哪个组第几名出战"这一抽象形态。
    def shape(conn, tid: int) -> list[tuple[int, int, int | None, int | None]]:
        groups = repo.list_groups(conn, tid)
        rank_of: dict[int, int] = {}
        group_of: dict[int, int] = {}
        for gi, group in enumerate(groups):
            for ri, team_id in enumerate(_group_teams(conn, tid, group["id"]), start=1):
                rank_of[team_id] = ri
                group_of[team_id] = gi
        ties = sorted(_knockout_ties(conn, tid), key=lambda t: (t["round"], t["match_index"]))
        return [
            (
                t["round"],
                t["match_index"],
                None if t["entry_a_id"] is None else rank_of[t["entry_a_id"]],
                None if t["entry_b_id"] is None else rank_of[t["entry_b_id"]],
            )
            for t in ties
        ]

    assert shape(conn, tid_a) == shape(conn, tid_b)

    # 同一个赛事重复查询也完全一致
    first = knockout_service.get_team_knockout(conn, tid_a)
    second = knockout_service.get_team_knockout(conn, tid_a)
    assert first == second

    # 域层纯函数：同输入同输出
    from app.domain.team_knockout import build_team_bracket

    assert build_team_bracket([[1, 2], [3, 4], [5, 6], [7, 8]]) == build_team_bracket(
        [[1, 2], [3, 4], [5, 6], [7, 8]]
    )


# ==================================================================== 其它守卫

def test_generation_uses_only_confirmed_teams(conn):
    """签表来源只认 A6.3 的确认结果：首轮队伍恰好是已确认晋级的那批。

    同时验证"旧确认被全量替换后，签表跟着新确认走"（未确认的队伍绝不进签表）。
    """
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="只认确认结果"
    )
    # 重新确认：**同一批队伍**但换一个提交顺序 → 签表必须完全一致
    qual_service.confirm_qualification(conn, tid, list(reversed(picks)))
    payload = knockout_service.generate_team_knockout(conn, tid)

    first_round = payload["rounds"][0]["matches"]
    seeded = {m["team_a"]["team_entry_id"] for m in first_round} | {
        m["team_b"]["team_entry_id"] for m in first_round
    }
    assert seeded == set(picks)
    # 未确认的队伍一律不出现在签表里
    all_teams = {
        e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value)
    }
    assert all_teams - set(picks) != set()
    assert seeded.isdisjoint(all_teams - set(picks))
    # 跨组交叉仍然成立（与确认的提交顺序无关）
    g = [_group_teams(conn, tid, group["id"]) for group in groups]
    assert [
        (m["team_a"]["team_entry_id"], m["team_b"]["team_entry_id"]) for m in first_round
    ] == [(g[0][0], g[1][1]), (g[1][0], g[0][1]), (g[2][0], g[3][1]), (g[3][0], g[2][1])]


def test_withdrawn_confirmed_team_blocks_generation(conn):
    """已确认的队伍退赛后不能生成签表（不能安排已退赛队伍的新对抗）。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="退赛阻止生成"
    )
    repo.withdraw_entry(conn, picks[0], "主裁判", "伤病退赛")
    conn.commit()

    with pytest.raises(knockout_service.ServiceError) as excinfo:
        knockout_service.generate_team_knockout(conn, tid)
    assert excinfo.value.code == 409
    assert _knockout_ties(conn, tid) == []


def test_non_team_and_missing_tournament(conn):
    singles = repo.create_tournament(conn, "单打", "2026-11-01", 4, 1, 2, event_type="SINGLES")
    conn.commit()
    with pytest.raises(knockout_service.ServiceError) as wrong_event:
        knockout_service.get_team_knockout(conn, singles["id"])
    assert wrong_event.value.code == 409
    assert "TEAM" in str(wrong_event.value)

    with pytest.raises(knockout_service.ServiceError) as missing:
        knockout_service.generate_team_knockout(conn, 999999)
    assert missing.value.code == 404


def test_get_before_generation_returns_empty_bracket(conn):
    """未生成时查询返回空签表（generated=false），不是错误。"""
    tid = _team_tournament(conn, teams=8, group_count=2, per_group=4, name="未生成查询")
    payload = knockout_service.get_team_knockout(conn, tid)
    assert payload["generated"] is False
    assert payload["rounds"] == []
    assert payload["ties"] == []
    assert payload["tournament_id"] == tid


def test_domain_rejects_unfrozen_configurations():
    """域层拒绝未冻结的配置：非 2 的幂、每组晋级数 != 2、奇数组。"""
    from app.domain.team_knockout import TeamKnockoutError, build_first_round_pairs

    with pytest.raises(TeamKnockoutError) as odd_groups:
        build_first_round_pairs([[1, 2], [3, 4], [5, 6]])
    assert "偶数个小组" in str(odd_groups.value)

    with pytest.raises(TeamKnockoutError) as per_group:
        build_first_round_pairs([[1, 2, 3], [4, 5, 6]])
    assert "每组晋级 2 支" in str(per_group.value)

    with pytest.raises(TeamKnockoutError) as empty:
        build_first_round_pairs([])
    assert "没有已确认晋级" in str(empty.value)

    with pytest.raises(TeamKnockoutError) as dup:
        build_first_round_pairs([[1, 2], [2, 3]])
    assert "重复" in str(dup.value)


# ==================================================================== Reviewer issue 1：种子顺序

def _no_knockout_ties(conn, tid: int) -> bool:
    return repo.count_team_ties(conn, tid, stage=MatchStage.KNOCKOUT.value) == 0


def test_issue1_ambiguous_seed_order_rejects_generation_case_a(conn):
    """Reviewer issue 1 / Case A：**任一晋级名次不唯一**就必须拒绝生成（不创建任何对抗）。

    说明：Reviewer 给的"rank 1–2 并列"只是并列的一种形态。本测试用同一判据下
    **服务层可稳定构造**的形态覆盖同一条规则：第 1 名唯一、第 2–4 名并列。
    判据本身与并列发生在第 1 名还是第 2 名无关 —— 只要 `rank_start/rank_end`
    不能唯一确定某个晋级名次，生成就必须 409（见 `_qualified_by_group`）。

    第 1 名与第 2 名都并列的情形见
    `test_issue1_both_seed_ranks_ambiguous_guard_covers_all_rank_positions`
    （用规范化的 standings 事实直接驱动，不依赖"运行时能否造出完全相同的统计"）。
    """
    tid = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Issue1 CaseA",
        qualify_per_group=2,
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    # A 组：1 强 + 3 循环 → 第 1 名唯一、第 2–4 名并列；B 组名次唯一
    _finish_group(conn, tid, groups[0]["id"], transitive=False)
    _finish_group(conn, tid, groups[1]["id"])

    state = qual_service.get_qualification(conn, tid)
    tie_group = state["groups"][0]
    assert len(tie_group["auto_qualified_team_ids"]) == 1     # 第 1 名唯一
    assert len(tie_group["boundary_tied_team_ids"]) == 3      # 第 2–4 名并列
    assert tie_group["blocked_reasons"] == []                 # 候选充足，不是状态阻塞

    chosen = sorted(tie_group["boundary_tied_team_ids"])[0]
    picks = (
        list(tie_group["auto_qualified_team_ids"]) + [chosen]
        + list(state["groups"][1]["auto_qualified_team_ids"])
    )
    qual_service.confirm_qualification(conn, tid, picks)      # qualification 可以确认

    with pytest.raises(knockout_service.ServiceError) as excinfo:
        knockout_service.generate_team_knockout(conn, tid)
    assert excinfo.value.code == 409
    message = str(excinfo.value)
    assert "种子顺序仍存在并列" in message
    assert "第 2 名" in message          # 歧义位置正是第 2 名
    assert "不支持人工指定淘汰种子顺序" in message
    assert _no_knockout_ties(conn, tid), "被拒绝时不得留下任何淘汰对抗"


def test_issue1_both_seed_ranks_ambiguous_guard_covers_all_rank_positions(conn):
    """Reviewer issue 1 / Case A 的直接覆盖：**第 1 名与第 2 名都不唯一** → 409。

    运行时无法稳定构造"两支队伍三项统计完全相同"的小组（5 盘制提前结束会让局分不对称，
    2 队小组又必然分出胜负），因此这里直接给出 A6.2 形态的 standings 事实，
    验证判据对"并列发生在第 1 名"同样成立 —— 且**绝不用展示顺序 / entry id 兜底**。
    """
    from app.services import team_knockout as ko

    # 两支队伍并列 1–2（区间都是 1–2）：任何名次都无法唯一确定
    ambiguous_group = {
        "group_id": 7,
        "group_name": "A组",
        "qualify_count": 2,
        "provisional": False,
        "blocked_reasons": [],
        "candidates": [
            {"team_entry_id": 11}, {"team_entry_id": 12},
        ],
        "standings": [
            {"team_entry_id": 11, "rank_start": 1, "rank_end": 2,
             "eligible_for_qualification": True, "status": "ACTIVE"},
            {"team_entry_id": 12, "rank_start": 1, "rank_end": 2,
             "eligible_for_qualification": True, "status": "ACTIVE"},
        ],
    }
    with pytest.raises(knockout_service.ServiceError) as excinfo:
        ko._seed_order_for_group(ambiguous_group, confirmed_ids={11, 12})
    assert excinfo.value.code == 409
    assert "第 1 名" in str(excinfo.value) and "第 2 名" in str(excinfo.value)
    assert "不支持人工指定淘汰种子顺序" in str(excinfo.value)

    # 对照：同样的两支队伍但名次唯一 → 允许按名次返回 [rank1, rank2]
    unique_group = dict(
        ambiguous_group,
        standings=[
            {"team_entry_id": 11, "rank_start": 1, "rank_end": 1,
             "eligible_for_qualification": True, "status": "ACTIVE"},
            {"team_entry_id": 12, "rank_start": 2, "rank_end": 2,
             "eligible_for_qualification": True, "status": "ACTIVE"},
        ],
    )
    assert ko._seed_order_for_group(unique_group, confirmed_ids={11, 12}) == [11, 12]
    # 顺序来自名次，而不是传参顺序
    assert ko._seed_order_for_group(unique_group, confirmed_ids={12, 11}) == [11, 12]


def test_issue1_ambiguous_seed_order_rejects_generation_case_b(conn):
    """Reviewer issue 1 / Case B：`rank 1 唯一`、`rank 2-3 并列`，人工从并列块选一支晋级。

    虽然"谁晋级"已确认，但被选中那支的区间仍是 2–3，**第 2 种子不唯一** →
    knockout generate 409（不得静默把它当成 A2）。
    """
    tid = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Issue1 CaseB",
        qualify_per_group=2,
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    # A 组：1 强 + 3 循环 → 第 1 名唯一，第 2–4 名并列；B 组名次唯一
    _finish_group(conn, tid, groups[0]["id"], transitive=False)
    _finish_group(conn, tid, groups[1]["id"])

    state = qual_service.get_qualification(conn, tid)
    tie_group = state["groups"][0]
    assert tie_group["requires_manual_resolution"] is True
    assert len(tie_group["auto_qualified_team_ids"]) == 1     # 第 1 名唯一
    assert len(tie_group["boundary_tied_team_ids"]) == 3      # 第 2–4 名并列
    assert tie_group["boundary_slots_remaining"] == 1

    chosen = sorted(tie_group["boundary_tied_team_ids"])[0]
    picks = (
        list(tie_group["auto_qualified_team_ids"]) + [chosen]
        + list(state["groups"][1]["auto_qualified_team_ids"])
    )
    qual_service.confirm_qualification(conn, tid, picks)      # 人工裁定可以确认

    with pytest.raises(knockout_service.ServiceError) as excinfo:
        knockout_service.generate_team_knockout(conn, tid)
    assert excinfo.value.code == 409
    # 第 1 名是唯一的，因此报出的歧义位置正是第 2 名；不得静默把 chosen 当成 A2
    assert "第 2 名" in str(excinfo.value)
    assert "不支持人工指定淘汰种子顺序" in str(excinfo.value)
    assert _no_knockout_ties(conn, tid)


def test_issue1_rank_positions_map_span_ties(conn):
    """Reviewer issue 1 的机制回归：并列队伍的区间**覆盖多个名次位置**。

    `_qualified_by_group` 依据 A6.2 的 rank_start / rank_end 判断"该位置是否唯一"，
    而不再照抄确认结果的展示顺序。这条测试锁死该判断所依赖的事实：
    第 1 名只有 1 支队伍占位，第 2 名有 3 支并列队伍占位。
    """
    tid = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Issue1 位置映射",
        qualify_per_group=2,
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    _finish_group(conn, tid, groups[0]["id"], transitive=False)
    _finish_group(conn, tid, groups[1]["id"])

    payload = standings_service.get_team_group_standings(conn, tid, groups[0]["id"])
    rows = payload["standings"]
    assert [row["rank_start"] for row in rows] == [1, 2, 2, 2]
    assert [row["rank_end"] for row in rows] == [1, 4, 4, 4]

    # 第 1 个位置只有一支队伍；第 2 个位置有三支 → 第 2 名不唯一
    at_rank_1 = [row["team_entry_id"] for row in rows if row["rank_start"] <= 1 <= row["rank_end"]]
    at_rank_2 = [row["team_entry_id"] for row in rows if row["rank_start"] <= 2 <= row["rank_end"]]
    assert len(at_rank_1) == 1
    assert len(at_rank_2) == 3


def test_issue1_unique_rank_order_still_generates_normally_case_c(conn):
    """Reviewer issue 1 / Case C：名次完全唯一时正常生成，现有场景不回归。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Issue1 CaseC"
    )
    payload = knockout_service.generate_team_knockout(conn, tid)
    assert payload["generated"] is True
    assert len(payload["ties"]) == 4

    g = [_group_teams(conn, tid, group["id"]) for group in groups]
    actual = [
        (m["team_a"]["team_entry_id"], m["team_b"]["team_entry_id"])
        for m in payload["rounds"][0]["matches"]
    ]
    # 名次唯一（强者通吃）→ A1-B2, B1-A2, C1-D2, D1-C2
    assert actual == [(g[0][0], g[1][1]), (g[1][0], g[0][1]), (g[2][0], g[3][1]), (g[3][0], g[2][1])]


def test_issue1_confirmed_submission_order_does_not_decide_seeds(conn):
    """确认的**提交顺序 / 展示顺序**不得影响种子：以相反顺序确认，签表形态必须一致。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Issue1 顺序无关 A"
    )
    first = knockout_service.generate_team_knockout(conn, tid)

    tid2 = _team_tournament(
        conn, teams=16, group_count=4, per_group=4, name="Issue1 顺序无关 B",
        qualify_per_group=2,
    )
    tie_service.generate_group_ties(conn, tid2)
    for group in repo.list_groups(conn, tid2):
        _finish_group(conn, tid2, group["id"])
    state2 = qual_service.get_qualification(conn, tid2)
    picks2 = [t for g in state2["groups"] for t in g["auto_qualified_team_ids"]]
    qual_service.confirm_qualification(conn, tid2, list(reversed(picks2)))
    second = knockout_service.generate_team_knockout(conn, tid2)

    def shape(conn, tid: int, payload) -> list[tuple[int, int, int, int]]:
        """(A 组序, A 组内名次, B 组序, B 组内名次) —— 与绝对 id 无关的形态。"""
        groups = repo.list_groups(conn, tid)
        rank_of = {
            team_id: rank
            for group in groups
            for rank, team_id in enumerate(_group_teams(conn, tid, group["id"]), start=1)
        }
        group_of = {
            team_id: index
            for index, group in enumerate(groups)
            for team_id in _group_teams(conn, tid, group["id"])
        }
        return [
            (group_of[m["team_a"]["team_entry_id"]], rank_of[m["team_a"]["team_entry_id"]],
             group_of[m["team_b"]["team_entry_id"]], rank_of[m["team_b"]["team_entry_id"]])
            for m in payload["rounds"][0]["matches"]
        ]

    assert len(first["ties"]) == 4
    assert shape(conn, tid, first) == shape(conn, tid2, second)


# ==================================================================== Reviewer issue 3：场序

def test_issue3_knockout_match_index_is_one_based(conn):
    """Reviewer issue 3：淘汰签 `match_index` 必须从 **1** 开始（与 A6.1 一致）。

    直接调用 repository 会绕过 `create_team_tie` 的 `match_index >= 1` 守卫，
    因此这里显式锁死首场 == 1，而不是只断言"排序稳定"。
    """
    # 8 队 → 首轮 4 场 → [1, 2, 3, 4]
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Issue3 8 队"
    )
    payload = knockout_service.generate_team_knockout(conn, tid)
    indexes = [m["match_index"] for m in payload["rounds"][0]["matches"]]
    assert indexes == [1, 2, 3, 4]
    assert indexes[0] == 1
    stored = sorted(t["match_index"] for t in _knockout_ties(conn, tid))
    assert stored == [1, 2, 3, 4]
    assert all(index >= 1 for index in stored)

    # 4 队 → 首轮 2 场 → [1, 2]
    tid2, groups2, picks2 = _setup_confirmed(
        conn, teams=8, group_count=2, per_group=4, name="Issue3 4 队"
    )
    payload2 = knockout_service.generate_team_knockout(conn, tid2)
    assert [m["match_index"] for m in payload2["rounds"][0]["matches"]] == [1, 2]
    assert sorted(t["match_index"] for t in _knockout_ties(conn, tid2)) == [1, 2]


def test_issue3_match_index_matches_group_stage_convention(conn):
    """小组赛（A6.1）与淘汰赛的 `match_index` 口径一致：都是 1-based。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=16, group_count=4, per_group=4, name="Issue3 口径一致"
    )
    knockout_service.generate_team_knockout(conn, tid)
    group_indexes = {
        tie["match_index"]
        for tie in repo.list_team_ties(conn, tid)
        if tie["stage"] == MatchStage.GROUP.value
    }
    knockout_indexes = {
        tie["match_index"]
        for tie in repo.list_team_ties(conn, tid)
        if tie["stage"] == MatchStage.KNOCKOUT.value
    }
    assert min(group_indexes) == 1 and min(knockout_indexes) == 1
    assert 0 not in group_indexes and 0 not in knockout_indexes


# ==================================================================== 端到端 + API

def test_end_to_end_groups_to_bracket(conn):
    """A6.1 生成小组赛 → 打完 → A6.2 排名 → A6.3 确认 → A6.4 淘汰签。"""
    tid, groups, picks = _setup_confirmed(
        conn, teams=8, group_count=2, per_group=4, name="端到端"
    )
    payload = knockout_service.generate_team_knockout(conn, tid)

    assert payload["generated"] is True
    assert len(payload["ties"]) == 2           # 2 SF（Final 待上游胜者）
    assert len(repo.list_team_qualifications(conn, tid)) == 4
    assert repo.list_matches(conn, tid) == []  # 全程没有普通 Match
    # 小组赛 2 组 × 6 场 = 12 场，淘汰赛首轮 2 场
    assert repo.count_team_ties(conn, tid, stage=MatchStage.GROUP.value) == 12
    assert repo.count_team_ties(conn, tid, stage=MatchStage.KNOCKOUT.value) == 2
    assert [(r["round_name"], r["match_count"]) for r in payload["rounds"]] == [
        ("Semi Final", 2), ("Final", 1)
    ]
    # 赛事阶段没有被本批次偷偷推进（TEAM 阶段推进规则未冻结）
    assert repo.get_tournament(conn, tid)["stage"] == "REGISTRATION"


def _api_setup(client, *, teams: int, group_count: int, per_group: int) -> tuple[int, list[dict]]:
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "团体淘汰 API", "date": "2026-11-01", "table_count": 4,
            "group_count": group_count, "qualify_per_group": 2,
            "event_type": "TEAM", "operation_mode": "DEMO",
        },
    ).json()["id"]
    player_ids = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, teams * 4 + 1)
    ]
    for index in range(teams):
        resp = client.post(
            f"/api/tournaments/{tid}/teams",
            json={"display_name": f"T{index + 1:02d}",
                  "member_ids": player_ids[index * 4 : (index + 1) * 4]},
        )
        assert resp.status_code == 201, resp.text
    grouped = client.post(f"/api/tournaments/{tid}/auto-group")
    assert grouped.status_code == 200, grouped.text
    return tid, grouped.json()["groups"]


def test_api_generate_and_get_knockout(client):
    """API：未确认 → 409；确认后生成 → 200；重复生成 → 409；查询结构正确。"""
    from app import db as db_module

    tid, groups = _api_setup(client, teams=16, group_count=4, per_group=4)
    assert client.post(GENERATE_TIES_URL.format(tid=tid)).status_code == 200

    # 未确认 → 409
    resp = client.post(GENERATE_KO_URL.format(tid=tid))
    assert resp.status_code == 409
    assert "尚未确认" in resp.json()["detail"]

    # 打完 + 确认（API 不提供"打完"，用 service 层驱动 Runtime）
    conn = db_module.connect()
    try:
        for group in repo.list_groups(conn, tid):
            _finish_group(conn, tid, group["id"])
        state = qual_service.get_qualification(conn, tid)
        picks = [t for g in state["groups"] for t in g["auto_qualified_team_ids"]]
    finally:
        conn.close()
    assert client.post(CONFIRM_URL.format(tid=tid), json={"qualified_team_ids": picks}).status_code == 200

    generated = client.post(GENERATE_KO_URL.format(tid=tid))
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert set(body) == {"tournament_id", "generated", "rounds", "ties"}
    assert body["generated"] is True
    assert [(r["round"], r["round_name"], r["match_count"], len(r["matches"]))
            for r in body["rounds"]] == [
        (1, "Quarter Final", 4, 4),
        (2, "Semi Final", 2, 0),
        (3, "Final", 1, 0),
    ]
    assert len(body["ties"]) == 4
    match = body["ties"][0]
    assert set(match) == {
        "tie_id", "round", "round_name", "match_index", "teams_decided",
        "team_a", "team_b", "status", "team_a_score", "team_b_score", "winner_entry_id",
    }
    assert match["teams_decided"] is True
    assert set(match["team_a"]) == {"team_entry_id", "team_name"}
    assert set(body["rounds"][0]) == {"round", "round_name", "match_count", "matches"}

    # 重复生成 → 409
    again = client.post(GENERATE_KO_URL.format(tid=tid))
    assert again.status_code == 409
    assert "不能重复生成" in again.json()["detail"]

    # 查询与生成结果一致
    fetched = client.get(GET_KO_URL.format(tid=tid))
    assert fetched.status_code == 200
    assert fetched.json() == body

    # 错误路径
    assert client.get(GET_KO_URL.format(tid=999999)).status_code == 404
    singles = client.post(
        "/api/tournaments",
        json={"name": "单打", "date": "2026-11-01", "table_count": 4, "group_count": 1,
              "qualify_per_group": 2, "event_type": "SINGLES"},
    ).json()["id"]
    assert client.get(GET_KO_URL.format(tid=singles)).status_code == 409
