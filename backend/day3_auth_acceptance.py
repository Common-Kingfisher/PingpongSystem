"""D 轨 Day3 验收：**真实认证与赛事授权**下的后端契约验收。

替代原先基于“后端无 Auth”假设的 `day3_mobile_score_acceptance.ps1`。

## 覆盖内容

| 场景 | 期望 |
| --- | --- |
| A 已登录 + 有该赛事写权限（tournament OWNER） | `POST /api/matches/{id}/score` → 200，比分落库 |
| B 匿名（无 Cookie / Bearer） | 401 `AUTH_REQUIRED`，比赛状态不变 |
| C 已登录但无该赛事授权（另一赛事 Owner） | 404 `RESOURCE_NOT_FOUND`，比赛状态不变，不泄露资源是否存在 |
| D 正常录分（只大比分） | 200，`games` 为空（不伪造逐局） |
| E 大比分 + 完整逐局小比分 | 200，逐局落库正确 |
| F 非法比分（逐局与大比分不一致 / 平局 / 局制不符） | 422，服务端仍为唯一权威 |
| G 异常结果（弃权） | 200，`result_type` / `forfeit_entry_id` 落库，无逐局小分 |
| H 重复提交（同一 request_id） | 幂等，只有一次逻辑写入 |
| I 已结束比赛再次录分 | 409 |
| J `GET /api/v1/auth/me` | 返回当前用户与可管理赛事数 |

## 认证方式

全部走真实契约：真实 Bootstrap 建 SYSTEM_ADMIN → 真实 `POST /api/v1/system/users` 建 EVENT_ADMIN
→ 真实 `POST /api/v1/auth/login` 拿 Bearer token。**没有任何绕过**
（无 dependency override、无 TEST_MODE、无“本机/局域网放行”）。

用法（后端需已在 8099 运行，且数据库为独立验收库）：

    .\\.venv\\Scripts\\python.exe day3_auth_acceptance.py [base_url]
"""

from __future__ import annotations

import sys
import uuid

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

USER_A = ("d3-owner-a", "d3-owner-a-pass1", "D3 甲赛事管理员")
USER_B = ("d3-owner-b", "d3-owner-b-pass1", "D3 乙赛事管理员")

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")
    return ok


def new_uuid() -> str:
    return str(uuid.uuid4())


def build_tournament(client: AuthClient, name: str) -> tuple[int, list[dict]]:
    """真实创建赛事 + 6 名选手 + 2 组 + 小组赛，返回 (tid, matches)。"""
    created = client.post(
        "/api/tournaments",
        {
            "name": name,
            "date": "2026-01-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 1,
            "event_type": "SINGLES",
            "operation_mode": "LIVE",
            "games_to_win": 2,
            "points_to_win": 11,
        },
    )
    if created.status not in (200, 201):
        raise RuntimeError(f"创建赛事失败: HTTP {created.status} {created.body}")
    tid = created.body["id"]

    for index in range(6):
        added = client.post(f"/api/tournaments/{tid}/players", {"name": f"P{index + 1}"})
        if added.status not in (200, 201):
            raise RuntimeError(f"添加选手失败: HTTP {added.status} {added.body}")
    client.post(f"/api/tournaments/{tid}/auto-group")
    generated = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    if generated.status not in (200, 201):
        raise RuntimeError(f"生成小组赛失败: HTTP {generated.status} {generated.body}")

    matches = client.get(f"/api/tournaments/{tid}/matches").body
    return tid, matches


def match_of(client: AuthClient, tid: int, match_id: int) -> dict | None:
    for item in client.get(f"/api/tournaments/{tid}/matches").body or []:
        if item["id"] == match_id:
            return item
    return None


def main() -> int:
    print("=== 准备两个 EVENT_ADMIN（真实 bootstrap + 真实建号 + 真实登录）===")
    owner_a = provision_event_admin(BASE, *USER_A)
    owner_b = provision_event_admin(BASE, *USER_B)
    print(f"owner_a token: {owner_a.token[:8]}…  owner_b token: {owner_b.token[:8]}…")

    # ---------------------------------------------------------------- J
    me = owner_a.me()
    check(
        "J /api/v1/auth/me 返回当前用户",
        me.status == 200 and isinstance(me.body, dict) and me.body.get("user", {}).get("username") == USER_A[0],
        f"HTTP {me.status} user={me.body.get('user', {}).get('username') if isinstance(me.body, dict) else None}",
    )

    print()
    print("=== 建立两个互不相关的赛事（各自 Owner）===")
    tid_a, matches_a = build_tournament(owner_a, "D3 甲赛事（可删）")
    tid_b, _ = build_tournament(owner_b, "D3 乙赛事（可删）")
    print(f"tid_a={tid_a} matches={len(matches_a)}   tid_b={tid_b}")

    # ---------------------------------------------------------------- A
    print()
    print("=== A 已登录 + 有写权限 → 200 并落库 ===")
    match_a = matches_a[0]
    recorded = owner_a.post(
        f"/api/matches/{match_a['id']}/score",
        {
            "player_a_score": 2,
            "player_b_score": 1,
            "result_type": "NORMAL",
            "request_id": new_uuid(),
        },
    )
    check("A 授权用户录分被接受", recorded.status == 200, f"HTTP {recorded.status}")
    after_a = match_of(owner_a, tid_a, match_a["id"])
    check(
        "A 比赛 FINISHED 且比分落库",
        after_a is not None and after_a["status"] == "FINISHED"
        and after_a["player_a_score"] == 2 and after_a["player_b_score"] == 1,
        f"status={after_a['status'] if after_a else None} {after_a['player_a_score'] if after_a else None}:{after_a['player_b_score'] if after_a else None}",
    )
    check(
        "A 未伪造逐局小比分",
        after_a is not None and len(after_a["games"]) == 0,
        f"games={len(after_a['games']) if after_a else None}",
    )

    # ---------------------------------------------------------------- B
    print()
    print("=== B 匿名 → 401 AUTH_REQUIRED，比赛状态不变 ===")
    target = matches_a[1]
    anonymous = AuthClient(BASE)  # 无 Cookie、无 Bearer
    anon_resp = anonymous.post(
        f"/api/matches/{target['id']}/score",
        {"player_a_score": 2, "player_b_score": 0, "result_type": "NORMAL", "request_id": new_uuid()},
    )
    check("B 匿名录分被拒绝为 401", anon_resp.status == 401, f"HTTP {anon_resp.status}")
    check(
        "B 错误码为 AUTH_REQUIRED",
        anon_resp.detail_code == "AUTH_REQUIRED",
        f"code={anon_resp.detail_code} message={anon_resp.detail_message}",
    )
    still_waiting = match_of(owner_a, tid_a, target["id"])
    check(
        "B 比赛状态未被匿名请求改动",
        still_waiting is not None and still_waiting["status"] != "FINISHED"
        and still_waiting["player_a_score"] is None,
        f"status={still_waiting['status'] if still_waiting else None}",
    )

    # ---------------------------------------------------------------- C
    print()
    print("=== C 已登录但无该赛事授权 → 404 RESOURCE_NOT_FOUND，不泄露资源存在性 ===")
    cross = owner_b.post(
        f"/api/matches/{target['id']}/score",
        {"player_a_score": 2, "player_b_score": 0, "result_type": "NORMAL", "request_id": new_uuid()},
    )
    check("C 跨赛事录分被拒绝为 404", cross.status == 404, f"HTTP {cross.status}")
    check(
        "C 错误码为 RESOURCE_NOT_FOUND（防资源枚举）",
        cross.detail_code == "RESOURCE_NOT_FOUND",
        f"code={cross.detail_code} message={cross.detail_message}",
    )
    check(
        "C 响应体不泄露赛事/比赛是否存在",
        (cross.detail_message or "") == "资源不存在",
        f"message={cross.detail_message}",
    )
    untouched = match_of(owner_a, tid_a, target["id"])
    check(
        "C 比赛状态未被跨赛事请求改动",
        untouched is not None and untouched["status"] != "FINISHED"
        and untouched["player_a_score"] is None,
        f"status={untouched['status'] if untouched else None}",
    )

    # ---------------------------------------------------------------- D/E/F/G/H/I
    print()
    print("=== D–I 正常/小分/非法/异常/重复/已结束 ===")

    # D 只录大比分
    d_match = target
    d_resp = owner_a.post(
        f"/api/matches/{d_match['id']}/score",
        {"player_a_score": 2, "player_b_score": 1, "result_type": "NORMAL", "request_id": new_uuid()},
    )
    check("D 只录大比分被接受", d_resp.status == 200, f"HTTP {d_resp.status}")
    d_after = match_of(owner_a, tid_a, d_match["id"])
    check(
        "D 未携带逐局小比分",
        d_after is not None and len(d_after["games"]) == 0,
        f"games={len(d_after['games']) if d_after else None}",
    )

    # E 大比分 + 完整小分
    e_match = matches_a[2]
    e_resp = owner_a.post(
        f"/api/matches/{e_match['id']}/score",
        {
            "player_a_score": 2,
            "player_b_score": 1,
            "games": [
                {"side_a_score": 11, "side_b_score": 7},
                {"side_a_score": 9, "side_b_score": 11},
                {"side_a_score": 11, "side_b_score": 8},
            ],
            "result_type": "NORMAL",
            "request_id": new_uuid(),
        },
    )
    check("E 大比分 + 完整小分被接受", e_resp.status == 200, f"HTTP {e_resp.status}")
    e_after = match_of(owner_a, tid_a, e_match["id"])
    games_text = " / ".join(
        f"{g['side_a_score']}-{g['side_b_score']}" for g in (e_after["games"] if e_after else [])
    )
    check("E 逐局小分落库正确", games_text == "11-7 / 9-11 / 11-8", f"games={games_text}")

    # F 非法比分（服务端仍是唯一权威）
    f_match = matches_a[3]
    f_resp = owner_a.post(
        f"/api/matches/{f_match['id']}/score",
        {
            "player_a_score": 2,
            "player_b_score": 1,
            "games": [
                {"side_a_score": 7, "side_b_score": 11},
                {"side_a_score": 9, "side_b_score": 11},
            ],
            "result_type": "NORMAL",
            "request_id": new_uuid(),
        },
    )
    check("F 小分与大比分不一致被 422 拒绝", f_resp.status == 422, f"HTTP {f_resp.status} detail={f_resp.detail_message}")

    f2 = owner_a.post(
        f"/api/matches/{f_match['id']}/score",
        {"player_a_score": 2, "player_b_score": 2, "result_type": "NORMAL", "request_id": new_uuid()},
    )
    check("F 平局被 422 拒绝", f2.status == 422, f"HTTP {f2.status} detail={f2.detail_message}")

    f3 = owner_a.post(
        f"/api/matches/{f_match['id']}/score",
        {"player_a_score": 1, "player_b_score": 0, "result_type": "NORMAL", "request_id": new_uuid()},
    )
    check(
        "F 局制不符（2 局制填 1:0）被 422 拒绝",
        f3.status == 422,
        f"HTTP {f3.status} detail={f3.detail_message}",
    )
    f_after = match_of(owner_a, tid_a, f_match["id"])
    check(
        "F 被拒后比赛状态未变",
        f_after is not None and f_after["status"] != "FINISHED",
        f"status={f_after['status'] if f_after else None}",
    )

    # G 异常结果
    g_match = matches_a[4]
    forfeit_side = g_match.get("entry_b_id") or g_match.get("player_b_id")
    g_resp = owner_a.post(
        f"/api/matches/{g_match['id']}/score",
        {
            "result_type": "FORFEIT",
            "forfeit_entry_id": forfeit_side,
            "note": "验收：弃权",
            "request_id": new_uuid(),
        },
    )
    check("G 异常结果被接受", g_resp.status == 200, f"HTTP {g_resp.status}")
    g_after = match_of(owner_a, tid_a, g_match["id"])
    check(
        "G result_type / forfeit_entry_id 落库",
        g_after is not None and g_after["result_type"] == "FORFEIT"
        and g_after["forfeit_entry_id"] == forfeit_side,
        f"result_type={g_after['result_type'] if g_after else None} forfeit={g_after['forfeit_entry_id'] if g_after else None}",
    )
    check(
        "G 未生成逐局小分",
        g_after is not None and len(g_after["games"]) == 0,
        f"games={len(g_after['games']) if g_after else None}",
    )

    # H 重复提交（同 request_id）
    replay_payload = {
        "player_a_score": 2,
        "player_b_score": 0,
        "result_type": "NORMAL",
        "request_id": new_uuid(),
    }
    h_match = matches_a[5]
    first = owner_a.post(f"/api/matches/{h_match['id']}/score", replay_payload)
    replay = owner_a.post(f"/api/matches/{h_match['id']}/score", replay_payload)
    check("H 首次提交被接受", first.status == 200, f"HTTP {first.status}")
    check("H 同一 request_id 幂等重放返回 200", replay.status == 200, f"HTTP {replay.status}")
    audits = owner_a.get(f"/api/matches/{h_match['id']}/score-audits").body or []
    records = [a for a in audits if a.get("action") == "RECORD"]
    check("H 只有一条 RECORD（无重复写入）", len(records) == 1, f"RECORD={len(records)}")

    conflict = dict(replay_payload)
    conflict["player_b_score"] = 1
    conflict_resp = owner_a.post(f"/api/matches/{h_match['id']}/score", conflict)
    check(
        "H 同一 request_id 换载荷被 409 拒绝",
        conflict_resp.status == 409,
        f"HTTP {conflict_resp.status} detail={conflict_resp.detail_message}",
    )

    # I 已结束比赛
    i_resp = owner_a.post(
        f"/api/matches/{match_a['id']}/score",
        {"player_a_score": 2, "player_b_score": 0, "result_type": "NORMAL", "request_id": new_uuid()},
    )
    check("I 已结束比赛再次录分被 409 拒绝", i_resp.status == 409, f"HTTP {i_resp.status} detail={i_resp.detail_message}")

    # 匿名**只读**是 master 冻结的 Public 契约（require_public_tournament_read，
    # 见 PR #42 的 “Public 匿名只读” 修复）：匿名可以读实况/赛程/排名/签表，
    # 但**写入**必须被拒绝。这里显式记录这条边界，避免验收把只读开放误判成漏洞。
    anon_read = anonymous.get(f"/api/tournaments/{tid_a}/matches")
    check(
        "B2 匿名读取比赛列表按 Public 只读契约放行（200）",
        anon_read.status == 200,
        f"HTTP {anon_read.status}",
    )
    anon_rankings = anonymous.get(f"/api/tournaments/{tid_a}/rankings")
    check(
        "B3 匿名读取排名仍按 Public 只读契约放行",
        anon_rankings.status == 200,
        f"HTTP {anon_rankings.status}",
    )
    anon_write_guarded = anonymous.post(
        f"/api/tournaments/{tid_a}/players", {"name": "anon-should-fail"}
    )
    check(
        "B4 匿名写入（新增选手）被拒绝为 401",
        anon_write_guarded.status == 401
        and anon_write_guarded.detail_code == "AUTH_REQUIRED",
        f"HTTP {anon_write_guarded.status} code={anon_write_guarded.detail_code}",
    )

    print()
    failed = [name for ok, name, _ in results if not ok]
    print(f"=== summary: PASS={len(results) - len(failed)} FAIL={len(failed)} ===")
    if failed:
        print("failed: " + " | ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
