"""D 轨 Day5D 验收：**公开报名正式链路**（真实认证 + 真实 HTTP）。

## 覆盖内容

| 场景 | 期望 |
| --- | --- |
| A 管理员开启报名 | `PUT /api/tournaments/{tid}/registration {enabled:true}` → 200，`registration_enabled=true` |
| A2 匿名读取赛事 | `GET /api/tournaments/{tid}` → 200，可读到 `registration_enabled`，且响应**不含**联系方式字段 |
| B 匿名提交报名 | `POST /api/tournaments/{tid}/registrations` → 201，`status=PENDING` |
| B2 报名只是台账 | 提交前后 Player / Entry / Match 数量**完全不变** |
| B3 管理员查看待确认 | `GET /registrations?status=PENDING` → 1 条，含 contact（管理端可见） |
| C 管理员关闭报名 | `PUT {enabled:false}` → 200；匿名再提交 → 409 `REGISTRATION_CLOSED`，台账不增加 |
| D 匿名读取报名列表 | 401 `AUTH_REQUIRED`（Public 不得拉取报名列表 / 联系方式） |
| E 匿名确认报名 | 401（Public 不得确认入赛），且不产生 Player |
| F 越权确认（另一赛事管理员） | 404 `RESOURCE_NOT_FOUND`，台账仍为 PENDING |

## 认证方式

全部走真实契约：真实 Bootstrap → 真实 `POST /api/v1/system/users` → 真实登录。
**没有任何绕过**（无 dependency override、无 TEST_MODE、无本机放行）。

用法（后端需已在 8099 运行，且使用独立验收库）：

    .\\.venv\\Scripts\\python.exe day5d_registration_smoke.py [base_url]
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

ADMIN = ("d5d-admin", "d5d-admin-pass1", "D5D 报名验收管理员")
OTHER = ("d5d-other", "d5d-other-pass1", "D5D 他赛事管理员")

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")
    return ok


def counts(admin: AuthClient, tid: int) -> tuple[int, int, int]:
    """(players, entries, matches) —— Day5D 的核心不变量。"""
    players = admin.get(f"/api/tournaments/{tid}/players").body or []
    entries = admin.get(f"/api/tournaments/{tid}/entries").body or []
    matches = admin.get(f"/api/tournaments/{tid}/matches").body or []
    return len(players), len(entries), len(matches)


def main() -> int:
    print("=== 准备管理员（真实 bootstrap + 真实建号 + 真实登录）===")
    admin = provision_event_admin(BASE, *ADMIN)
    other = provision_event_admin(BASE, *OTHER)
    anon = AuthClient(BASE)
    print("admin / other / anon 就绪")

    created = admin.post(
        "/api/tournaments",
        {
            "name": "D5D 公开报名验收赛事",
            "date": "2026-01-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 2,
            "event_type": "SINGLES",
            "operation_mode": "LIVE",
            "games_to_win": 2,
            "points_to_win": 11,
        },
    )
    if created.status not in (200, 201):
        raise RuntimeError(f"创建赛事失败: HTTP {created.status} {created.body}")
    tid = created.body["id"]
    print(f"赛事 tid={tid}")

    before = counts(admin, tid)
    check("初始赛事无选手 / 无参赛单元 / 无比赛", before == (0, 0, 0), f"players/entries/matches={before}")

    # ----------------------------------------------------------------- A
    print("\n--- A 管理员开启报名 ---")
    enabled = admin.put(f"/api/tournaments/{tid}/registration", {"enabled": True})
    check(
        "A PUT /registration {enabled:true} → 200 且 registration_enabled=true",
        enabled.status == 200 and isinstance(enabled.body, dict) and enabled.body.get("registration_enabled") is True,
        f"HTTP {enabled.status} registration_enabled={enabled.body.get('registration_enabled') if isinstance(enabled.body, dict) else None}",
    )

    # ----------------------------------------------------------------- A2
    print("\n--- A2 匿名读取赛事（Public 可用） ---")
    public_tournament = anon.get(f"/api/tournaments/{tid}")
    body = public_tournament.body if isinstance(public_tournament.body, dict) else {}
    check(
        "A2 匿名 GET /tournaments/{tid} → 200 且可读到 registration_enabled",
        public_tournament.status == 200 and body.get("registration_enabled") is True,
        f"HTTP {public_tournament.status} registration_enabled={body.get('registration_enabled')}",
    )
    check(
        "A2 匿名赛事 DTO 不泄露任何联系方式字段",
        not ({"contact", "contact_name"} & set(body.keys())),
        f"keys={sorted(body.keys())}",
    )

    # ----------------------------------------------------------------- B
    print("\n--- B 匿名提交报名 ---")
    submitted = anon.post(
        f"/api/tournaments/{tid}/registrations",
        {"name": "张三", "affiliation": "XX学院", "contact": "13800000000", "rating_points": 1200},
    )
    payload = submitted.body if isinstance(submitted.body, dict) else {}
    registration_id = payload.get("registration_id")
    check(
        "B POST /registrations → 201 且 status=PENDING",
        submitted.status == 201 and payload.get("status") == "PENDING",
        f"HTTP {submitted.status} body={payload}",
    )
    check(
        "B Public 回执只含 registration_id/status/name/created_at（不回显联系方式）",
        set(payload.keys()) == {"registration_id", "status", "name", "created_at"},
        f"keys={sorted(payload.keys())}",
    )

    # ----------------------------------------------------------------- B2
    after = counts(admin, tid)
    check(
        "B2 报名只落台账：Player / Entry / Match 数量不变（核心不变量）",
        after == before,
        f"before={before} after={after}",
    )

    # ----------------------------------------------------------------- B3
    pending = admin.get(f"/api/tournaments/{tid}/registrations?status=PENDING")
    pending_rows = pending.body if isinstance(pending.body, list) else []
    check(
        "B3 管理员 GET /registrations?status=PENDING → 1 条待确认，且含 contact",
        pending.status == 200 and len(pending_rows) == 1 and pending_rows[0].get("contact") == "13800000000",
        f"HTTP {pending.status} rows={len(pending_rows)}",
    )

    # ----------------------------------------------------------------- D
    print("\n--- D/E Public 不得读取或确认报名 ---")
    anon_list = anon.get(f"/api/tournaments/{tid}/registrations")
    check(
        "D 匿名 GET /registrations → 401 AUTH_REQUIRED",
        anon_list.status == 401 and anon_list.detail_code == "AUTH_REQUIRED",
        f"HTTP {anon_list.status} code={anon_list.detail_code}",
    )

    anon_confirm = anon.post(f"/api/tournaments/{tid}/registrations/{registration_id}/confirm")
    check(
        "E 匿名 POST /registrations/{id}/confirm → 401",
        anon_confirm.status == 401,
        f"HTTP {anon_confirm.status} code={anon_confirm.detail_code}",
    )

    # ----------------------------------------------------------------- F
    cross = other.post(f"/api/tournaments/{tid}/registrations/{registration_id}/confirm")
    check(
        "F 他赛事管理员确认 → 404 RESOURCE_NOT_FOUND（跨赛事一律不泄露）",
        cross.status == 404 and cross.detail_code == "RESOURCE_NOT_FOUND",
        f"HTTP {cross.status} code={cross.detail_code}",
    )

    still_pending = admin.get(f"/api/tournaments/{tid}/registrations?status=PENDING")
    rows_after_f = still_pending.body if isinstance(still_pending.body, list) else []
    check(
        "F 越权 / 匿名尝试后台账仍为 PENDING，Player 仍为 0",
        len(rows_after_f) == 1 and len(admin.get(f"/api/tournaments/{tid}/players").body or []) == 0,
        f"pending={len(rows_after_f)}",
    )

    # ----------------------------------------------------------------- C
    print("\n--- C 管理员关闭报名 ---")
    disabled = admin.put(f"/api/tournaments/{tid}/registration", {"enabled": False})
    check(
        "C PUT /registration {enabled:false} → 200 且 registration_enabled=false",
        disabled.status == 200 and isinstance(disabled.body, dict) and disabled.body.get("registration_enabled") is False,
        f"HTTP {disabled.status}",
    )
    check(
        "C 匿名 GET /tournaments/{tid} 反映 registration_enabled=false（Public 关闭态的真实来源）",
        (anon.get(f"/api/tournaments/{tid}").body or {}).get("registration_enabled") is False,
        "",
    )
    rejected = anon.post(f"/api/tournaments/{tid}/registrations", {"name": "李四"})
    check(
        "C 关闭后匿名提交 → 409 REGISTRATION_CLOSED",
        rejected.status == 409 and rejected.detail_code == "REGISTRATION_CLOSED",
        f"HTTP {rejected.status} code={rejected.detail_code} message={rejected.detail_message}",
    )
    final_pending = admin.get(f"/api/tournaments/{tid}/registrations?status=PENDING")
    check(
        "C 关闭后台账不增加（仍 1 条），Player 仍为 0",
        len(final_pending.body or []) == 1 and counts(admin, tid) == (0, 0, 0),
        f"pending={len(final_pending.body or [])} counts={counts(admin, tid)}",
    )

    passed = sum(1 for ok, _, _ in results if ok)
    total = len(results)
    print(f"\n=== D5D smoke: {passed}/{total} PASS ===")
    if passed != total:
        for ok, name, detail in results:
            if not ok:
                print(f"  FAIL {name} :: {detail}")
        return 1
    print("tid=%d registration_id=%s" % (tid, registration_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
