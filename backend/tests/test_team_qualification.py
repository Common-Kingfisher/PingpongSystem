"""A6.3 团体晋级（Team Qualification）。

规则源：`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`。本文件覆盖任务书要求的四类用例：

1. **Case 1 正常晋级**：4 组 × 每组前 2 → 候选正确、数量正确，可以自动确认；
2. **Case 2 并列晋级**：`rank 2-3` 并列且 `qualify_count = 2`
   → `requires_manual_resolution = true`，系统**绝不**按 id / 顺序 / 随机打破；
3. **Case 3 小组未完成**：standings `provisional = true` → 禁止自动确认；
4. **Case 4 非法确认**：跨赛事队伍 / 数量错误 / 重复队伍 → 全部拒绝且不落库。

另外覆盖：已退赛队伍不可晋级；确认是全量替换；确认后可再确认（替换）；
非 TEAM 赛事与不存在的赛事。

刻意**不**在这里测试（A6.3 范围外）：淘汰签生成（见 `test_team_knockout.py`）、
抽签、排程/ETA、实时运行态 UI。
"""

import pytest

from app import db as db_module
from app import repository as repo
from app.models import EventType
from app.services import team_qualification as qual_service
from app.services import team_runtime as runtime
from app.services import team_standings as standings_service
from app.services import team_ties as tie_service
from app.services import teams as teams_service

FORMAT_CODE = "LOCAL_CLASSIC_5_V1"
GENERATE_TIES_URL = "/api/tournaments/{tid}/team-ties/generate-group-ties"
QUALIFICATION_URL = "/api/tournaments/{tid}/qualification"
CONFIRM_URL = "/api/tournaments/{tid}/qualification/confirm"


# ------------------------------------------------------------------ 夹具

def _team_tournament(
    conn, *, teams: int, group_count: int, per_group: int, name: str = "团体晋级验收",
    qualify_per_group: int = 2,
) -> int:
    """TEAM 赛事 + `teams` 支队伍（每队 4 人）+ 按计算顺序分组（不依赖自动分组随机性）。"""
    tournament = repo.create_tournament(
        conn, name, "2026-10-01", 4, group_count, qualify_per_group,
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
    assert len(entries) == teams
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
    """真打完一场对抗（3 盘 2:0，先赢 3 盘即结束，剩余盘 SKIPPED）。"""
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
    assert repo.get_team_tie(conn, tie_id)["winner_entry_id"] == winner


def _finish_group(conn, tid: int, group_id: int, *, transitive: bool = True) -> None:
    """把某组全部对抗打完。

    `transitive=True`：按队伍计算顺序"强者通吃"→ 组内名次唯一（无并列）。
    `transitive=False`：**第一名通吃其余三队，其余三队两两循环** →
        standings[0] 独自第 1 名，standings[1..3] 三项统计完全相同（并列 2–4 名）。
        这是制造"晋级线上并列"的最小构造：每队"赢一场 3:0、输一场 0:3"，
        因此盘 3:3、局 6:6，三者逐项相等，任何 ranking key 都无法区分。
    """
    teams = _group_teams(conn, tid, group_id)
    ties = repo.list_group_team_ties(conn, tid, group_id)
    assert ties, "该组还没有对抗，请先生成小组赛"

    if transitive:
        for tie in ties:
            a, b = tie["entry_a_id"], tie["entry_b_id"]
            _finish_tie(conn, tid, tie["id"], a if a < b else b)  # 计算顺序在前者获胜
        return

    assert len(teams) == 4, "并列构造需要 4 支队伍（1 强 + 3 循环）"
    first, rest = teams[0], teams[1:]
    winners: dict[frozenset, int] = {
        frozenset((first, other)): first for other in rest
    }
    winners[frozenset((rest[0], rest[1]))] = rest[0]
    winners[frozenset((rest[1], rest[2]))] = rest[1]
    winners[frozenset((rest[0], rest[2]))] = rest[2]
    for tie in ties:
        pair = frozenset((tie["entry_a_id"], tie["entry_b_id"]))
        _finish_tie(conn, tid, tie["id"], winners[pair])


def _setup_finished(
    conn, *, teams: int, group_count: int, per_group: int, name: str,
    qualify_per_group: int = 2, transitive: bool = True,
) -> tuple[int, list[dict]]:
    """建赛 → 生成小组赛 → 全部打完（每组名次唯一）。返回 (tid, 小组列表)。"""
    tid = _team_tournament(
        conn, teams=teams, group_count=group_count, per_group=per_group,
        name=name, qualify_per_group=qualify_per_group,
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    for group in groups:
        _finish_group(conn, tid, group["id"], transitive=transitive)
    return tid, groups


# ==================================================================== Case 1：正常晋级

def test_case1_four_groups_top_two_are_auto_qualified(conn):
    """4 组 × 每组 4 队、每组前 2 → 每组的候选与数量都正确，无并列、可自动确认。"""
    tid, groups = _setup_finished(
        conn, teams=16, group_count=4, per_group=4, name="Case1 正常晋级"
    )
    payload = qual_service.get_qualification(conn, tid)

    assert payload["provisional"] is False
    assert payload["requires_manual_resolution"] is False
    assert payload["can_confirm"] is True
    assert payload["blocked_reasons"] == []
    assert len(payload["groups"]) == 4
    assert payload["confirmed"] == []

    for view, group in zip(payload["groups"], groups):
        assert view["group_name"] == group["name"]
        assert view["qualify_count"] == 2
        assert view["provisional"] is False
        assert view["requires_manual_resolution"] is False
        assert view["can_confirm"] is True
        assert len(view["auto_qualified_team_ids"]) == 2
        assert view["boundary_tied_team_ids"] == []
        # 候选正好是"名次前 2"，且与 auto_qualified 一致
        assert view["candidates"] == [
            {
                "team_entry_id": team_id,
                "team_name": view["candidates"][index]["team_name"],
                "auto_qualified": True,
                "on_boundary_tie": False,
            }
            for index, team_id in enumerate(view["auto_qualified_team_ids"])
        ]
        # 候选必须真的来自本组
        assert set(view["auto_qualified_team_ids"]) <= set(_group_teams(conn, tid, group["id"]))

    # 总共 4 组 × 2 = 8 个晋级候选
    assert sum(len(g["auto_qualified_team_ids"]) for g in payload["groups"]) == 8


def test_case1_confirm_accepts_exactly_the_auto_qualified_teams(conn):
    """按系统结论确认 → 落库，再次查询能看到 confirmed。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="Case1 确认")
    before = qual_service.get_qualification(conn, tid)
    expected = [
        team_id for group in before["groups"] for team_id in group["auto_qualified_team_ids"]
    ]
    assert len(expected) == 8

    payload = qual_service.confirm_qualification(conn, tid, expected)
    assert [row["team_entry_id"] for row in payload["confirmed"]] == expected
    assert all(row["status"] == "QUALIFIED" for row in payload["confirmed"])
    assert all(row["group_id"] is not None for row in payload["confirmed"])
    # 落库行数 == 确认数量，且每条只出现一次
    rows = repo.list_team_qualifications(conn, tid)
    assert len(rows) == 8
    assert len({row["team_entry_id"] for row in rows}) == 8

    # 再确认一次（全量替换）不会翻倍
    payload2 = qual_service.confirm_qualification(conn, tid, list(reversed(expected)))
    assert len(repo.list_team_qualifications(conn, tid)) == 8
    # confirmed 的返回顺序始终按 小组顺序 → 组内排名顺序（与请求顺序无关）
    assert [row["team_entry_id"] for row in payload2["confirmed"]] == expected


# ==================================================================== Case 2：并列晋级

def test_case2_boundary_tie_requires_manual_resolution(conn):
    """rank 2-3 并列且 qualify_count = 2 → 必须人工处理，且不自动选任何人。

    A 组构造：T01 全胜（名次唯一第 1）；T02/T03/T04 两两循环且**三项统计完全相同**
    → 三者并列 2–4 名。晋级名额 2 → 第 1 名自动晋级，剩 1 个席位被并列挡住。
    """
    tid = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Case2 并列晋级", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    # A 组：1 强 + 3 循环 → 并列 2–4；B 组：强者通吃 → 名次唯一
    _finish_group(conn, tid, groups[0]["id"], transitive=False)
    _finish_group(conn, tid, groups[1]["id"], transitive=True)

    payload = qual_service.get_qualification(conn, tid)
    assert payload["requires_manual_resolution"] is True
    assert payload["can_confirm"] is False

    tie_teams = _group_teams(conn, tid, groups[0]["id"])
    tie_group = payload["groups"][0]
    assert tie_group["group_name"] == groups[0]["name"]
    assert tie_group["requires_manual_resolution"] is True
    # 第 1 名（tie_teams[0]）自动晋级，剩 1 个席位由并列的 3 支队伍竞争
    assert tie_group["auto_qualified_team_ids"] == [tie_teams[0]]
    assert tie_group["boundary_slots_remaining"] == 1
    assert sorted(tie_group["boundary_tied_team_ids"]) == sorted(tie_teams[1:])
    # 并列的三支都在候选里且标记为跨线并列（系统不选任何一个）
    tied_candidates = [c for c in tie_group["candidates"] if c["on_boundary_tie"]]
    assert sorted(c["team_entry_id"] for c in tied_candidates) == sorted(tie_teams[1:])
    assert all(not c["auto_qualified"] for c in tied_candidates)

    clean_group = payload["groups"][1]
    assert clean_group["requires_manual_resolution"] is False
    assert len(clean_group["auto_qualified_team_ids"]) == 2

    # 系统不给出任何"建议晋级"：confirmed 仍为空
    assert payload["confirmed"] == []


def test_case2_manual_confirmation_resolves_the_tie(conn):
    """人工从并列块中挑出正确数量 → 允许确认；数量不对 → 拒绝。"""
    tid = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Case2 人工确认", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    _finish_group(conn, tid, groups[0]["id"], transitive=False)
    _finish_group(conn, tid, groups[1]["id"], transitive=True)

    payload = qual_service.get_qualification(conn, tid)
    tie_group = payload["groups"][0]
    clean_group = payload["groups"][1]
    clean_picks = list(clean_group["auto_qualified_team_ids"])
    tied = sorted(tie_group["boundary_tied_team_ids"])
    auto = list(tie_group["auto_qualified_team_ids"])
    assert len(tied) == 3 and len(auto) == 1

    # 不选并列队（只交自动晋级的那支）→ 422：该组数量不足
    with pytest.raises(qual_service.ServiceError) as short:
        qual_service.confirm_qualification(conn, tid, clean_picks + auto)
    assert short.value.code == 422
    assert repo.list_team_qualifications(conn, tid) == []

    # 并列块里多选一个 → 422
    with pytest.raises(qual_service.ServiceError) as many:
        qual_service.confirm_qualification(conn, tid, clean_picks + auto + tied[:2])
    assert many.value.code == 422
    assert repo.list_team_qualifications(conn, tid) == []

    # 正好一个并列队 → 成功
    chosen = tied[1]
    result = qual_service.confirm_qualification(conn, tid, clean_picks + auto + [chosen])
    confirmed_ids = {row["team_entry_id"] for row in result["confirmed"]}
    assert confirmed_ids == set(clean_picks) | set(auto) | {chosen}
    assert set(result["groups"][0]["confirmed_team_ids"]) == set(auto) | {chosen}


def test_case2_system_never_breaks_ties_by_id(conn):
    """同一份并列事实、重复查询 → 结论完全一致（没有按 id/顺序破并列）。"""
    tid = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Case2 确定性", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid)
    groups = repo.list_groups(conn, tid)
    _finish_group(conn, tid, groups[0]["id"], transitive=False)
    _finish_group(conn, tid, groups[1]["id"], transitive=True)

    first = qual_service.get_qualification(conn, tid)
    second = qual_service.get_qualification(conn, tid)
    assert first["groups"] == second["groups"]

    tie_group = first["groups"][0]
    # 并列 3 支只争 1 个席位 → 系统一个都不自动选（既不按 id、也不按顺序）
    assert tie_group["boundary_slots_remaining"] == 1
    assert not any(c["auto_qualified"] for c in tie_group["candidates"] if c["on_boundary_tie"])
    # 而且并列队伍的展示顺序与"谁该晋级"无关：换一个 group 也一样只认统计
    assert tie_group["requires_manual_resolution"] is True


# ==================================================================== Case 3：小组未完成

def test_case3_provisional_group_blocks_confirmation(conn):
    """只要有一组没打完 → 整体 provisional，禁止确认（也禁止后续生成淘汰签）。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="Case3 未完成")
    # 把"最后一场"打回未完成状态：直接删掉它的结果不可行（Runtime 无撤销），
    # 因此这里改用"只打完部分小组"的构造：重新建一个赛事更直观。
    tid2 = _team_tournament(
        conn, teams=8, group_count=2, per_group=4, name="Case3 只打一半", qualify_per_group=2
    )
    tie_service.generate_group_ties(conn, tid2)
    groups2 = repo.list_groups(conn, tid2)
    _finish_group(conn, tid2, groups2[0]["id"], transitive=True)  # 只打完 A 组

    payload = qual_service.get_qualification(conn, tid2)
    assert payload["provisional"] is True
    assert payload["can_confirm"] is False
    assert payload["groups"][1]["provisional"] is True
    assert payload["groups"][1]["blocked_reasons"]
    assert any("尚未全部结束" in reason for reason in payload["blocked_reasons"])

    # 直接调用服务确认 → 409
    with pytest.raises(qual_service.ServiceError) as excinfo:
        qual_service.confirm_qualification(
            conn, tid2, payload["groups"][0]["auto_qualified_team_ids"]
        )
    assert excinfo.value.code == 409
    assert repo.list_team_qualifications(conn, tid2) == []

    # 顺带确认：Case3 的第一个赛事是完整打完的，仍然可以确认
    assert qual_service.get_qualification(conn, tid)["can_confirm"] is True


# ==================================================================== Case 4：非法确认

def test_case4_cross_tournament_team_is_rejected(conn):
    """跨赛事队伍 → 404，且不落库。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="Case4 跨赛事")
    other, _ = _setup_finished(
        conn, teams=8, group_count=2, per_group=4, name="Case4 另一个赛事"
    )
    payload = qual_service.get_qualification(conn, tid)
    picks = [t for g in payload["groups"] for t in g["auto_qualified_team_ids"]]
    foreign = qual_service.get_qualification(conn, other)["groups"][0]["auto_qualified_team_ids"][0]
    assert foreign not in picks

    with pytest.raises(qual_service.ServiceError) as excinfo:
        qual_service.confirm_qualification(conn, tid, picks[:-1] + [foreign])
    assert excinfo.value.code == 404
    assert "不存在或不属于本赛事" in str(excinfo.value)
    assert repo.list_team_qualifications(conn, tid) == []


def test_case4_wrong_count_is_rejected(conn):
    """数量错误（少选/多选/漏整组）→ 422。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="Case4 数量")
    payload = qual_service.get_qualification(conn, tid)
    picks = [t for g in payload["groups"] for t in g["auto_qualified_team_ids"]]

    with pytest.raises(qual_service.ServiceError) as fewer:
        qual_service.confirm_qualification(conn, tid, picks[:-1])
    assert fewer.value.code == 422

    # 漏掉一整组（用另一组的名额补上）→ 仍然 422，因为该组会少一个
    with pytest.raises(qual_service.ServiceError) as missing_group:
        qual_service.confirm_qualification(conn, tid, picks[:4] + picks[:2])
    assert missing_group.value.code == 422

    assert repo.list_team_qualifications(conn, tid) == []


def test_case4_duplicate_teams_are_rejected(conn):
    """重复队伍 → 422，且不落库。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="Case4 重复")
    payload = qual_service.get_qualification(conn, tid)
    picks = [t for g in payload["groups"] for t in g["auto_qualified_team_ids"]]

    with pytest.raises(qual_service.ServiceError) as excinfo:
        qual_service.confirm_qualification(conn, tid, picks[:7] + [picks[0]])
    assert excinfo.value.code == 422
    assert "重复" in str(excinfo.value)
    assert repo.list_team_qualifications(conn, tid) == []


def test_case4_empty_selection_is_rejected(conn):
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="Case4 空名单")
    with pytest.raises(qual_service.ServiceError) as excinfo:
        qual_service.confirm_qualification(conn, tid, [])
    assert excinfo.value.code == 422


# ==================================================================== 退赛

def test_withdrawn_team_is_not_a_candidate(conn):
    """已退赛队伍不可晋级：不出现在候选里，也不能被确认。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="退赛不可晋级")
    payload = qual_service.get_qualification(conn, tid)
    target = payload["groups"][0]["auto_qualified_team_ids"][0]
    repo.withdraw_entry(conn, target, "主裁判", "伤病退赛")
    conn.commit()

    after = qual_service.get_qualification(conn, tid)
    candidates = {c["team_entry_id"] for c in after["groups"][0]["candidates"]}
    assert target not in candidates
    # 该组现在只剩 1 个自动晋级者（名额 2 但退赛者被排除）
    assert target not in after["groups"][0]["auto_qualified_team_ids"]

    picks = [t for g in after["groups"] for t in g["auto_qualified_team_ids"]]
    with pytest.raises(qual_service.ServiceError) as excinfo:
        qual_service.confirm_qualification(conn, tid, picks + [target])
    assert excinfo.value.code in (404, 422)
    assert repo.list_team_qualifications(conn, tid) == []


# ==================================================================== 错误路径 / API

def test_non_team_and_missing_tournament_are_rejected(conn):
    singles = repo.create_tournament(conn, "单打", "2026-10-01", 4, 1, 2, event_type="SINGLES")
    group = repo.create_group(conn, singles["id"], "A组", 0)
    conn.commit()
    with pytest.raises(qual_service.ServiceError) as wrong_event:
        qual_service.get_qualification(conn, singles["id"])
    assert wrong_event.value.code == 409
    assert "TEAM" in str(wrong_event.value)

    with pytest.raises(qual_service.ServiceError) as missing:
        qual_service.get_qualification(conn, 999999)
    assert missing.value.code == 404
    del group


def test_standings_and_qualification_agree_on_ranks(conn):
    """晋级结论必须与 A6.2 的名次事实一致（不重新排名、不另算一套）。"""
    tid, groups = _setup_finished(conn, teams=16, group_count=4, per_group=4, name="与 A6.2 一致")
    payload = qual_service.get_qualification(conn, tid)
    for view, group in zip(payload["groups"], groups):
        standings = standings_service.get_team_group_standings(conn, tid, group["id"])
        inside = [
            row["team_entry_id"] for row in standings["standings"]
            if row["rank_end"] <= view["qualify_count"]
        ]
        assert view["auto_qualified_team_ids"] == inside


# ------------------------------------------------------------------ API 层

def _api_team_tournament(client, *, teams: int, group_count: int, per_group: int,
                         qualify_per_group: int = 2) -> tuple[int, list[dict]]:
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "团体晋级 API", "date": "2026-10-01", "table_count": 4,
            "group_count": group_count, "qualify_per_group": qualify_per_group,
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


def test_api_qualification_state_and_confirm_flow(client):
    """API 全流程：未打完 → 409；打完 → 可确认 → confirm 落库。"""
    tid, groups = _api_team_tournament(client, teams=16, group_count=4, per_group=4)
    assert client.post(GENERATE_TIES_URL.format(tid=tid)).status_code == 200

    state = client.get(QUALIFICATION_URL.format(tid=tid))
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["provisional"] is True
    assert body["can_confirm"] is False
    assert len(body["groups"]) == 4
    assert set(body) == {
        "tournament_id", "provisional", "requires_manual_resolution",
        "can_confirm", "blocked_reasons", "groups", "confirmed",
    }
    group_view = body["groups"][0]
    assert set(group_view) == {
        "group_id", "group_name", "qualify_count", "provisional",
        "requires_manual_resolution", "can_confirm", "auto_qualified_team_ids",
        "boundary_tied_team_ids", "boundary_slots_remaining", "blocked_reasons",
        "confirmed_team_ids", "candidates",
    }

    # 打完全部小组（API 层不提供"打完"的接口，用 service 层驱动 Runtime 到完成态）
    conn = db_module.connect()
    try:
        for group in repo.list_groups(conn, tid):
            _finish_group(conn, tid, group["id"], transitive=True)
    finally:
        conn.close()

    ready = client.get(QUALIFICATION_URL.format(tid=tid)).json()
    assert ready["can_confirm"] is True
    picks = [t for g in ready["groups"] for t in g["auto_qualified_team_ids"]]
    assert len(picks) == 8

    confirmed = client.post(CONFIRM_URL.format(tid=tid), json={"qualified_team_ids": picks})
    assert confirmed.status_code == 200, confirmed.text
    assert {row["team_entry_id"] for row in confirmed.json()["confirmed"]} == set(picks)

    # 重复确认是幂等的（全量替换），不会翻倍
    again = client.post(CONFIRM_URL.format(tid=tid), json={"qualified_team_ids": picks})
    assert again.status_code == 200
    assert len(again.json()["confirmed"]) == 8


def test_api_rejects_bad_confirmation_payloads(client):
    tid, groups = _api_team_tournament(client, teams=16, group_count=4, per_group=4)
    assert client.post(GENERATE_TIES_URL.format(tid=tid)).status_code == 200

    # 还没打完 → 409
    resp = client.post(CONFIRM_URL.format(tid=tid), json={"qualified_team_ids": [1, 2]})
    assert resp.status_code == 409

    # 空列表 → 422（Pydantic 层）
    assert client.post(CONFIRM_URL.format(tid=tid), json={"qualified_team_ids": []}).status_code == 422

    # 赛事不存在 / 非 TEAM
    assert client.get(QUALIFICATION_URL.format(tid=999999)).status_code == 404
    singles = client.post(
        "/api/tournaments",
        json={"name": "单打", "date": "2026-10-01", "table_count": 4, "group_count": 1,
              "qualify_per_group": 2, "event_type": "SINGLES"},
    ).json()["id"]
    assert client.get(QUALIFICATION_URL.format(tid=singles)).status_code == 409
