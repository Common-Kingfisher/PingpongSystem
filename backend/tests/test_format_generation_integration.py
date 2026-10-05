"""V0.3 三赛制生成链路：统一入口 `POST /generate-matches` 与 legacy 小组入口的赛制边界。

本轮**没有**新增赛制，也没有重新实现任何比赛算法：三个 `FormatHandler.generate_matches()`
（`GROUP_KNOCKOUT` / `ROUND_ROBIN` / `SINGLE_ELIMINATION`）在 master 上已经存在。
本文件锁定的是把既有 Handler 接到正式 HTTP 入口之后的真实产品行为。

| # | 场景 | 期望 |
| --- | --- | --- |
| A | `ROUND_ROBIN` 正向 | 200 / 15 场 / `per_group == {}` / `GROUP_STAGE` |
| B | `ROUND_ROBIN` 重复生成 | 409 / 不产生重复 Match |
| C | `SINGLE_ELIMINATION` 正向 | 200 / 主签 7 场 / `KNOCKOUT`，且不经过小组阶段 |
| D | 非 2 幂（6 人） | 既有 Handler 产生 BYE → `WALKOVER` → 胜者传播 |
| E | `GROUP_KNOCKOUT` 走统一入口 | 复用既有 Handler，`per_group` 仍有值（证明真的 format-aware） |
| F | `format_code = null` | 422 / 0 Match / 阶段不变，不默认成 `GROUP_KNOCKOUT` |
| G | `TEAM` | 拒绝普通 Match 生成，且不创建任何 Match |
| H | legacy 跨赛制 | `ROUND_ROBIN` / `SINGLE_ELIMINATION` 上明确拒绝 |
"""

import pytest

from app.main import app

GENERATE_MATCHES = "/api/tournaments/{tid}/generate-matches"
GENERATE_GROUP_MATCHES = "/api/tournaments/{tid}/generate-group-matches"


# ----------------------------------------------------------------- 工具

def _create_tournament(
    client,
    name,
    *,
    event_type="SINGLES",
    format_code="GROUP_KNOCKOUT",
    players=16,
    tables=6,
    groups=4,
    qualify=2,
    rule_config=None,
):
    body = {
        "name": name,
        "date": "2026-10-02",
        "table_count": tables,
        "group_count": groups,
        "qualify_per_group": qualify,
        "event_type": event_type,
        "operation_mode": "LIVE",
    }
    # 刻意只在显式给出时才写 format_code：null 的历史赛事不能被默认成 GROUP_KNOCKOUT。
    if format_code is not None:
        body["format_code"] = format_code
    # SINGLE_ELIMINATION 的 draw_seed 决定 BYE 落在哪个半区；不给出时
    # `domain.draw` 用 `random.Random(None)`（系统熵）抽签，断言不能依赖具体落位。
    if rule_config is not None:
        body["rule_config"] = rule_config
    response = client.post("/api/tournaments", json=body)
    assert response.status_code == 201, response.text
    tid = response.json()["id"]
    for index in range(1, players + 1):
        created = client.post(
            f"/api/tournaments/{tid}/players", json={"name": f"选手{index:02d}"}
        )
        assert created.status_code == 201, created.text
    return tid


def _confirm_roster(client, tid: int) -> None:
    response = client.post(f"/api/tournaments/{tid}/confirm-roster")
    assert response.status_code == 200, response.text


def _matches(client, tid: int, stage: str | None = None) -> list[dict]:
    query = f"?stage={stage}" if stage else ""
    response = client.get(f"/api/tournaments/{tid}/matches{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _stage(client, tid: int) -> str:
    response = client.get(f"/api/tournaments/{tid}")
    assert response.status_code == 200, response.text
    return response.json()["stage"]


def _generate(client, tid: int, path: str = GENERATE_MATCHES):
    return client.post(path.format(tid=tid))


# ----------------------------------------------------------------- A. ROUND_ROBIN 正向

def test_round_robin_generate_matches_via_http(client):
    """6 人循环赛：15 场、无分组明细、赛事进入 GROUP_STAGE。"""
    tid = _create_tournament(
        client, "循环赛-正向", format_code="ROUND_ROBIN", players=6, tables=3, groups=1
    )
    _confirm_roster(client, tid)

    response = _generate(client, tid)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["matches_generated"] == 15  # 6 × 5 / 2
    assert data["per_group"] == {}
    assert data["tournament"]["stage"] == "GROUP_STAGE"
    assert data["tournament"]["format_code"] == "ROUND_ROBIN"

    matches = _matches(client, tid)
    assert len(matches) == 15
    assert all(m["stage"] == "GROUP" and m["status"] == "WAITING" for m in matches)
    # 单循环：每对参赛位恰好一次，且没有自对。
    pairs = {frozenset((m["entry_a_id"], m["entry_b_id"])) for m in matches}
    assert len(pairs) == 15
    assert all(m["entry_a_id"] != m["entry_b_id"] for m in matches)
    assert _stage(client, tid) == "GROUP_STAGE"


def test_round_robin_uses_active_entries_not_players(client):
    """参赛位是 Entry：生成结果必须落在 entry_a_id / entry_b_id 上。"""
    tid = _create_tournament(
        client, "循环赛-参赛位", format_code="ROUND_ROBIN", players=4, tables=2, groups=1
    )
    _confirm_roster(client, tid)
    assert _generate(client, tid).status_code == 200

    entries = client.get(f"/api/tournaments/{tid}/entries").json()
    assert len(entries) == 4
    assert {entry["id"] for entry in entries} >= {
        match["entry_a_id"] for match in _matches(client, tid)
    }


# ----------------------------------------------------------------- B. 重复生成

def test_round_robin_duplicate_generation_is_rejected(client):
    """第二次调用必须被拒绝，且不产生任何重复 Match。"""
    tid = _create_tournament(
        client, "循环赛-重复", format_code="ROUND_ROBIN", players=6, tables=3, groups=1
    )
    _confirm_roster(client, tid)
    assert _generate(client, tid).status_code == 200

    again = _generate(client, tid)
    assert again.status_code == 409, again.text
    assert "已生成" in again.json()["detail"]

    assert len(_matches(client, tid)) == 15
    assert _stage(client, tid) == "GROUP_STAGE"


# ----------------------------------------------------------------- C. SINGLE_ELIMINATION 正向

def test_single_elimination_generate_matches_via_http(client):
    """8 人单淘汰：主签 7 场、直接进入 KNOCKOUT，不经过小组阶段。"""
    tid = _create_tournament(
        client, "单淘汰-正向", format_code="SINGLE_ELIMINATION",
        players=8, tables=4, groups=1,
    )
    _confirm_roster(client, tid)

    response = _generate(client, tid)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["matches_generated"] == 7  # 4 + 2 + 1
    assert data["per_group"] == {}
    assert data["tournament"]["stage"] == "KNOCKOUT"

    # 关键边界：单淘汰没有小组赛，也不调用 /generate-knockout。
    assert _matches(client, tid, stage="GROUP") == []
    knockout = _matches(client, tid, stage="KNOCKOUT")
    assert all(m["bracket"] == "MAIN" for m in knockout)
    assert [len([m for m in knockout if m["round"] == r]) for r in (1, 2, 3)] == [4, 2, 1]

    tree = client.get(f"/api/tournaments/{tid}/knockout").json()
    assert [round_["round"] for round_ in tree["rounds"]] == [1, 2, 3]
    assert tree["rounds"][0]["label"] == "8强赛"
    assert tree["rounds"][2]["label"] == "决赛"


def test_single_elimination_duplicate_generation_is_rejected(client):
    tid = _create_tournament(
        client, "单淘汰-重复", format_code="SINGLE_ELIMINATION",
        players=8, tables=4, groups=1,
    )
    _confirm_roster(client, tid)
    assert _generate(client, tid).status_code == 200

    again = _generate(client, tid)
    assert again.status_code == 409, again.text
    assert len(_matches(client, tid, stage="KNOCKOUT")) == 7


# ----------------------------------------------------------------- D. 非 2 幂 → BYE

def test_single_elimination_six_entries_produce_bye_walkovers(client):
    """6 人扩展到 8 签位：BYE 由既有 Handler 记为 WALKOVER 并推进胜者。

    router 不参与 BYE 计算；这里断言的是既有 `_persist_main_bracket` 行为
    在经过新入口后仍然生效。

    ⚠️ 回归修复（PR #68 review 返工时发现）：`draw_seed = None` 时
    `domain.draw.build_single_elimination` 使用 `random.Random(None)`（系统熵）抽签，
    BYE 落在哪个半区是随机的 —— 旧断言"第二轮两场都恰好只填一侧"只在两个 BYE
    分处不同半区时成立（实测 pristine HEAD 20 次里失败 4 次）。
    现在固定 `draw_seed` 保证可复现，并把断言改为与抽签落位无关的**真实不变量**：
    每个轮空胜者必须真的被传播进第二轮签位。
    """
    tid = _create_tournament(
        client, "单淘汰-六人", format_code="SINGLE_ELIMINATION",
        players=6, tables=3, groups=1,
        rule_config={"draw_seed": 20261005},
    )
    _confirm_roster(client, tid)

    response = _generate(client, tid)
    assert response.status_code == 200, response.text
    assert response.json()["matches_generated"] == 7
    assert response.json()["tournament"]["stage"] == "KNOCKOUT"

    knockout = _matches(client, tid, stage="KNOCKOUT")
    walkovers = [m for m in knockout if m["result_type"] == "WALKOVER"]
    assert len(walkovers) == 2
    assert all(m["round"] == 1 and m["status"] == "FINISHED" for m in walkovers)
    # 轮空不计逐局小分，也不是"正常比赛比分"。
    assert all(m["games"] == [] for m in walkovers)
    # 空签的一侧确实为空，另一侧是真实参赛位。
    assert all((m["entry_a_id"] is None) != (m["entry_b_id"] is None) for m in walkovers)

    # 胜者传播（与抽签落位无关）：两个轮空胜者必须都进入第二轮签位。
    round_two = [m for m in knockout if m["round"] == 2]
    assert len(round_two) == 2
    bye_winners = {m["winner_entry_id"] for m in walkovers}
    assert None not in bye_winners and len(bye_winners) == 2
    round_two_slots = {
        entry_id
        for m in round_two
        for entry_id in (m["entry_a_id"], m["entry_b_id"])
    }
    assert bye_winners <= round_two_slots


# ----------------------------------------------------------------- E. GROUP_KNOCKOUT 走统一入口

def test_group_knockout_generic_endpoint_reuses_existing_handler(client):
    """统一入口对 GROUP_KNOCKOUT 同样有效：证明它是 format-aware，而非只补两种赛制。"""
    tid = _create_tournament(
        client, "小组淘汰-统一入口", format_code="GROUP_KNOCKOUT",
        players=16, tables=6, groups=4, qualify=2,
    )
    _confirm_roster(client, tid)
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200

    response = _generate(client, tid)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["matches_generated"] == 24  # 4 组 × 4 人 × 6 场
    assert data["per_group"] == {"A组": 6, "B组": 6, "C组": 6, "D组": 6}
    assert data["tournament"]["stage"] == "GROUP_STAGE"
    assert len(_matches(client, tid, stage="GROUP")) == 24


def test_group_knockout_generic_endpoint_keeps_existing_guards(client):
    """统一入口不得绕过既有守卫：没有分组时仍是既有的 409 文案。"""
    tid = _create_tournament(
        client, "小组淘汰-未分组", format_code="GROUP_KNOCKOUT",
        players=8, tables=4, groups=2, qualify=2,
    )
    _confirm_roster(client, tid)

    response = _generate(client, tid)
    assert response.status_code == 409, response.text
    assert "分组" in response.json()["detail"]
    assert _matches(client, tid) == []
    assert _stage(client, tid) == "REGISTRATION"


# ----------------------------------------------------------------- F. format_code = null

def test_missing_format_code_is_rejected_without_generating(client):
    """未设置赛制时不得生成任何比赛，也不得默认成 GROUP_KNOCKOUT。"""
    tid = _create_tournament(
        client, "未设置赛制", format_code=None, players=4, tables=2, groups=1
    )
    _confirm_roster(client, tid)

    response = _generate(client, tid)
    assert response.status_code == 422, response.text
    assert "赛制" in response.json()["detail"]

    assert _matches(client, tid) == []
    assert _stage(client, tid) == "REGISTRATION"
    assert client.get(f"/api/tournaments/{tid}").json()["format_code"] is None


# ----------------------------------------------------------------- G. TEAM

def test_team_tournament_never_generates_individual_matches(client):
    """团体赛不使用个人赛 Handler：两条生成入口都不得产生普通 Match。"""
    tid = _create_tournament(
        client, "团体赛", event_type="TEAM", format_code=None,
        players=0, tables=2, groups=1, qualify=1,
    )
    assert client.get(f"/api/tournaments/{tid}").json()["format_code"] is None

    # 团体赛连个人赛赛制都写不进去（既有 Handler 边界）。
    rejected_format = client.put(
        f"/api/tournaments/{tid}/format",
        json={"format_code": "GROUP_KNOCKOUT", "rule_config": {}},
    )
    assert rejected_format.status_code == 409, rejected_format.text
    assert "团体赛" in rejected_format.json()["detail"]

    # 统一入口：无赛制 → 拒绝。
    generic = _generate(client, tid)
    assert generic.status_code == 422, generic.text

    # legacy 小组入口：由既有 service 拒绝团体赛。
    legacy = _generate(client, tid, GENERATE_GROUP_MATCHES)
    assert legacy.status_code == 409, legacy.text
    assert "团体赛" in legacy.json()["detail"]

    assert _matches(client, tid) == []
    assert client.get(f"/api/tournaments/{tid}/team-ties").json() == []


# ----------------------------------------------------------------- H. legacy 跨赛制守卫

@pytest.mark.parametrize("format_code", ["ROUND_ROBIN", "SINGLE_ELIMINATION"])
def test_legacy_group_endpoint_rejects_cross_format(client, format_code):
    """旧的小组生成入口不得被其它赛制借用 —— 即使已经建好分组。"""
    tid = _create_tournament(
        client, f"跨赛制-{format_code}", format_code=format_code,
        players=6, tables=3, groups=1,
    )
    _confirm_roster(client, tid)
    # 分组本身对任何个人赛赛制都合法，所以"有分组"不能成为放行理由。
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200

    response = _generate(client, tid, GENERATE_GROUP_MATCHES)
    assert response.status_code == 409, response.text
    assert format_code in response.json()["detail"]

    assert _matches(client, tid) == []
    assert _stage(client, tid) == "REGISTRATION"


def test_legacy_group_endpoint_still_serves_group_knockout(client):
    """ROUND_ROBIN / SINGLE_ELIMINATION 之外，legacy 入口主链不退化。"""
    tid = _create_tournament(
        client, "小组淘汰-legacy", format_code="GROUP_KNOCKOUT",
        players=8, tables=4, groups=2, qualify=2,
    )
    _confirm_roster(client, tid)
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200

    response = _generate(client, tid, GENERATE_GROUP_MATCHES)
    assert response.status_code == 200, response.text
    assert response.json()["matches_generated"] == 12
    assert response.json()["per_group"] == {"A组": 6, "B组": 6}
    assert _stage(client, tid) == "GROUP_STAGE"


def test_legacy_group_endpoint_keeps_historical_null_format_behavior(client):
    """`format_code = null` 的历史赛事仍可使用旧入口 —— 本轮不改写其历史语义。

    新入口（`/generate-matches`）对未设置赛制是**显式拒绝**；旧入口在本轮之前
    就一直服务于未登记赛制的历史赛事，且既有测试 / D6D harness 依赖它，因此
    这里只加"不得跨到其它已声明赛制"的最小守卫。
    """
    tid = _create_tournament(
        client, "历史赛事-未设置赛制", format_code=None,
        players=6, tables=3, groups=1,
    )
    _confirm_roster(client, tid)
    assert client.post(f"/api/tournaments/{tid}/auto-group").status_code == 200

    response = _generate(client, tid, GENERATE_GROUP_MATCHES)
    assert response.status_code == 200, response.text
    assert response.json()["matches_generated"] == 15
    assert response.json()["tournament"]["format_code"] is None
    assert _stage(client, tid) == "GROUP_STAGE"


# ----------------------------------------------------------------- 404 语义

@pytest.mark.parametrize(
    "path", [GENERATE_MATCHES, GENERATE_GROUP_MATCHES]
)
def test_nonexistent_tournament_is_404(client, path):
    """失效 tid 沿用既有 404，不得因 `None["format_code"]` 变成 500。"""
    response = _generate(client, 999999, path)
    assert response.status_code == 404, response.text


# ----------------------------------------------------------------- 契约

def test_generate_matches_endpoint_is_in_openapi_contract():
    """前端不得只靠硬编码 URL：新入口必须在 OpenAPI 契约里。"""
    schema = app.openapi()
    operation = schema["paths"]["/api/tournaments/{tournament_id}/generate-matches"]["post"]
    assert operation["operationId"] == (
        "generate_matches_api_tournaments__tournament_id__generate_matches_post"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/GenerateMatchesResult"
    }
    # legacy 入口必须同时保留。
    assert "/api/tournaments/{tournament_id}/generate-group-matches" in schema["paths"]
