"""C-D5 Phase 2：阶段完成状态必须由后端赛制 Handler 提供，前端不得自行推断。

## 背景（这就是本文件要防住的回归）

`ConsolePage` 曾经自己统计"小组赛总场数 / 已结束场数"，再配合 `Tournament.stage`
推断"下一阶段是不是淘汰赛"。这在三种赛制下都会给出**错误入口**：

- `ROUND_ROBIN`：循环赛打完后被诱导"进入淘汰赛"（循环赛根本没有淘汰阶段）；
- `SINGLE_ELIMINATION`：不存在小组阶段，却被说成"小组赛尚未完成"；
- `format_code = null` 的历史赛事：被静默默认成小组淘汰。

C-D5 收口把唯一权威固定为 `services/formats.py` 各 Handler 的 `get_completion_state`，
并通过 `GET /api/tournaments/{id}/dashboard` 的 `completion` 字段只读透传。
前端 `frontend/src/fieldOps.ts::completionNotice` 只消费该状态做文案映射。

## 本文件锁定的内容

1. `completion` 的字段形状与取值来源（`format_code` / `state` / `can_advance` / `completed`）；
2. 小组淘汰在三个验收场景下的真实推进（进行中 → 可生成 → 已生成）；
3. 循环赛**永远**不报告 `can_advance=True`；
4. 单淘汰不伪造小组阶段；
5. 团体赛与未设置赛制返回 `NOT_APPLICABLE`，不猜成小组淘汰；
6. 该字段是只读的：重复读取不改变任何比赛/球台/阶段事实。
"""

import sqlite3

import pytest

from app import repository as repo
from app.services import formats as formats_service
from app.services import scheduling as scheduling_service

GROUP_COUNT = 4
QUALIFY = 2


# ----------------------------------------------------------------- 工具

def _create_tournament(client, name, *, event_type="SINGLES", format_code="GROUP_KNOCKOUT",
                       players=16, tables=6, groups=GROUP_COUNT, qualify=QUALIFY, mode="LIVE"):
    body = {
        "name": name,
        "date": "2026-10-01",
        "table_count": tables,
        "group_count": groups,
        "qualify_per_group": qualify,
        "event_type": event_type,
        "operation_mode": mode,
    }
    # 刻意只在显式给出时才写 format_code：null 的历史赛事不能被默认成 GROUP_KNOCKOUT。
    if format_code is not None:
        body["format_code"] = format_code
    tid = client.post("/api/tournaments", json=body).json()["id"]
    for index in range(1, players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{index:02d}"})
    return tid


def _completion(client, tid: int) -> dict:
    return client.get(f"/api/tournaments/{tid}/dashboard").json()["completion"]


def _play_matches(client, tid: int, *, stop_after: int | None = None) -> int:
    """调度 + 录分（id 小者 2:0 胜，可复现），直到没有可安排的比赛。"""
    done = 0
    for _ in range(300):
        if stop_after is not None and done >= stop_after:
            break
        client.post(f"/api/tournaments/{tid}/schedule-next")
        dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [t["match"] for t in dash["tables"] if t["match"]]
        if not playing:
            break
        for match in playing:
            if stop_after is not None and done >= stop_after:
                return done
            winner_is_a = match["player_a_id"] < match["player_b_id"]
            resp = client.post(
                f"/api/matches/{match['id']}/score",
                json={
                    "player_a_score": 2 if winner_is_a else 0,
                    "player_b_score": 0 if winner_is_a else 2,
                },
            )
            assert resp.status_code == 200, resp.text
            done += 1
    return done


# ----------------------------------------------------------------- 字段契约

def test_dashboard_exposes_completion_contract(client):
    """`completion` 是 Dashboard 的必备字段，且取值只能来自赛制 Handler。"""
    tid = _create_tournament(client, "契约-字段形状")
    completion = _completion(client, tid)
    assert set(completion) == {"format_code", "state", "can_advance", "completed"}
    assert completion["format_code"] == "GROUP_KNOCKOUT"
    # 注意：小组淘汰的"尚未生成"是 GROUP_MATCHES_NOT_GENERATED，
    # 与循环赛/单淘汰的 MATCHES_NOT_GENERATED 是两个不同字符串。
    assert completion["state"] == "GROUP_MATCHES_NOT_GENERATED"
    assert completion["can_advance"] is False
    assert completion["completed"] is False


def test_public_readers_get_the_same_completion(client):
    """公开只读依赖也能拿到同一份状态（Dashboard 本来就是 public read）。"""
    tid = _create_tournament(client, "契约-public")
    response = client.get(f"/api/tournaments/{tid}/dashboard")
    assert response.status_code == 200
    assert response.json()["completion"]["state"] == "GROUP_MATCHES_NOT_GENERATED"


# ----------------------------------------------------------------- 小组淘汰三场景

def test_group_knockout_completion_across_three_scenarios(client):
    """进行中 → 可生成淘汰签 → 淘汰赛进行中，三个场景的状态必须逐段正确。"""
    tid = _create_tournament(client, "场景-小组淘汰")
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200
    generated = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert generated.status_code == 200, generated.text
    assert generated.json()["matches_generated"] == 24

    # 场景1：小组赛进行中
    _play_matches(client, tid, stop_after=6)
    running = _completion(client, tid)
    assert running["state"] == "GROUP_STAGE_IN_PROGRESS"
    assert running["can_advance"] is False
    assert running["completed"] is False

    # 场景2：小组赛全部完成、淘汰签尚未生成 —— 唯一的 can_advance=True 窗口
    _play_matches(client, tid)
    ready = _completion(client, tid)
    assert ready["state"] == "KNOCKOUT_READY"
    assert ready["can_advance"] is True
    assert ready["completed"] is False
    stats = client.get(f"/api/tournaments/{tid}/dashboard").json()["stats"]
    assert stats == {"total": 24, "finished": 24, "playing": 0, "waiting": 0}

    # 场景3：淘汰赛生成后恢复排台能力，且不再报告可推进
    assert client.post(f"/api/tournaments/{tid}/generate-knockout").status_code == 200
    knockout = _completion(client, tid)
    assert knockout["state"] == "KNOCKOUT_IN_PROGRESS"
    assert knockout["can_advance"] is False
    assert knockout["completed"] is False
    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert dashboard["stats"]["waiting"] == 7
    assert dashboard["tournament"]["stage"] == "KNOCKOUT"


def test_group_knockout_completion_is_not_derivable_from_stage_alone(client):
    """场景2 里 `stage` 仍是 GROUP_STAGE —— 证明不能靠 stage 推断阶段是否结束。"""
    tid = _create_tournament(client, "场景-不能靠-stage")
    client.post(f"/api/tournaments/{tid}/confirm-roster")
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    _play_matches(client, tid)

    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert dashboard["tournament"]["stage"] == "GROUP_STAGE"
    assert dashboard["completion"]["state"] == "KNOCKOUT_READY"
    assert dashboard["completion"]["can_advance"] is True


def test_unresolved_qualification_blocks_advance_and_is_reported(client):
    """小组内出现真实三循环并列时：后端必须报告"不可推进"，前端据此不得给出淘汰赛入口。

    构造方式（4 人 1 组，每组出线 2 人，只录大比分、不带逐局小分）：

    ```text
    索引 3 全负；索引 0/1/2 互相形成 0>1>2>0 的三循环
    → 0/1/2 各 2 胜 1 负且行政比分完全相同 = 无法自动判定的并列
    ```

    这正是"主裁现场只录大比分"时可能遇到的真实情形：前端**不得**因为
    "24 场都打完了"就自行开放淘汰赛，必须原样显示后端阻断原因。
    """
    tid = _create_tournament(
        client, "并列无法判定", players=4, tables=2, groups=1, qualify=2
    )
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200
    assert client.post(f"/api/tournaments/{tid}/generate-group-matches").status_code == 200

    entries = client.get(f"/api/tournaments/{tid}/entries").json()
    index_of = {entry["id"]: index for index, entry in enumerate(sorted(entries, key=lambda e: e["id"]))}

    def winner_index(a: int, b: int | None) -> int:
        if b is None or b == 3:
            return a
        if a == 3:
            return b
        if (a + 1) % 3 == b:
            return a
        if (b + 1) % 3 == a:
            return b
        raise AssertionError(f"未覆盖的对阵: {a} vs {b}")

    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    assert len(matches) == 6
    for match in matches:
        a = index_of[match["entry_a_id"] if match["entry_a_id"] is not None else match["player_a_id"]]
        b = index_of[match["entry_b_id"] if match["entry_b_id"] is not None else match["player_b_id"]]
        a_wins = winner_index(a, b) == a
        resp = client.post(
            f"/api/matches/{match['id']}/score",
            json={"player_a_score": 2 if a_wins else 0, "player_b_score": 0 if a_wins else 2},
        )
        assert resp.status_code == 200, resp.text

    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert dashboard["stats"]["finished"] == 6
    assert dashboard["completion"]["state"] == "QUALIFICATION_UNRESOLVED"
    assert dashboard["completion"]["can_advance"] is False
    assert dashboard["completion"]["completed"] is False

    # 后备事实：后端确实拒绝推进（所以前端显示"不能进入淘汰赛"不是前后端不一致）
    rejected = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert rejected.status_code == 409
    assert "并列" in rejected.json()["detail"] or "判定" in rejected.json()["detail"]

    # 且排名页确实标出了并列，前端可以据此引导主裁去处理
    rankings = client.get(f"/api/tournaments/{tid}/rankings").json()["rankings"]
    assert any(group["ambiguous_qualification"] for group in rankings)


# ----------------------------------------------------------------- 循环赛

def _generate_round_robin(client, conn, name: str) -> int:
    """循环赛目前没有 HTTP 生成入口（B 轨待办），因此直接走赛制 Handler 的权威路径。"""
    tid = _create_tournament(client, name, format_code="ROUND_ROBIN", players=6, tables=3, groups=1)
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    handler = formats_service.resolve_format_handler("ROUND_ROBIN")
    assert handler.generate_matches(conn, tid).matches_generated == 15
    return tid


def test_round_robin_never_offers_knockout_advance(client, conn):
    """循环赛在任何阶段都不得报告 can_advance=True，也不得出现淘汰赛入口。"""
    tid = _generate_round_robin(client, conn, "循环赛-推进")

    running = _completion(client, tid)
    assert running["format_code"] == "ROUND_ROBIN"
    assert running["state"] == "ROUND_ROBIN_IN_PROGRESS"
    assert running["can_advance"] is False
    assert running["completed"] is False

    _play_matches(client, tid)
    finished = _completion(client, tid)
    assert finished["state"] == "COMPLETED"
    assert finished["completed"] is True
    # 关键断言：循环赛结束后前端**不得**出现"进入淘汰赛"
    assert finished["can_advance"] is False


def test_round_robin_stage_advances_to_finished(client, conn):
    """循环赛全部完成后赛事生命周期同步到 FINISHED（后端 sync，不是前端推断）。"""
    tid = _generate_round_robin(client, conn, "循环赛-生命周期")
    _play_matches(client, tid)
    tournament = client.get(f"/api/tournaments/{tid}").json()
    assert tournament["stage"] == "FINISHED"
    assert _completion(client, tid)["state"] == "COMPLETED"


def test_round_robin_before_generation_reports_matches_not_generated(client):
    """尚未生成循环赛时是 MATCHES_NOT_GENERATED，不是"小组赛"、也不是"可推进"。"""
    tid = _create_tournament(client, "循环赛-未生成", format_code="ROUND_ROBIN", players=6, tables=3, groups=1)
    completion = _completion(client, tid)
    assert completion["state"] == "MATCHES_NOT_GENERATED"
    assert completion["can_advance"] is False
    assert completion["completed"] is False


# ----------------------------------------------------------------- 单淘汰

def test_single_elimination_has_no_group_stage(client):
    """单淘汰没有小组阶段：未生成时只能报告"比赛尚未生成"。"""
    tid = _create_tournament(
        client, "单淘汰-未生成", format_code="SINGLE_ELIMINATION", players=8, tables=4, groups=1
    )
    completion = _completion(client, tid)
    assert completion["format_code"] == "SINGLE_ELIMINATION"
    assert completion["state"] == "MATCHES_NOT_GENERATED"
    assert completion["can_advance"] is False
    assert completion["completed"] is False


# ----------------------------------------------------------------- 边界

def test_team_tournament_completion_not_applicable(client):
    """团体赛使用独立链路：不得被塞进个人赛赛制的完成状态。

    团体赛创建时本身就不允许写 `format_code`（`GroupKnockoutHandler.validate_config`
    明确拒绝"团体赛不使用个人赛赛制处理器"），这里同时锁定这两条边界。
    """
    # 先锁定"团体赛 + 个人赛赛制"必须被拒绝，而不是静默接受。
    rejected = client.post("/api/tournaments", json={
        "name": "团体赛-非法赛制",
        "date": "2026-10-01",
        "table_count": 2,
        "group_count": 1,
        "qualify_per_group": 1,
        "event_type": "TEAM",
        "format_code": "GROUP_KNOCKOUT",
        "operation_mode": "LIVE",
    })
    assert rejected.status_code in (409, 422), rejected.text
    assert "团体赛" in rejected.text

    tid = _create_tournament(client, "团体赛", event_type="TEAM", format_code=None,
                             players=0, tables=2, groups=1)
    completion = _completion(client, tid)
    assert completion["format_code"] is None
    assert completion["state"] == "NOT_APPLICABLE"
    assert completion["can_advance"] is False
    assert completion["completed"] is False


def test_missing_format_code_is_not_defaulted_to_group_knockout(client):
    """D4A 冻结：`format_code=null` 的历史赛事不得默认成 GROUP_KNOCKOUT。"""
    tid = _create_tournament(client, "未设置赛制", format_code=None, players=4, tables=2, groups=1)
    tournament = client.get(f"/api/tournaments/{tid}").json()
    assert tournament["format_code"] is None
    completion = _completion(client, tid)
    assert completion["format_code"] is None
    assert completion["state"] == "NOT_APPLICABLE"
    assert completion["can_advance"] is False


def test_nonexistent_tournament_dashboard_is_404(client):
    """失效 tid 必须明确 404，不能无限 loading。"""
    assert client.get("/api/tournaments/999999/dashboard").status_code == 404


# ----------------------------------------------------------------- 非法 / 不可解析配置（PR #66 review）

def test_database_rejects_invalid_format_code_at_sql_level(client, conn):
    """先记录事实：正常写入路径**无法**产生非法 `format_code`（表级 CHECK 约束）。

    `app/db.py` 建表与 `app/migrations.py` 迁移路径都带：

    ```sql
    CHECK (format_code IS NULL OR format_code IN ('ROUND_ROBIN','SINGLE_ELIMINATION','GROUP_KNOCKOUT'))
    ```

    所以下面针对"枚举外 format_code"的防御分支只能在单元层构造。它防的是
    约束被后续迁移放宽、外部 DB 文件被替换、`PRAGMA ignore_check_constraints`
    等非正常路径 —— 属于 defense-in-depth，而不是当前可达路径。
    """
    tid = _create_tournament(client, "约束-非法赛制", format_code=None, players=2, groups=1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tournaments SET format_code = ? WHERE id = ?", ("UNKNOWN_FORMAT", tid))
    conn.rollback()
    # 回滚后赛事仍可用
    assert client.get(f"/api/tournaments/{tid}/dashboard").status_code == 200


@pytest.mark.parametrize("bad_format", ["UNKNOWN_FORMAT", "unknown", "RoundRobin", "GROUP-KNOCKOUT", ""])
def test_unresolvable_format_code_degrades_without_500(conn, bad_format):
    """枚举外 / 近似 / 空的 format_code 一律不得让 Dashboard 变成 500。

    此前实现会把非法值回填给 `DashboardCompletion.format_code`
    （声明为 `TournamentFormat | None`），触发 Pydantic 二次校验失败。
    一个字段的历史脏数据不该让主裁判看不到现场。
    """
    row_id = repo.create_tournament(conn, "防御分支", "2026-10-01", 2, 1, 1)["id"]
    conn.commit()

    completion = scheduling_service.resolve_completion_state(
        conn, {"id": row_id, "event_type": "SINGLES", "format_code": bad_format}
    )
    # 空串在业务上等同于"未设置赛制"
    assert completion["state"] == ("NOT_APPLICABLE" if bad_format == "" else "UNAVAILABLE")
    # 关键：非法值不得回填
    assert completion["format_code"] is None
    assert completion["can_advance"] is False
    assert completion["completed"] is False


def test_legal_format_code_with_invalid_config_keeps_format_and_reports_unavailable(client, conn):
    """合法 format_code + Handler 拒绝配置：保留合法赛制信息，只把状态降为 UNAVAILABLE。

    这是"修过头"的反向保护：不能因为要处理非法 format_code，就把合法赛制也抹成 null。
    """
    tid = _create_tournament(client, "合法赛制-非法配置")
    # GROUP_KNOCKOUT 只允许空 rule_config；写入未知键会让 validate_rule_config 抛
    # FormatHandlerError，从而走 UNAVAILABLE 分支。
    conn.execute("UPDATE tournaments SET rule_config = ? WHERE id = ?", ('{"unknown_key": 1}', tid))
    conn.commit()

    response = client.get(f"/api/tournaments/{tid}/dashboard")
    assert response.status_code == 200, response.text
    completion = response.json()["completion"]
    assert completion["state"] == "UNAVAILABLE"
    # 关键：合法赛制信息必须保留
    assert completion["format_code"] == "GROUP_KNOCKOUT"
    assert completion["can_advance"] is False
    assert completion["completed"] is False


@pytest.mark.parametrize("bad_format", ["", "unknown", "RoundRobin", "GROUP-KNOCKOUT"])
def test_format_code_matching_is_exact(client, conn, bad_format):
    """赛制匹配必须精确：大小写、连字符、空串等近似值都不得被当成合法赛制。"""
    tid = _create_tournament(client, f"近似赛制-{bad_format or 'empty'}")
    # 先证明这些近似值确实写不进库（表级 CHECK 约束）
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tournaments SET format_code = ? WHERE id = ?", (bad_format, tid))
    conn.rollback()

    # 再在单元层确认：即便绕过约束送进来，也必须收敛成 null + 明确状态
    row_id = repo.create_tournament(conn, f"近似-单元-{bad_format or 'empty'}", "2026-10-01", 2, 1, 1)["id"]
    conn.commit()
    completion = scheduling_service.resolve_completion_state(
        conn, {"id": row_id, "event_type": "SINGLES", "format_code": bad_format}
    )
    assert completion["format_code"] is None
    assert completion["state"] == ("NOT_APPLICABLE" if bad_format == "" else "UNAVAILABLE")
    assert completion["can_advance"] is False


def test_dashboard_completion_state_is_within_declared_contract(client, conn):
    """completion.state 必须始终落在声明的封闭取值集合内（含防御分支）。

    该集合与 `schemas.DashboardCompletionState` 一一对应；前端 `completionNotice`
    现在对未知状态走"无法识别赛事状态"兜底，所以后端**不得**悄无声息地跑出契约。
    """
    from typing import get_args

    from app import schemas

    declared = set(get_args(schemas.DashboardCompletionState))
    assert len(declared) == 13

    # 1) 通过真实接口可达的状态
    without_format = _create_tournament(client, "契约-未设置", format_code=None, players=2, groups=1)
    legal = _create_tournament(client, "契约-合法")
    for tid in (without_format, legal):
        state = client.get(f"/api/tournaments/{tid}/dashboard").json()["completion"]["state"]
        assert state in declared, f"tid={tid} 返回了契约外的 state: {state}"

    # 2) 防御分支产生的状态同样必须在契约内
    row_id = repo.create_tournament(conn, "契约-单元", "2026-10-01", 2, 1, 1)["id"]
    conn.commit()
    for synthetic in ("UNKNOWN_FORMAT", ""):
        state = scheduling_service.resolve_completion_state(
            conn, {"id": row_id, "event_type": "SINGLES", "format_code": synthetic}
        )["state"]
        assert state in declared, f"防御分支返回了契约外的 state: {state}"


def test_completion_reads_do_not_mutate_state(client):
    """`completion` 是只读观测：重复读取不得改变比赛、球台或阶段事实。"""
    tid = _create_tournament(client, "只读观测")
    client.post(f"/api/tournaments/{tid}/confirm-roster")
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    _play_matches(client, tid, stop_after=4)

    def snapshot() -> dict:
        dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
        return {
            "stage": dashboard["tournament"]["stage"],
            "stats": dashboard["stats"],
            "tables": [(t["id"], t["status"]) for t in dashboard["tables"]],
            "completion": dashboard["completion"],
        }

    before = snapshot()
    for _ in range(3):
        assert snapshot() == before


@pytest.mark.parametrize("state_key", ["state", "can_advance", "completed"])
def test_completion_field_types_are_stable(client, state_key):
    """字段类型固定，前端可以做穷尽 switch 而不需要运行时兜底。"""
    tid = _create_tournament(client, f"类型-{state_key}")
    completion = _completion(client, tid)
    if state_key == "state":
        assert isinstance(completion[state_key], str)
    else:
        assert isinstance(completion[state_key], bool)
