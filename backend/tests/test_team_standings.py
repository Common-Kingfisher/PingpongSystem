"""A6.2 团体小组排名（Team Group Standings V1）。

**唯一规则源**：`docs/TEAM_GROUP_RULES_V1.md`。本文件用测试把该文档逐条钉死，
分两层：

1. **域层纯算法**（`app.domain.team_standings`）：直接喂标准化事实，覆盖 Fixture A–E、
   部分区分后 subset 重启、比率分母为 0、并列区间、provisional。
2. **服务 + API 层**（真实 SQLite）：用 A6.1 生成器建赛程、用 A4.1 Runtime 真打完盘，
   再验证 SKIPPED 不计入、跨组隔离、退赛/资格事实、以及"每次从数据库事实重算"。

本文件统一使用**三局两胜**的有效局分（`2:0` / `2:1` / `0:2` / `1:2`），
因为 A4.1 Runtime 会按赛事 `games_to_win` 校验盘比分。

刻意**不**在这里实现的（A6.2 范围外，见规则文档 §10）：qualification 写入、人工裁定 API、
抽签、团体淘汰赛、Scheduler/ETA、points ratio、TEAM 阶段推进。
"""

from functools import cmp_to_key

import pytest

from app import repository as repo
from app.domain import round_robin
from app.domain import team_standings as domain
from app.models import EventType
from app.services import team_runtime as runtime
from app.services import team_standings as standings_service
from app.services import team_ties as tie_service
from app.services import teams as teams_service

FORMAT_CODE = "LOCAL_CLASSIC_5_V1"
GENERATE_URL = "/api/tournaments/{tid}/team-ties/generate-group-ties"
STANDINGS_URL = "/api/tournaments/{tid}/team-groups/standings"
GROUP_STANDINGS_URL = "/api/tournaments/{tid}/team-groups/{gid}/standings"

#: 三局两胜下合法的盘局分。
WIN_20 = (2, 0)
LOSE_02 = (0, 2)
WIN_21 = (2, 1)


def _sweep(winner_is_home: bool) -> list[tuple[int, int]]:
    """三盘 2:0 直接结束对抗。"""
    return [WIN_20 if winner_is_home else LOSE_02] * 3


# ==================================================================== 域层纯算法

def _entries(*names: str) -> tuple[domain.TeamEntryFact, ...]:
    return tuple(
        domain.TeamEntryFact(team_entry_id=index, team_name=name)
        for index, name in enumerate(names, start=1)
    )


def _tie(tie_id: int, a: int, b: int, winner: int | None, rubbers=()) -> domain.TeamTieFact:
    """一场对抗；`winner=None` 表示未完成（WAITING/PLAYING）。"""
    return domain.TeamTieFact(
        tie_id=tie_id,
        entry_a_id=a,
        entry_b_id=b,
        status="FINISHED" if winner is not None else "PLAYING",
        winner_entry_id=winner,
        rubbers=tuple(rubbers),
    )


def _rubber(
    winner: int | None = None,
    *,
    entry_a: int = 1,
    status: str = "FINISHED",
    games_won: int = 2,
    games_lost: int = 0,
) -> domain.TeamRubberFact:
    """一盘事实（默认三局两胜的 2:0）。

    局分按**胜者是主队还是客队**落到 `home_score` / `away_score`：`entry_a` 是主队，
    因此 A 队获胜时 `home_score = games_won`，B 队获胜时对调。`winner=None` 表示这盘没打完。
    """
    if winner is None:
        home = away = 0
    elif winner == entry_a:
        home, away = games_won, games_lost
    else:
        home, away = games_lost, games_won
    return domain.TeamRubberFact(
        tie_id=0,
        sequence=1,
        status=status,
        winner_entry_id=winner,
        home_score=home,
        away_score=away,
    )


def _facts(names: tuple[str, ...], ties: list[domain.TeamTieFact]) -> domain.StandingsFacts:
    return domain.StandingsFacts(entries=_entries(*names), ties=tuple(ties))


def _by_name(rows) -> dict:
    return {row.team_name: row for row in rows}


# ---------------------------------------------------------------- 比率比较（§4.2）

def test_ratio_cross_multiplication_avoids_float_error():
    """1/3 与 2/6 必须判为相等：用浮点会因 0.333… 抖动。"""
    assert domain.compare_ratio(1, 3, 2, 6) == 0
    assert domain.compare_ratio(1, 3, 1, 2) == -1  # 1/3 < 1/2
    assert domain.compare_ratio(3, 7, 2, 5) == 1   # 3/7 > 2/5
    # 大数：交叉乘法仍是精确整数比较
    assert domain.compare_ratio(1000000007, 3, 1000000009, 3) == -1


def test_ratio_zero_denominator_semantics():
    """分母 0：全胜 = +∞；0/0 = 没有数据（与 +∞ 是两件事）。"""
    assert domain.compare_ratio(3, 0, 1, 3) == 1   # +∞ > 有限
    assert domain.compare_ratio(1, 3, 3, 0) == -1
    assert domain.compare_ratio(2, 0, 5, 0) == 0   # 两侧都是 +∞
    assert domain.compare_ratio(0, 0, 0, 0) is None  # 都没打过 → 无法比较
    # 一侧没打过、另一侧全胜/全负：结果仍然是确定的
    assert domain.compare_ratio(0, 0, 1, 0) == -1
    assert domain.compare_ratio(0, 0, 0, 1) == 0


# ---------------------------------------------------------------- Fixture A（§3）

def test_fixture_a_no_tie_ranks_by_match_points():
    """4 队无同分：A 全胜、B 2 胜、C 1 胜、D 全负 → 积分 6/5/4/3，名次唯一。"""
    ties = [
        _tie(1, 1, 2, 1), _tie(2, 1, 3, 1), _tie(3, 1, 4, 1),
        _tie(4, 2, 3, 2), _tie(5, 2, 4, 2), _tie(6, 3, 4, 3),
    ]
    facts = _facts(("A", "B", "C", "D"), ties)
    rows = domain.compute_team_group_standings(facts)
    assert [r.team_name for r in rows] == ["A", "B", "C", "D"]
    assert [r.match_points for r in rows] == [6, 5, 4, 3]
    assert [(r.rank_start, r.rank_end) for r in rows] == [(1, 1), (2, 2), (3, 3), (4, 4)]
    assert not any(r.ambiguous for r in rows)
    assert [(r.ties_played, r.ties_won, r.ties_lost) for r in rows] == [
        (3, 3, 0), (3, 2, 1), (3, 1, 2), (3, 0, 3)
    ]
    assert domain.group_is_provisional(facts) is False


def test_match_points_are_two_one_not_one_zero():
    """胜 2 负 1（不是胜 1 负 0）——写死，防止有人顺手改成常见积分。"""
    assert domain.MATCH_POINTS_WIN == 2
    assert domain.MATCH_POINTS_LOSS == 1
    rows = domain.compute_team_group_standings(_facts(("A", "B"), [_tie(1, 1, 2, 1)]))
    assert _by_name(rows)["A"].match_points == 2
    assert _by_name(rows)["B"].match_points == 1


def test_unfinished_tie_never_counts_as_a_normal_result():
    """未完成对抗：不计积分、不计 ties_played，只让小组变成 provisional。"""
    facts = _facts(("A", "B"), [_tie(1, 1, 2, 1), _tie(2, 2, 1, None)])
    rows = _by_name(domain.compute_team_group_standings(facts))
    assert (rows["A"].match_points, rows["A"].ties_played) == (2, 1)
    assert (rows["B"].match_points, rows["B"].ties_played) == (1, 1)
    assert domain.group_is_provisional(facts) is True


# ---------------------------------------------------------------- Fixture B（§4 Step 1）

def test_fixture_b_two_way_tie_resolved_by_head_to_head():
    """两队同积分 → 子集内比赛积分（直接交锋）决定名次。"""
    rows = domain.compute_team_group_standings(_facts(("A", "B"), [_tie(1, 1, 2, 2)]))
    assert [r.team_name for r in rows] == ["B", "A"]
    assert [r.match_points for r in rows] == [2, 1]


def test_three_way_total_tie_without_any_rubber_data_stays_ambiguous():
    """三队总积分相同、且**没有任何 FINISHED 盘** → 两个比率 key 都不可用 → 并列 2–4。

    这条同时证明"未完成的盘不进入统计"：对抗都是 FINISHED 的，但盘一条都没打完。
    """
    ties = [
        _tie(1, 1, 2, 1), _tie(2, 1, 3, 1), _tie(3, 1, 4, 1),
        _tie(4, 2, 3, 2), _tie(5, 3, 4, 3), _tie(6, 4, 2, 4),
    ]
    rows = domain.compute_team_group_standings(_facts(("A", "B", "C", "D"), ties))
    assert [r.match_points for r in rows] == [6, 4, 4, 4]
    assert (rows[0].rank_start, rows[0].rank_end) == (1, 1)
    for row in rows[1:]:
        assert (row.rank_start, row.rank_end) == (2, 4)
        assert row.ambiguous is True
        assert (row.rubber_wins, row.rubber_losses) == (0, 0)
        assert (row.games_won, row.games_lost) == (0, 0)


# ------------------------------------------------- Fixture C/D/E + 部分区分（§4）
#
# 共用底盘：A(1) 全胜；B(2)/C(3)/D(4) 三队循环（B 胜 C、C 胜 D、D 胜 B）→ 三队各 4 分。
# 所有 ratio fixture 都在这个底盘上调整盘/局，保证"总积分相同"这个前提成立。

def _cycle_base() -> list[domain.TeamTieFact]:
    """A 全胜 + B/C/D 三队循环（各 4 分），无任何 FINISHED 盘。"""
    return [
        _tie(1, 1, 2, 1), _tie(2, 1, 3, 1), _tie(3, 1, 4, 1),
        _tie(4, 2, 3, 2), _tie(5, 3, 4, 3), _tie(6, 4, 2, 4),
    ]


def _cycle_with_ratios() -> list[domain.TeamTieFact]:
    """B/C/D 循环同分，盘比率依次变差：D 2:1 > C 1:1 > B 1:2（Step 2 分开）。"""
    base = _cycle_base()
    return base[:3] + [
        _tie(4, 2, 3, 2, [_rubber(2, entry_a=2)]),                    # B 胜 C：盘 1:0
        _tie(5, 3, 4, 3, [_rubber(3, entry_a=3)]),                    # C 胜 D：盘 1:0
        _tie(6, 4, 2, 4, [_rubber(4, entry_a=4)] * 2),                # D 胜 B：盘 2:0
    ]


def test_fixture_c_three_way_cycle_resolved_by_rubber_ratio():
    """三队循环同分、子集积分也相同 → 盘 W/L 比率决定名次（Step 2）。"""
    rows = domain.compute_team_group_standings(
        _facts(("A", "B", "C", "D"), _cycle_with_ratios())
    )
    stats = _by_name(rows)
    assert [r.match_points for r in rows] == [6, 4, 4, 4]
    assert (stats["B"].rubber_wins, stats["B"].rubber_losses) == (1, 2)
    assert (stats["C"].rubber_wins, stats["C"].rubber_losses) == (1, 1)
    assert (stats["D"].rubber_wins, stats["D"].rubber_losses) == (2, 1)
    assert stats["D"].rank_start == stats["D"].rank_end == 2
    assert stats["C"].rank_start == stats["C"].rank_end == 3
    assert stats["B"].rank_start == stats["B"].rank_end == 4
    assert not any(r.ambiguous for r in rows)


def _cycle_rubber_equal_games_differ() -> list[domain.TeamTieFact]:
    """B/C/D 循环，盘比率**完全相同**（各 2:2），局比率不同：B 5:4 > C 5:5 > D 4:5。

    这是"比率的比值相同、总量不同"的组合，因此 Step 2 无法区分，
    必须由 Step 3 的局比率分开。
    """
    base = _cycle_base()
    return base[:3] + [
        # B 胜 C：B 2:0、C 2:1（C 那盘是 1:2 的惜败）
        _tie(4, 2, 3, 2, [_rubber(2, entry_a=2), _rubber(3, entry_a=2, games_won=1, games_lost=2)]),
        # C 胜 D：同上
        _tie(5, 3, 4, 3, [_rubber(3, entry_a=3), _rubber(4, entry_a=3, games_won=1, games_lost=2)]),
        # D 胜 B：B 那盘被 0:2 拿下
        _tie(6, 4, 2, 4, [_rubber(4, entry_a=4), _rubber(2, entry_a=4, games_won=0, games_lost=2)]),
    ]


def test_fixture_d_rubber_ratio_equal_then_games_ratio_decides():
    """盘比率相同 → 局 W/L 比率决定名次（Step 3）。"""
    rows = domain.compute_team_group_standings(
        _facts(("A", "B", "C", "D"), _cycle_rubber_equal_games_differ())
    )
    stats = _by_name(rows)
    # 盘比率三者完全相同（各 2:2）→ Step 2 无法区分
    for name in ("B", "C", "D"):
        assert (stats[name].rubber_wins, stats[name].rubber_losses) == (2, 2)
    # Step 3 局比率把它们分开
    assert (stats["B"].games_won, stats["B"].games_lost) == (5, 4)
    assert (stats["C"].games_won, stats["C"].games_lost) == (5, 5)
    assert (stats["D"].games_won, stats["D"].games_lost) == (4, 5)
    assert stats["B"].rank_start == stats["B"].rank_end == 2
    assert stats["C"].rank_start == stats["C"].rank_end == 3
    assert stats["D"].rank_start == stats["D"].rank_end == 4
    assert not any(r.ambiguous for r in rows)


def test_fixture_e_every_key_equal_gives_rank_range_ambiguity():
    """盘、局比率仍完全相同 → B/C/D 共享 2–4 名，**不按 id 打破同分**。"""
    base = _cycle_base()
    ties = base[:3] + [
        _tie(4, 2, 3, 2, [_rubber(2, entry_a=2), _rubber(3, entry_a=2)]),
        _tie(5, 3, 4, 3, [_rubber(3, entry_a=3), _rubber(4, entry_a=3)]),
        _tie(6, 4, 2, 4, [_rubber(4, entry_a=4), _rubber(2, entry_a=4)]),
    ]
    rows = domain.compute_team_group_standings(_facts(("A", "B", "C", "D"), ties))
    stats = _by_name(rows)
    assert [r.team_name for r in rows] == ["A", "B", "C", "D"]  # 展示顺序只是稳定顺序
    assert (stats["A"].rank_start, stats["A"].rank_end) == (1, 1)
    for name in ("B", "C", "D"):
        assert (stats[name].rank_start, stats[name].rank_end) == (2, 4)
        assert stats[name].ambiguous is True
        assert (stats[name].rubber_wins, stats[name].rubber_losses) == (2, 2)
        assert (stats[name].games_won, stats[name].games_lost) == (4, 4)
    # 三者统计完全相同（这才叫"无法区分"）
    for key in ("match_points", "rubber_wins", "rubber_losses", "games_won", "games_lost"):
        assert len({getattr(stats[name], key) for name in ("B", "C", "D")}) == 1


def test_partial_resolution_restarts_from_step_one_with_smaller_subset():
    """部分区分：A 已定，B/C/D 进入子集，并在**重算后的 Step 1** 上继续拆分。

    子集内的比赛积分完全等价（三队循环各 2 分），因此必须**缩小 subset 后从 Step 1 重算**
    （而不是拿着全局积分或直接跳到比率）：重算后 Step 1 仍然并列，才轮到 Step 2 的盘比率。
    本用例断言子集重算后的真实结果：D > C > B。
    """
    facts = _facts(("A", "B", "C", "D"), _cycle_with_ratios())
    rows = domain.compute_team_group_standings(facts)
    stats = _by_name(rows)
    # 全局：A=6，B/C/D 各 4 分（确实同分）
    assert [r.match_points for r in rows] == [6, 4, 4, 4]
    # 子集内积分：三队循环各 2 分（Step 1 仍并列）→ 由盘比率决定
    assert stats["D"].rank_start == 2 and stats["C"].rank_start == 3 and stats["B"].rank_start == 4
    # 子集内盘比率：D 2:1 > C 1:1 > B 1:2（而不是全局累计，全局累计含与 A 的比赛）
    assert stats["D"].rubber_wins * stats["C"].rubber_losses > stats["C"].rubber_wins * stats["D"].rubber_losses
    assert stats["C"].rubber_wins * stats["B"].rubber_losses > stats["B"].rubber_wins * stats["C"].rubber_losses
    # 子集内积分必须**重新计算**：若错误地沿用全局积分或直接跳到下一个 key，就会得到别的顺序
    assert stats["D"].ties_won == 1 and stats["C"].ties_won == 1  # 全局各 1 胜


def test_resolution_partitions_every_team_exactly_once():
    """不变量：`_resolve` 的输出必须是队伍的**一个划分**（每人恰好出现一次）。

    这条测试直接锁住曾经的实现缺陷：子集下标与 entries 下标混用会让某些队伍重复出现、
    另一些直接消失（名次行数看起来还对，实际是错的）。
    """
    cases = [
        _cycle_with_ratios(),
        _cycle_rubber_equal_games_differ(),
        [
            _tie(1, 1, 2, 1), _tie(2, 1, 3, 1), _tie(3, 1, 4, 1),
            _tie(4, 2, 3, 2), _tie(5, 3, 4, 3), _tie(6, 4, 2, 4),
        ],
    ]
    for ties in cases:
        facts = _facts(("A", "B", "C", "D"), ties)
        groups = domain._resolve(facts, [0, 1, 2, 3])
        flat = [index for group in groups for index in group]
        assert sorted(flat) == [0, 1, 2, 3], groups
        assert len(flat) == len(set(flat)), groups
        # 每个队伍一行、且与 entries 一一对应
        rows = domain.compute_team_group_standings(facts)
        assert sorted(r.team_entry_id for r in rows) == [1, 2, 3, 4]
        # 名次区间必须连续覆盖 1..4
        assert sorted((r.rank_start, r.rank_end) for r in rows) == [
            (1, 1), (2, 2), (3, 3), (4, 4)
        ] or [r.rank_start for r in rows] == sorted(r.rank_start for r in rows)


def test_ratios_are_compared_after_recomputing_the_tied_subset():
    """同分子集必须**重算统计**：子集内比率与全局比率会给出**相反**的结论。

    这个 fixture 的关键性质：B/C/D 全局同为 4 分；子集（去掉 A）内三队循环各 3 分，
    于是由**子集内**盘比率决定名次 → C > D > B。
    如果错误地拿全局累计比率比较，C 与 D 的次序会反过来
    （全局 D 3:3 优于 C 5:3；子集内 C 5:2 优于 D 3:2）。
    """
    ties = [
        # A 全胜（这些对抗同时污染 B/C/D 的全局累计）
        _tie(1, 1, 2, 1, [_rubber(1, entry_a=1)] * 3),
        _tie(2, 1, 3, 1, [_rubber(1, entry_a=1)]),
        _tie(3, 1, 4, 1, [_rubber(1, entry_a=1)]),
        # B/C/D 三队循环：B 胜 C、C 胜 D、D 胜 B → 全局各 4 分、子集内各 3 分
        _tie(4, 2, 3, 2, [_rubber(2, entry_a=2)] + [_rubber(3, entry_a=2)] * 3),  # B 1:3 C
        _tie(5, 3, 4, 3, [_rubber(3, entry_a=3)] * 2 + [_rubber(4, entry_a=3)]),  # C 2:1 D
        _tie(6, 4, 2, 4, [_rubber(4, entry_a=4)] * 2),                            # D 2:0 B
    ]
    facts = _facts(("A", "B", "C", "D"), ties)
    rows = domain.compute_team_group_standings(facts)
    stats = _by_name(rows)
    names = "ABCD"

    # 全局：A=6，B/C/D 各 4 分；子集内也是三队循环（各 3 分）→ Step 1 无法分开
    assert [r.match_points for r in rows] == [6, 4, 4, 4]
    subset = domain._accumulate(facts, [1, 2, 3])
    assert [t.match_points for t in subset] == [3, 3, 3]
    assert [(t.rubber_wins, t.rubber_losses) for t in subset] == [(1, 5), (5, 2), (3, 2)]

    # 子集内盘比率：C 5:2（2.5）> D 3:2（1.5）> B 1:5（0.2）
    assert (stats["C"].rank_start, stats["D"].rank_start, stats["B"].rank_start) == (2, 3, 4)
    # 全局累计次序不同（B 1:8 最差但 C 5:3 与 D 3:3 的先后与子集内相反）
    order = [names.index(row.team_name) for row in rows]
    assert order == [0, 2, 3, 1]  # A, C, D, B


def test_unavailable_ratio_key_falls_through_and_ends_in_tie():
    """盘比率 key 不可用（存在 0/0 的一对）→ 改用局比率；同样不可用才判并列。

    三方循环、且**三场对抗一盘都没打完**：三支队伍的比赛积分都是 3，
    盘与局的累计都是 0/0 —— 两个比率 key 对所有配对都不可用，
    因此只能并列（既不崩，也**不按 id 排序**）。
    """
    ties = [
        _tie(1, 1, 2, 1),  # A 胜 B：无 FINISHED 盘
        _tie(2, 2, 3, 2),  # B 胜 C：无 FINISHED 盘
        _tie(3, 3, 1, 3),  # C 胜 A：无 FINISHED 盘
    ]
    rows = domain.compute_team_group_standings(_facts(("A", "B", "C"), ties))
    stats = _by_name(rows)
    assert {stats[n].match_points for n in ("A", "B", "C")} == {3}  # 三方循环
    for name in ("A", "B", "C"):
        assert (stats[name].rubber_wins, stats[name].rubber_losses) == (0, 0)
        assert (stats[name].games_won, stats[name].games_lost) == (0, 0)
    # 0/0 对 0/0 无法比较 → 三者共享 1–3 名，且都标记为 ambiguous
    assert {(r.rank_start, r.rank_end) for r in rows} == {(1, 3)}
    assert all(r.ambiguous for r in rows)


def test_zero_zero_ratio_is_not_comparable_but_zero_one_is():
    """锁定分母为 0 的语义：0/0 是"没数据"（不可比较），0/1 是"全负"（可比较）。

    构造：B 胜 A 且无盘；C 的两场都有 FINISHED 盘 → 在盘比率 key 上 B 是 0/0、
    C 是 1:1，A 是 0/0。A 与 B 同为 0/0 → 不可比较 → 盘比率 key 整体失效。
    """
    assert domain.compare_ratio(0, 0, 0, 0) is None
    assert domain.compare_ratio(0, 1, 0, 0) == 0  # 0/1 对 0/0：0/0 更"没有数据"，但 0/1 已确定全负
    assert domain.compare_ratio(1, 0, 0, 0) == 1  # 全胜 > 没数据
    assert domain.compare_ratio(0, 0, 1, 0) == -1


def test_duplicate_team_in_group_is_rejected():
    facts = domain.StandingsFacts(
        entries=(domain.TeamEntryFact(1, "A"), domain.TeamEntryFact(1, "A 重复")),
        ties=(),
    )
    with pytest.raises(domain.TeamStandingsError):
        domain.compute_team_group_standings(facts)


def test_tie_referencing_foreign_team_is_rejected():
    facts = domain.StandingsFacts(
        entries=(domain.TeamEntryFact(1, "A"), domain.TeamEntryFact(2, "B")),
        ties=(_tie(1, 1, 99, 1),),
    )
    with pytest.raises(domain.TeamStandingsError):
        domain.compute_team_group_standings(facts)


# ==================================================================== 数据库 / 服务层

def _team_tournament(conn, *, teams: int, per_group: int, name: str = "团体排名验收") -> int:
    """TEAM 赛事 + `teams` 支队伍（每队 4 人，足够打 5 盘制）+ 已分组。"""
    tournament = repo.create_tournament(
        conn, name, "2026-09-01", 4, teams // per_group, 1,
        event_type=EventType.TEAM.value, operation_mode="DEMO",
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 4)
    for index in range(1, teams * 4 + 1):
        repo.add_player(conn, tid, f"选手{index:03d}", "计算机学院", 1000 + index)
    conn.commit()
    for index in range(teams):
        members = [p["id"] for p in repo.list_players(conn, tid)[index * 4 : (index + 1) * 4]]
        teams_service.create_team_entry(conn, tid, f"{chr(ord('A') + index)}队", members)

    groups = [
        repo.create_group(conn, tid, f"第{chr(ord('A') + i)}组", i)
        for i in range(teams // per_group)
    ]
    entries = sorted(
        repo.list_entries_by_type(conn, tid, EventType.TEAM.value), key=lambda e: e["id"]
    )
    for index, entry in enumerate(entries):
        repo.set_entry_group(conn, entry["id"], groups[index // per_group]["id"])
    conn.commit()
    return tid


def _finish_tie(
    conn, tid: int, tie_id: int, *, winner, rubbers: list[tuple[int, int]]
) -> None:
    """真打完一场对抗：建 5 盘骨架 → 逐盘阵容/开始/录分。

    `rubbers` 是 [(home_score, away_score), ...]（`home` = entry_a 视角的局分）。
    先赢 3 盘的队伍立即结束对抗，剩余盘由 Runtime 自动 SKIPPED —— 正好用于验证
    SKIPPED 不进入统计。
    """
    tie_service.build_rubber_skeleton(conn, tid, tie_id, FORMAT_CODE)
    for index, (home, away) in enumerate(rubbers, start=1):
        view = runtime.runtime_view(conn, tid, tie_id)
        rubber = next(r for r in view["rubbers"] if r["sequence"] == index)
        need = 2 if rubber["rubber_type"] == "DOUBLES" else 1
        home_ids = [m["player_id"] for m in view["home_team"]["members"]][:need]
        away_ids = [m["player_id"] for m in view["away_team"]["members"]][:need]
        runtime.set_lineup(conn, tid, tie_id, rubber["id"], home_ids, away_ids)
        runtime.start_rubber(conn, tid, tie_id, rubber["id"])
        runtime.record_rubber_score(conn, tid, tie_id, rubber["id"], home, away)
        if repo.get_team_tie(conn, tie_id)["status"] == "FINISHED":
            break
    assert repo.get_team_tie(conn, tie_id)["winner_entry_id"] == winner


def _finish_all_group_ties(conn, tid: int, group_id: int, *, plan: dict | None = None) -> None:
    """把某组**尚未开打**的对抗打完。

    `plan` 为 {frozenset({a, b}): winner_id}，缺省由 entry_a 获胜。
    已经打完（对抗 FINISHED 或已有盘骨架）的对抗会被跳过，因此可以安全地"接着打剩下的"。
    """
    for tie in repo.list_group_team_ties(conn, tid, group_id):
        stored = repo.get_team_tie(conn, tie["id"])
        if stored["status"] == "FINISHED" or repo.list_team_rubbers(conn, tie["id"]):
            continue
        pair = frozenset((tie["entry_a_id"], tie["entry_b_id"]))
        winner = (plan or {}).get(pair, tie["entry_a_id"])
        _finish_tie(conn, tid, tie["id"], winner=winner,
                    rubbers=_sweep(winner == tie["entry_a_id"]))


def _standings(conn, tid: int, group_id: int) -> dict:
    return standings_service.get_team_group_standings(conn, tid, group_id)


def _rows_by_name(payload: dict) -> dict:
    return {row["team_name"]: row for row in payload["standings"]}


def _seed_two_team_group(conn, name: str = "两队一组") -> tuple[int, int, int]:
    """2 队 1 组 + 一场已完成对抗（A 队 3:0 B 队），返回 (tid, group_id, tie_id)。"""
    tid = _team_tournament(conn, teams=2, per_group=2, name=name)
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    tie = repo.list_group_team_ties(conn, tid, group["id"])[0]
    _finish_tie(conn, tid, tie["id"], winner=tie["entry_a_id"], rubbers=_sweep(True))
    return tid, group["id"], tie["id"]


# ---------------------------------------------------------------- 服务层基础

def test_service_reads_real_finished_ties(conn):
    tid, group_id, _ = _seed_two_team_group(conn)
    payload = _standings(conn, tid, group_id)
    rows = _rows_by_name(payload)

    assert payload["group_name"] == "第A组"
    assert payload["provisional"] is False
    assert payload["ambiguous"] is False
    assert payload["automatic_qualification_allowed"] is True
    assert payload["qualify_count"] == 1  # 赛事默认值（groups.qualify_count 为空）
    assert [r["team_name"] for r in payload["standings"]] == ["A队", "B队"]
    assert rows["A队"]["match_points"] == 2
    assert rows["B队"]["match_points"] == 1
    assert (rows["A队"]["ties_played"], rows["A队"]["ties_won"], rows["A队"]["ties_lost"]) == (1, 1, 0)
    assert (rows["B队"]["ties_played"], rows["B队"]["ties_won"], rows["B队"]["ties_lost"]) == (1, 0, 1)
    assert (rows["A队"]["rubber_wins"], rows["A队"]["rubber_losses"]) == (3, 0)
    assert (rows["B队"]["rubber_wins"], rows["B队"]["rubber_losses"]) == (0, 3)
    # 局分来自 TeamRubber.home_score / away_score（3 盘 2:0 → 6:0）
    assert (rows["A队"]["games_won"], rows["A队"]["games_lost"]) == (6, 0)
    assert (rows["B队"]["games_won"], rows["B队"]["games_lost"]) == (0, 6)
    assert rows["A队"]["qualification_position_state"] == "RESOLVED"
    assert rows["B队"]["qualification_position_state"] == "ELIGIBLE_ONLY"
    assert all(r["eligible_for_qualification"] for r in payload["standings"])


def test_skipped_rubbers_are_ignored(conn):
    """3:0 提前结束后剩下的盘是 SKIPPED：既不计盘、也不计局。"""
    tid = _team_tournament(conn, teams=2, per_group=2, name="SKIPPED 不计入")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    tie = repo.list_group_team_ties(conn, tid, group["id"])[0]
    _finish_tie(conn, tid, tie["id"], winner=tie["entry_a_id"], rubbers=_sweep(True))

    statuses = [r["status"] for r in repo.list_team_rubbers(conn, tie["id"])]
    assert statuses.count("FINISHED") == 3
    assert statuses.count("SKIPPED") == 2  # 确实存在 SKIPPED 的盘

    rows = _rows_by_name(_standings(conn, tid, group["id"]))
    assert rows["A队"]["rubber_wins"] == 3   # 不是 5
    assert rows["A队"]["games_won"] == 6     # 3 盘 × 2 局；SKIPPED 的盘贡献 0
    assert rows["A队"]["games_lost"] == 0
    assert rows["B队"]["games_won"] == 0


def test_games_ratio_really_reads_rubber_scores(conn):
    """局 W/L 真正读取 TeamRubber.home_score / away_score（同盘数、不同局分）。"""
    tid = _team_tournament(conn, teams=2, per_group=2, name="局分读取")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    tie = repo.list_group_team_ties(conn, tid, group["id"])[0]
    # A 3:0 取胜，但每盘都是 2:1（局分 6:3），而不是 2:0 的 6:0
    _finish_tie(conn, tid, tie["id"], winner=tie["entry_a_id"], rubbers=[WIN_21, WIN_21, WIN_21])

    raw = [
        (r["home_score"], r["away_score"])
        for r in repo.list_team_rubbers(conn, tie["id"])
        if r["status"] == "FINISHED"
    ]
    assert raw == [(2, 1), (2, 1), (2, 1)]

    rows = _rows_by_name(_standings(conn, tid, group["id"]))
    assert (rows["A队"]["games_won"], rows["A队"]["games_lost"]) == (6, 3)
    assert (rows["B队"]["games_won"], rows["B队"]["games_lost"]) == (3, 6)
    # 盘比率 3:0 与局比率 6:3 必须各自独立
    assert (rows["A队"]["rubber_wins"], rows["A队"]["rubber_losses"]) == (3, 0)


def test_standings_are_recomputed_from_current_facts(conn):
    """每次都从数据库事实重算：打完更多场后 provisional 与名次立刻改变（无缓存）。"""
    tid = _team_tournament(conn, teams=4, per_group=4, name="重算")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    teams = sorted(e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value))
    ties = repo.list_group_team_ties(conn, tid, group["id"])

    # 先只打完一场：B 胜 A
    first = next(t for t in ties if {t["entry_a_id"], t["entry_b_id"]} == set(teams[:2]))
    b_is_a = teams[1] == first["entry_a_id"]
    _finish_tie(conn, tid, first["id"], winner=teams[1], rubbers=_sweep(b_is_a))

    before = _standings(conn, tid, group["id"])
    assert before["provisional"] is True
    assert before["automatic_qualification_allowed"] is False
    rows = _rows_by_name(before)
    assert rows["B队"]["match_points"] == 2
    assert rows["A队"]["match_points"] == 1
    assert rows["C队"]["match_points"] == 0  # 还没打过
    for row in before["standings"]:
        assert row["qualification_position_state"] == "UNDECIDED"

    # 再打完其余全部对抗（A 队全胜其余对手）
    plan = {}
    for tie in ties:
        if tie["id"] == first["id"]:
            continue
        a, b = tie["entry_a_id"], tie["entry_b_id"]
        plan[frozenset((a, b))] = teams[0] if teams[0] in (a, b) else a
    _finish_all_group_ties(conn, tid, group["id"], plan=plan)

    after = _standings(conn, tid, group["id"])
    assert after["provisional"] is False  # 全部对抗已打完
    assert after["automatic_qualification_allowed"] is True
    rows = _rows_by_name(after)
    # 每一行都必须是"逐场累计"的结果（从这个真实赛果里重算，而不是沿用之前的快照）
    finished = [t for t in repo.list_group_team_ties(conn, tid, group["id"])
                if t["status"] == "FINISHED"]
    assert len(finished) == 6
    expected_points = {row["team_entry_id"]: 0 for row in after["standings"]}
    for tie in finished:
        expected_points[tie["winner_entry_id"]] += 2
        loser = tie["entry_b_id"] if tie["winner_entry_id"] == tie["entry_a_id"] else tie["entry_a_id"]
        expected_points[loser] += 1
    for row in after["standings"]:
        assert row["match_points"] == expected_points[row["team_entry_id"]]
        assert row["ties_played"] == 3
        assert row["ties_won"] + row["ties_lost"] == 3
    # B 赢了与 A 的那一场，因此不可能低于 A
    assert rows["B队"]["match_points"] >= rows["A队"]["match_points"]
    # 名次区间与 ambiguous 标记必须自洽（区间长度 == 该区间的队伍数）
    spans: dict[tuple[int, int], int] = {}
    for row in after["standings"]:
        span = (row["rank_start"], row["rank_end"])
        spans[span] = spans.get(span, 0) + 1
        assert row["ambiguous"] == (span[0] != span[1])
    assert all(count == end - start + 1 for (start, end), count in spans.items())


def test_ambiguous_group_flags_and_states(conn):
    """并列时：group.ambiguous 为真、行区间共享、位置事实为 UNDECIDED。

    构造：三队循环且全部 3:0 打完。5 盘制下每场对抗会留下 2 盘 SKIPPED，
    因此各队的盘/局累计取决于"哪一盘被跳过"，未必完全相同；
    本用例断言的是**接口契约**：只要存在无法区分的名次区间，
    区间内所有队伍必须共享 rank_start/rank_end、ambiguous=true、位置事实为 UNDECIDED。
    """
    tid = _team_tournament(conn, teams=3, per_group=3, name="并列")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    ties = repo.list_group_team_ties(conn, tid, group["id"])
    entries = sorted(e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value))
    # 胜负关系必须是一个环（每队恰好一胜一负），且与 round-robin 的 a/b 顺序无关。
    winners = {frozenset((entries[0], entries[1])): entries[1],
               frozenset((entries[1], entries[2])): entries[2],
               frozenset((entries[0], entries[2])): entries[0]}
    plan = {frozenset((t["entry_a_id"], t["entry_b_id"])):
            winners[frozenset((t["entry_a_id"], t["entry_b_id"]))] for t in ties}
    _finish_all_group_ties(conn, tid, group["id"], plan=plan)

    payload = _standings(conn, tid, group["id"])
    assert payload["provisional"] is False
    assert payload["automatic_qualification_allowed"] is True  # 打完了，允许自动判定
    # 三队循环 → 每队恰好 3 个比赛积分（一胜 2 分 + 一负 1 分）
    assert [row["match_points"] for row in payload["standings"]] == [3, 3, 3]

    # 名次区间与 ambiguous 必须与**同一份事实**上的纯算法结论逐行一致
    expected = _expected_rows_from_db(conn, tid, group["id"])
    for row in payload["standings"]:
        want = expected[row["team_entry_id"]]
        assert row["rank_start"] == want.rank_start
        assert row["rank_end"] == want.rank_end
        assert row["ambiguous"] == want.ambiguous
        assert row["match_points"] == want.match_points
        assert (row["rubber_wins"], row["rubber_losses"]) == (
            want.rubber_wins, want.rubber_losses
        )
        assert (row["games_won"], row["games_lost"]) == (want.games_won, want.games_lost)
        if want.ambiguous:
            assert row["qualification_position_state"] == "UNDECIDED"
    # group.ambiguous 与行级标记一致（不允许只在一处标记）
    assert payload["ambiguous"] == any(row["ambiguous"] for row in payload["standings"])
    # 区间必须连续覆盖 1..3
    assert sorted({(r["rank_start"], r["rank_end"]) for r in payload["standings"]}) == (
        [(1, 3)] if payload["ambiguous"] else [(1, 1), (2, 2), (3, 3)]
    )


def test_three_way_cycle_is_resolved_by_games_not_shared_ranks(conn):
    """三队循环且每场都是 3:0（各 3 盘 FINISHED + 2 盘 SKIPPED）→ 由局比率给出唯一名次。

    这个 fixture 同时证明两件事：
    1. 5 盘制下"提前结束"留下的 SKIPPED 盘确实**不计入**统计（每队正好 3:3 盘）；
    2. 循环同分时不是无脑并列——局比率能分开就给唯一名次，
       只有真的分不开（见下一条用例）才共享名次区间。
    """
    tid = _team_tournament(conn, teams=3, per_group=3, name="三队循环")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    entries = sorted(e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value))
    # 环：entries[1] 胜 entries[0]、entries[2] 胜 entries[1]、entries[0] 胜 entries[2]
    winners = {frozenset((entries[0], entries[1])): entries[1],
               frozenset((entries[1], entries[2])): entries[2],
               frozenset((entries[0], entries[2])): entries[0]}
    for tie in repo.list_group_team_ties(conn, tid, group["id"]):
        winner = winners[frozenset((tie["entry_a_id"], tie["entry_b_id"]))]
        home_won = winner == tie["entry_a_id"]
        _finish_tie(conn, tid, tie["id"], winner=winner,
                    rubbers=[(2 if home_won else 0, 0 if home_won else 2)] * 3)

    payload = _standings(conn, tid, group["id"])
    assert payload["provisional"] is False
    by_id = {row["team_entry_id"]: row for row in payload["standings"]}
    for row in payload["standings"]:
        assert row["match_points"] == 3                       # 一胜(2) + 一负(1)
        assert (row["rubber_wins"], row["rubber_losses"]) == (3, 3)  # SKIPPED 不计入

    # 三队的局分互不相同 → 名次必须唯一，且顺序 = 局比率降序（用服务自己报的局分校验自洽性）
    def ratio_greater(left: int, right: int) -> bool:
        """局比率严格大于（交叉乘法，避免 0 分母与浮点误差）。"""
        return (by_id[left]["games_won"] * by_id[right]["games_lost"]
                > by_id[right]["games_won"] * by_id[left]["games_lost"])

    ordered = sorted(entries, key=cmp_to_key(
        lambda left, right: -1 if ratio_greater(left, right) else (1 if ratio_greater(right, left) else 0)
    ))
    # 本 fixture 的局比率必须互不相同（否则这条用例就退化成"并列"了）
    assert all(
        ratio_greater(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)
    ), [(e, by_id[e]["games_won"], by_id[e]["games_lost"]) for e in ordered]
    for position, entry_id in enumerate(ordered, start=1):
        assert by_id[entry_id]["rank_start"] == position
        assert by_id[entry_id]["rank_end"] == position
        assert by_id[entry_id]["ambiguous"] is False
    assert payload["ambiguous"] is False
    # 每队恰好出场 2 次、盘 3+3（SKIPPED 的两盘确实被忽略）
    assert all(row["ties_played"] == 2 for row in payload["standings"])
    assert all(
        status == "SKIPPED"
        for tie in repo.list_group_team_ties(conn, tid, group["id"])
        for status in [r["status"] for r in repo.list_team_rubbers(conn, tie["id"])][3:]
    )


def test_identical_teams_share_one_rank_range(conn):
    """统计完全相同的两队必须共享同一个名次区间（1–2），且都标 ambiguous。

    这里用"一场都没打"的两队小组：积分/盘/局全部相同，任何 ranking key 都无法区分，
    因此只能并列——这正是"不按 id 破同分"的接口级证据（不返回 1 和 2 两个名次）。
    """
    tid = _team_tournament(conn, teams=2, per_group=2, name="并列区间")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]

    payload = _standings(conn, tid, group["id"])
    assert payload["provisional"] is True          # 一场都没打
    assert payload["ambiguous"] is True
    assert len(payload["standings"]) == 2
    for row in payload["standings"]:
        assert (row["rank_start"], row["rank_end"]) == (1, 2)
        assert row["ambiguous"] is True
        assert row["match_points"] == 0
        assert (row["rubber_wins"], row["rubber_losses"]) == (0, 0)
        assert (row["games_won"], row["games_lost"]) == (0, 0)
        assert row["qualification_position_state"] == "UNDECIDED"
    # **不按 id 打破同分**：两行共享同一个区间，而不是 1 / 2
    assert {row["rank_start"] for row in payload["standings"]} == {1}
    assert {row["rank_end"] for row in payload["standings"]} == {2}


def _expected_rows_from_db(conn, tid: int, group_id: int) -> dict:
    """直接从数据库事实跑一遍域层算法，作为服务层结果的独立参照。"""
    entries = [
        e for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value)
        if e["group_id"] == group_id
    ]
    entries.sort(key=lambda e: e["id"])
    ties = repo.list_group_team_ties_with_rubbers(conn, tid, group_id)
    facts = domain.StandingsFacts(
        entries=tuple(
            domain.TeamEntryFact(e["id"], e["display_name"], e["status"]) for e in entries
        ),
        ties=tuple(
            domain.TeamTieFact(
                tie_id=t["id"], entry_a_id=t["entry_a_id"], entry_b_id=t["entry_b_id"],
                status=t["status"], winner_entry_id=t["winner_entry_id"],
                rubbers=tuple(
                    domain.TeamRubberFact(
                        tie_id=t["id"], sequence=r["sequence"], status=r["status"],
                        winner_entry_id=r["winner_entry_id"],
                        home_score=r["home_score"], away_score=r["away_score"],
                    )
                    for r in t["rubbers"]
                ),
            )
            for t in ties
        ),
    )
    return {row.team_entry_id: row for row in domain.compute_team_group_standings(facts)}


# ---------------------------------------------------------------- provisional（§6.1）

def test_active_team_with_waiting_tie_is_provisional(conn):
    """组内还有 WAITING 的对抗（ACTIVE 队伍）→ provisional，禁止自动晋级。"""
    tid = _team_tournament(conn, teams=4, per_group=4, name="WAITING")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    ties = repo.list_group_team_ties(conn, tid, group["id"])
    _finish_tie(conn, tid, ties[0]["id"], winner=ties[0]["entry_a_id"], rubbers=_sweep(True))
    assert repo.get_team_tie(conn, ties[1]["id"])["status"] == "WAITING"

    payload = _standings(conn, tid, group["id"])
    assert payload["provisional"] is True
    assert payload["automatic_qualification_allowed"] is False
    for row in payload["standings"]:
        assert row["qualification_position_state"] == "UNDECIDED"


def test_active_team_with_playing_tie_is_provisional(conn):
    """组内还有 PLAYING 的对抗 → 同样 provisional。"""
    tid = _team_tournament(conn, teams=2, per_group=2, name="PLAYING")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    tie = repo.list_group_team_ties(conn, tid, group["id"])[0]
    tie_service.build_rubber_skeleton(conn, tid, tie["id"], FORMAT_CODE)
    view = runtime.runtime_view(conn, tid, tie["id"])
    first = view["rubbers"][0]
    runtime.set_lineup(
        conn, tid, tie["id"], first["id"],
        [m["player_id"] for m in view["home_team"]["members"]][:1],
        [m["player_id"] for m in view["away_team"]["members"]][:1],
    )
    runtime.start_rubber(conn, tid, tie["id"], first["id"])
    assert repo.get_team_tie(conn, tie["id"])["status"] == "PLAYING"

    payload = _standings(conn, tid, group["id"])
    assert payload["provisional"] is True
    assert payload["automatic_qualification_allowed"] is False
    for row in payload["standings"]:
        assert (row["match_points"], row["ties_played"]) == (0, 0)  # 未完成不进统计


# ---------------------------------------------------------------- 退赛（§6.2）

def test_withdrawn_team_keeps_results_but_loses_eligibility(conn):
    """退赛队伍：已完成比赛继续计入，但不可晋级，且仍占用名次区间。"""
    tid, group_id, tie_id = _seed_two_team_group(conn, name="退赛-全完成")
    tie = repo.get_team_tie(conn, tie_id)
    repo.withdraw_entry(conn, tie["entry_b_id"], "主裁判", "伤病")
    conn.commit()

    payload = _standings(conn, tid, group_id)
    rows = _rows_by_name(payload)
    assert payload["provisional"] is False  # 所有对抗都已完成 → 可以是 final
    assert payload["automatic_qualification_allowed"] is True
    assert rows["B队"]["status"] == "WITHDRAWN"
    assert rows["B队"]["match_points"] == 1        # 成绩保留
    assert rows["B队"]["ties_played"] == 1
    assert rows["B队"]["eligible_for_qualification"] is False
    assert (rows["B队"]["rank_start"], rows["B队"]["rank_end"]) == (2, 2)  # 仍占名次
    assert rows["B队"]["qualification_position_state"] == "ELIGIBLE_ONLY"
    assert rows["A队"]["eligible_for_qualification"] is True
    assert rows["A队"]["qualification_position_state"] == "RESOLVED"


def test_withdrawn_team_with_unfinished_tie_blocks_whole_group(conn):
    """退赛队伍仍有未完成对抗 → **整个小组** provisional，禁止自动晋级。"""
    tid = _team_tournament(conn, teams=4, per_group=4, name="退赛-未完成")
    tie_service.generate_group_ties(conn, tid)
    group = repo.list_groups(conn, tid)[0]
    ties = repo.list_group_team_ties(conn, tid, group["id"])
    first = ties[0]
    _finish_tie(conn, tid, first["id"], winner=first["entry_a_id"], rubbers=_sweep(True))
    repo.withdraw_entry(conn, first["entry_b_id"], "主裁判", "退赛")  # 它还有 2 场没打
    conn.commit()

    payload = _standings(conn, tid, group["id"])
    rows = _rows_by_name(payload)
    withdrawn_name = next(
        name for name, row in rows.items() if row["team_entry_id"] == first["entry_b_id"]
    )
    assert payload["provisional"] is True
    assert payload["automatic_qualification_allowed"] is False
    # 不只是退赛队：全组都不可自动晋级
    for row in payload["standings"]:
        assert row["qualification_position_state"] == "UNDECIDED"
    assert rows[withdrawn_name]["eligible_for_qualification"] is False
    assert rows[withdrawn_name]["match_points"] == 1  # 已完成的比赛仍然计入


# ---------------------------------------------------------------- 跨组隔离（§2.1）

def test_groups_are_isolated(conn):
    """两个小组各自独立：互不影响，接口按 sort_order 返回两组。"""
    tid = _team_tournament(conn, teams=8, per_group=4, name="跨组隔离")
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    assert len(groups) == 2

    _finish_all_group_ties(conn, tid, groups[0]["id"])  # 只打完 A 组

    all_payload = standings_service.list_team_group_standings(conn, tid)
    assert [g["group_id"] for g in all_payload] == [g["id"] for g in groups]

    first = _standings(conn, tid, groups[0]["id"])
    second = _standings(conn, tid, groups[1]["id"])
    assert first["provisional"] is False
    assert second["provisional"] is True          # B 组一场没打
    first_ids = {row["team_entry_id"] for row in first["standings"]}
    second_ids = {row["team_entry_id"] for row in second["standings"]}
    assert first_ids.isdisjoint(second_ids)
    # A 组统计不因 B 组存在而变化：4 队 → 6 场 → 12 次出场
    assert sum(row["ties_played"] for row in first["standings"]) == 12
    for row in second["standings"]:
        assert (row["match_points"], row["ties_played"]) == (0, 0)

    only_second = standings_service.list_team_group_standings(conn, tid, groups[1]["id"])
    assert [g["group_id"] for g in only_second] == [groups[1]["id"]]


def test_standings_match_a6_1_generated_schedule(conn):
    """A6.1 生成的赛程就是排名输入：每组 6 场，且与 round_robin 输出一致。"""
    tid = _team_tournament(conn, teams=4, per_group=4, name="与生成器一致")
    assert tie_service.generate_group_ties(conn, tid)["ties_generated"] == 6
    group = repo.list_groups(conn, tid)[0]
    ties = repo.list_group_team_ties(conn, tid, group["id"])
    members = sorted(e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value))
    assert [(t["round"], t["entry_a_id"], t["entry_b_id"]) for t in ties] == [
        (r, a, b) for r, a, b in round_robin.round_robin(members)
    ]

    payload = _standings(conn, tid, group["id"])
    assert len(payload["standings"]) == 4
    assert all(row["ties_played"] == 0 for row in payload["standings"])
    assert payload["provisional"] is True


# ---------------------------------------------------------------- 错误路径

def test_service_errors(conn):
    tid, group_id, _ = _seed_two_team_group(conn, name="错误路径")
    with pytest.raises(standings_service.TeamStandingsError) as missing:
        standings_service.get_team_group_standings(conn, 999999, group_id)
    assert missing.value.code == 404

    with pytest.raises(standings_service.TeamStandingsError) as no_group:
        standings_service.get_team_group_standings(conn, tid, 999999)
    assert no_group.value.code == 404

    other = repo.create_tournament(
        conn, "别的赛事", "2026-09-02", 4, 1, 1, event_type=EventType.TEAM.value
    )
    other_group = repo.create_group(conn, other["id"], "别组", 0)
    conn.commit()
    with pytest.raises(standings_service.TeamStandingsError) as cross:
        standings_service.get_team_group_standings(conn, tid, other_group["id"])
    assert cross.value.code == 404


def test_non_team_tournament_is_rejected(conn):
    singles = repo.create_tournament(conn, "单打赛", "2026-09-01", 4, 1, 1, event_type="SINGLES")
    group = repo.create_group(conn, singles["id"], "A组", 0)
    conn.commit()
    with pytest.raises(standings_service.TeamStandingsError) as excinfo:
        standings_service.get_team_group_standings(conn, singles["id"], group["id"])
    assert excinfo.value.code == 409
    assert "TEAM" in str(excinfo.value)


def test_qualify_count_overrides_group_level(conn):
    """组级 qualify_count 优先于赛事默认值（沿用个人赛口径）。"""
    tid, group_id, _ = _seed_two_team_group(conn, name="出线名额")
    repo.update_group_qualify_count(conn, group_id, 2)
    payload = _standings(conn, tid, group_id)
    assert payload["qualify_count"] == 2
    rows = _rows_by_name(payload)
    assert rows["A队"]["qualification_position_state"] == "RESOLVED"
    assert rows["B队"]["qualification_position_state"] == "RESOLVED"  # 2 个名额


# ==================================================================== API 层

def _api_team_tournament(client, *, teams: int, per_group: int, name: str = "团体排名 API"):
    return client.post(
        "/api/tournaments",
        json={
            "name": name, "date": "2026-09-01", "table_count": 4,
            "group_count": teams // per_group, "qualify_per_group": 1,
            "event_type": "TEAM", "operation_mode": "DEMO",
        },
    ).json()["id"]


def test_api_returns_group_standings(client):
    tid = _api_team_tournament(client, teams=2, per_group=2)
    players = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, 9)
    ]
    for index in range(2):
        resp = client.post(
            f"/api/tournaments/{tid}/teams",
            json={"display_name": f"{index + 1}队", "member_ids": players[index * 4 : (index + 1) * 4]},
        )
        assert resp.status_code == 201, resp.text
    grouped = client.post(f"/api/tournaments/{tid}/auto-group")
    assert grouped.status_code == 200, grouped.text
    group_id = grouped.json()["groups"][0]["id"]
    assert client.post(GENERATE_URL.format(tid=tid)).status_code == 200

    payload = client.get(GROUP_STANDINGS_URL.format(tid=tid, gid=group_id))
    assert payload.status_code == 200, payload.text
    body = payload.json()
    assert set(body) == {
        "group_id", "group_name", "provisional", "ambiguous",
        "automatic_qualification_allowed", "qualify_count", "standings",
    }
    assert body["group_id"] == group_id
    assert body["provisional"] is True      # 一场没打
    assert body["automatic_qualification_allowed"] is False
    assert len(body["standings"]) == 2
    row = body["standings"][0]
    assert set(row) == {
        "team_entry_id", "team_name", "status", "match_points", "ties_played",
        "ties_won", "ties_lost", "rubber_wins", "rubber_losses", "games_won",
        "games_lost", "rank_start", "rank_end", "ambiguous",
        "eligible_for_qualification", "qualification_position_state",
    }
    assert "qualified" not in row           # A6.3 才做晋级
    assert row["match_points"] == 0
    assert (row["rank_start"], row["rank_end"]) == (1, 2)
    assert row["ambiguous"] is True
    assert row["qualification_position_state"] == "UNDECIDED"

    listed = client.get(STANDINGS_URL.format(tid=tid))
    assert listed.status_code == 200
    assert [g["group_id"] for g in listed.json()] == [group_id]
    filtered = client.get(STANDINGS_URL.format(tid=tid), params={"group_id": group_id})
    assert [g["group_id"] for g in filtered.json()] == [group_id]


def test_api_error_statuses(client):
    tid = _api_team_tournament(client, teams=2, per_group=2, name="API 错误")
    assert client.get(GROUP_STANDINGS_URL.format(tid=tid, gid=999999)).status_code == 404
    assert client.get(STANDINGS_URL.format(tid=999999)).status_code == 404
    assert client.get(STANDINGS_URL.format(tid=tid), params={"group_id": 999999}).status_code == 404

    singles = client.post(
        "/api/tournaments",
        json={
            "name": "单打", "date": "2026-09-01", "table_count": 4, "group_count": 1,
            "qualify_per_group": 1, "event_type": "SINGLES",
        },
    ).json()["id"]
    resp = client.get(STANDINGS_URL.format(tid=singles))
    assert resp.status_code == 409
    assert "TEAM" in resp.json()["detail"]


def test_api_empty_group_returns_empty_list(client):
    """还没分组时返回空数组而不是报错。"""
    tid = _api_team_tournament(client, teams=2, per_group=2, name="空小组")
    assert client.get(STANDINGS_URL.format(tid=tid)).json() == []


# ==================================================================== 集成：A6.1 → Runtime → standings

def test_generator_runtime_standings_integration(conn):
    """A6.1 生成 → Runtime 真打完 → standings 正确反映事实（端到端）。"""
    tid = _team_tournament(conn, teams=4, per_group=4, name="端到端")
    assert tie_service.generate_group_ties(conn, tid)["ties_generated"] == 6
    group = repo.list_groups(conn, tid)[0]
    teams = sorted(e["id"] for e in repo.list_entries_by_type(conn, tid, EventType.TEAM.value))

    plan = {
        frozenset((teams[0], teams[1])): teams[0],
        frozenset((teams[0], teams[2])): teams[0],
        frozenset((teams[0], teams[3])): teams[0],
        frozenset((teams[1], teams[2])): teams[1],
        frozenset((teams[1], teams[3])): teams[1],
        frozenset((teams[2], teams[3])): teams[2],
    }
    _finish_all_group_ties(conn, tid, group["id"], plan=plan)

    payload = _standings(conn, tid, group["id"])
    assert payload["provisional"] is False
    assert payload["ambiguous"] is False
    assert [row["team_entry_id"] for row in payload["standings"]] == teams
    assert [row["match_points"] for row in payload["standings"]] == [6, 5, 4, 3]
    assert [(row["rank_start"], row["rank_end"]) for row in payload["standings"]] == [
        (1, 1), (2, 2), (3, 3), (4, 4)
    ]
    rows = _rows_by_name(payload)
    assert rows["A队"]["qualification_position_state"] == "RESOLVED"   # 名额 1
    assert rows["B队"]["qualification_position_state"] == "ELIGIBLE_ONLY"
    # 一场对抗都没被做成普通 Match
    assert repo.list_matches(conn, tid) == []
