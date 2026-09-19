"""小组赛 → 淘汰赛过渡期的状态闭环（ConsolePage / KnockoutPage 的错误交互修复）。

背景：小组赛打完之后、淘汰赛签表生成之前存在一个"过渡窗口"。前端曾经在这个窗口里
自相矛盾——一边提示"可以生成淘汰赛"、一边还挂着"请先完成小组赛"的过期报错，
控制台也仍然提供"自动安排下一批比赛"和球台上的"安排比赛"。

本文件锁定前端判定所依赖的**数据契约**（@56 每个断言都对应一个界面分支），
真正的判定逻辑在 `frontend/src/pages/ConsolePage.tsx`（groupStageCompleted）与
`frontend/src/pages/KnockoutPage.tsx`（awaitingBracket / knockoutReady）。

三个验收场景：
- 场景1  小组赛进行中            → Console 显示自动安排；Knockout 显示"尚未完成"、无生成入口
- 场景2  小组赛完成、未生成淘汰赛 → Console 24/24 且不再提供安排入口；Knockout 允许生成
- 场景3  淘汰赛生成后            → 签表存在、Console 恢复排台能力，且不再显示"可以生成"
"""

import pytest

TEAM_COUNT = 16
TABLE_COUNT = 4
GROUP_COUNT = 4
QUALIFY = 2


# ----------------------------------------------------------------- 工具

def _create_tournament(client, name, *, players=TEAM_COUNT, tables=TABLE_COUNT,
                       groups=GROUP_COUNT, qualify=QUALIFY, mode="DEMO"):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": name,
            "date": "2026-07-10",
            "table_count": tables,
            "group_count": groups,
            "qualify_per_group": qualify,
            "operation_mode": mode,
        },
    ).json()["id"]
    for i in range(1, players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    return tid


def _group_stage_tournament(client, name, **kwargs) -> tuple[int, int]:
    """建赛事 → 选手 → 分组 → 生成小组赛，返回 (tid, 小组赛场数)。"""
    tid = _create_tournament(client, name, **kwargs)
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200
    generated = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert generated.status_code == 200, generated.text
    return tid, generated.json()["matches_generated"]


def _play_group_rounds(client, tid: int, *, stop_after: int | None = None) -> int:
    """调度 + 录分（id 小者 2:0 胜，结果可复现），直到没有可安排的比赛。

    stop_after 用于故意停在中间状态（场景1）：一次调度会同时填满多张球台，
    因此这里逐场检查，达到目标场数就立刻停下。
    """
    done = 0
    for _ in range(200):
        if stop_after is not None and done >= stop_after:
            break
        client.post(f"/api/tournaments/{tid}/schedule-next")
        dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [tb["match"] for tb in dash["tables"] if tb["match"]]
        if not playing:
            break
        for m in playing:
            if stop_after is not None and done >= stop_after:
                return done
            winner_is_a = m["player_a_id"] < m["player_b_id"]
            resp = client.post(
                f"/api/matches/{m['id']}/score",
                json={"player_a_score": 2 if winner_is_a else 0,
                      "player_b_score": 0 if winner_is_a else 2},
            )
            assert resp.status_code == 200, resp.text
            done += 1
    return done


def _console_state(client, tid: int) -> dict:
    """复刻 ConsolePage 的 groupStageCompleted 判定所需字段。"""
    tournament = client.get(f"/api/tournaments/{tid}").json()
    dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
    finished = client.get(f"/api/tournaments/{tid}/matches", params={"status": "FINISHED"}).json()
    waiting = client.get(f"/api/tournaments/{tid}/matches", params={"status": "WAITING"}).json()

    waiting_group = [m for m in waiting if m["stage"] == "GROUP"]
    playing_group = [
        tb["match"] for tb in dash["tables"] if tb["match"] and tb["match"]["stage"] == "GROUP"
    ]
    finished_group = [m for m in finished if m["stage"] == "GROUP"]
    group_total = len(waiting_group) + len(playing_group) + len(finished_group)
    return {
        "stage": tournament["stage"],
        "table_count": tournament["table_count"],
        "dashboard_tables": len(dash["tables"]),
        "stats": dash["stats"],
        "finished_group": len(finished_group),
        "waiting_group": len(waiting_group),
        "playing_group": len(playing_group),
        "group_total": group_total,
        # ConsolePage：小组赛completed = 有比赛 + 全部 FINISHED + 没有 WAITING/PLAYING
        "group_stage_completed": (
            group_total > 0
            and len(finished_group) == group_total
            and len(waiting_group) == 0
            and len(playing_group) == 0
        ),
        "free_table_recommendations": [
            tb["recommended_match_id"] for tb in dash["tables"] if tb["match"] is None
        ],
    }


def _knockout_state(client, tid: int) -> dict:
    """复刻 KnockoutPage 的 knockoutReady / groupsAllDone / awaitingBracket 判定所需字段。"""
    tree = client.get(f"/api/tournaments/{tid}/knockout").json()
    rankings = client.get(f"/api/tournaments/{tid}/rankings").json()
    groups = rankings["rankings"]
    groups_all_done = len(groups) > 0 and all(
        g["finished_matches"] == g["total_matches"] and g["total_matches"] > 0 for g in groups
    )
    knockout_ready = len(tree["rounds"]) > 0
    return {
        "groups": len(groups),
        "groups_all_done": groups_all_done,
        "knockout_ready": knockout_ready,
        "awaiting_bracket": groups_all_done and not knockout_ready,
        "remaining_group_matches": sum(g["total_matches"] - g["finished_matches"] for g in groups),
        "qualifier_count": sum(1 for g in groups for e in g["entries"] if e["qualified"]),
        "ambiguous": any(g["ambiguous_qualification"] for g in groups),
        "round_labels": [r["label"] for r in tree["rounds"]],
        "rounds": [len(r["matches"]) for r in tree["rounds"]],
    }


# ----------------------------------------------------------------- 场景1

def test_scenario_group_stage_running(client):
    """场景1：16 人 / 4 组 / 4 台，小组赛未打完。"""
    tid, generated = _group_stage_tournament(client, "场景1-小组赛进行中")
    assert generated == 24
    _play_group_rounds(client, tid, stop_after=6)

    console = _console_state(client, tid)
    # Console：仍然允许排台
    assert console["group_stage_completed"] is False
    assert console["waiting_group"] > 0
    assert console["stage"] == "GROUP_STAGE"
    # 空闲球台仍然拿得到服务端的安排建议（"安排比赛"按钮可用）
    assert any(r is not None for r in console["free_table_recommendations"])

    knockout = _knockout_state(client, tid)
    # Knockout：显示"小组赛尚未完成"，不得出现生成入口
    assert knockout["groups_all_done"] is False
    assert knockout["knockout_ready"] is False
    assert knockout["awaiting_bracket"] is False
    assert knockout["remaining_group_matches"] == 24 - 6

    # 后端确实拒绝生成（前端不应该给出生成按钮）
    rejected = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert rejected.status_code == 409
    assert "小组赛尚未全部结束" in rejected.json()["detail"]


# ----------------------------------------------------------------- 场景2

def test_scenario_group_stage_completed_without_knockout(client):
    """场景2：小组赛全部完成、淘汰赛尚未生成（过渡窗口）。"""
    tid, _ = _group_stage_tournament(client, "场景2-小组赛完成")
    _play_group_rounds(client, tid)

    console = _console_state(client, tid)
    assert console["group_stage_completed"] is True
    assert console["stats"] == {"total": 24, "finished": 24, "playing": 0, "waiting": 0}
    assert console["finished_group"] == console["group_total"] == 24
    assert console["stage"] == "GROUP_STAGE"          # stage 仍是 GROUP_STAGE：不能靠它判断
    assert console["free_table_recommendations"] == [None] * TABLE_COUNT  # 没有可安排的比赛

    knockout = _knockout_state(client, tid)
    assert knockout["groups_all_done"] is True
    assert knockout["knockout_ready"] is False
    assert knockout["awaiting_bracket"] is True       # → 显示"可以生成淘汰赛" + 生成按钮
    assert knockout["remaining_group_matches"] == 0
    assert knockout["qualifier_count"] == GROUP_COUNT * QUALIFY
    assert knockout["ambiguous"] is False

    # 生成确实可用（前端显示按钮不会点出错误）
    created = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert created.status_code == 200, created.text


def test_scenario_transition_window_survives_refresh(client):
    """过渡窗口里的判定在重复刷新（GET）时保持稳定，不会一会儿允许一会儿不允许。"""
    tid, _ = _group_stage_tournament(client, "场景2-刷新稳定")
    _play_group_rounds(client, tid)
    for _ in range(3):
        assert _console_state(client, tid)["group_stage_completed"] is True
        assert _knockout_state(client, tid)["awaiting_bracket"] is True


# ----------------------------------------------------------------- 场景3

def test_scenario_knockout_created(client):
    """场景3：淘汰赛生成后 → 展示签表，且不再显示"可以生成"。"""
    tid, _ = _group_stage_tournament(client, "场景3-淘汰赛已生成")
    _play_group_rounds(client, tid)
    assert client.post(f"/api/tournaments/{tid}/generate-knockout").status_code == 200

    knockout = _knockout_state(client, tid)
    assert knockout["knockout_ready"] is True
    assert knockout["awaiting_bracket"] is False      # 生成按钮不再出现
    assert knockout["groups_all_done"] is True         # 但小组赛确实已完成（横幅仍可显示）
    assert knockout["round_labels"] == ["8强赛", "半决赛", "决赛"]
    assert knockout["rounds"] == [4, 2, 1]

    console = _console_state(client, tid)
    # 进入淘汰赛后 stage 变成 KNOCKOUT：控制台必须恢复排台能力（不能被小组赛逻辑永久锁死）
    assert console["stage"] == "KNOCKOUT"
    assert console["stats"]["waiting"] == 7            # 8强4场 + 半决赛2场 + 决赛1场
    assert any(r is not None for r in console["free_table_recommendations"])


# ----------------------------------------------------------------- 边界

def test_empty_tournament_is_not_reported_as_completed(client):
    """total=0 的空赛事不得被判定成"小组赛已完成"。"""
    tid = _create_tournament(client, "空赛事", players=0, groups=GROUP_COUNT)
    console = _console_state(client, tid)
    assert console["group_total"] == 0
    assert console["group_stage_completed"] is False
    assert _knockout_state(client, tid)["groups_all_done"] is False


def test_tournament_with_groups_but_no_matches_is_not_completed(client):
    """已分组但还没生成小组赛：同样不算完成。"""
    tid = _create_tournament(client, "已分组未生成")
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200
    console = _console_state(client, tid)
    assert console["group_total"] == 0
    assert console["group_stage_completed"] is False
    assert _knockout_state(client, tid)["groups_all_done"] is False


def test_table_count_comes_from_configuration(client):
    """球台数量按赛事配置渲染：4 台赛事不得显示成 8 台，8 台赛事保持 8 台。"""
    four = _create_tournament(client, "四台", players=4, tables=4, groups=2)
    eight = _create_tournament(client, "八台", players=4, tables=8, groups=2)
    assert _console_state(client, four)["dashboard_tables"] == 4
    assert _console_state(client, eight)["dashboard_tables"] == 8
    assert _console_state(client, four)["table_count"] == 4
    assert _console_state(client, eight)["table_count"] == 8


@pytest.mark.parametrize("qualify", [1, 2, 3])
def test_qualify_per_group_is_used_as_configured(client, qualify):
    """前端文案取真实出线人数，不写死"每组前 2"；生成能力也不因配置不同而自相矛盾。"""
    tid, generated = _group_stage_tournament(
        client, f"每组前{qualify}", players=12, tables=4, groups=2, qualify=qualify
    )
    assert generated == 30  # 2 组 × 6 人 → 每组 15 场
    _play_group_rounds(client, tid)

    knockout = _knockout_state(client, tid)
    assert knockout["groups_all_done"] is True
    assert knockout["qualifier_count"] == 2 * qualify
    tree = client.get(f"/api/tournaments/{tid}/rankings").json()
    assert {g["qualify_count"] for g in tree["rankings"]} == {qualify}

    created = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert created.status_code == 200, created.text
    # 签表会向上补齐到 2 的幂：2 人 → 1 场；4 人 → 2 场；6 人 → 补齐 8 签 = 4 场（含轮空）。
    rounds = created.json()["rounds"]
    assert len(rounds) >= 1
    padded = 1
    while padded < 2 * qualify:
        padded *= 2
    assert len(rounds[0]["matches"]) == padded // 2
