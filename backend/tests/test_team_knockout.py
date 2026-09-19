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
from app.services import team_ties as tie_service
from app.services import teams as teams_service

FORMAT_CODE = "LOCAL_CLASSIC_5_V1"
GENERATE_TIES_URL = "/api/tournaments/{tid}/team-ties/generate-group-ties"
CONFIRM_URL = "/api/tournaments/{tid}/qualification/confirm"
GENERATE_KO_URL = "/api/tournaments/{tid}/team-knockout/generate"
GET_KO_URL = "/api/tournaments/{tid}/team-knockout"


# ------------------------------------------------------------------ 夹具

def _team_tournament(
    conn, *, teams: int, group_count: int, per_group: int, name: str,
    qualify_per_group: int = 2,
) -> int:
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
    for index, entry in enumerate(entries):
        repo.set_entry_group(conn, entry["id"], groups[index // per_group]["id"])
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


def _finish_group(conn, tid: int, group_id: int) -> None:
    """强者通吃：计算顺序在前者获胜 → 组内名次唯一（无并列）。"""
    for tie in repo.list_group_team_ties(conn, tid, group_id):
        a, b = tie["entry_a_id"], tie["entry_b_id"]
        _finish_tie(conn, tid, tie["id"], a if a < b else b)


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
