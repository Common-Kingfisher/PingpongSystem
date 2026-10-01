"""D 轨 Day6D Phase 7：服务重启前后「现场事实」比对。

## 这个脚本要证明什么

赛事跑到中途（有 Tournament / Players / Entries / Groups / Matches，既有 FINISHED
也有 WAITING / PLAYING），**停掉服务再重启**之后：

```text
赛事还在
名单还在（roster_confirmed 不回退）
比分还在（每场 FINISHED 的比分逐场一致）
球台占用状态还在
阶段没有莫名回退
```

## 明确禁止的“通过方式”

不重新生成 Demo 数据、不重置数据库、不 `seed`、不删库重建。
本脚本**只读**：capture 与 verify 都是 GET，不做任何写请求。

## 用法

```powershell
# 1. 赛事运行到中途时（重启前）
.\.venv\Scripts\python.exe .\day6d_restart_check.py capture http://127.0.0.1:8000 1 d6d-admin d6d-admin-pass1 "$env:TEMP\d6d_restart_before.json"

# 2. 重新运行 .\start_pingpong.ps1（同一条命令、同一个 PINGPONG_DB_PATH）
# 3. 重启后
.\.venv\Scripts\python.exe .\day6d_restart_check.py verify http://127.0.0.1:8000 1 d6d-admin d6d-admin-pass1 "$env:TEMP\d6d_restart_before.json"
```

退出码 0 = 全部一致；1 = 有事实丢失或不一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from day3_auth_client import AuthClient

failures: list[str] = []
lines: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    line = f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}"
    lines.append(line)
    print(line, flush=True)
    if not ok:
        failures.append(name)


def snapshot(base: str, tid: int, user: str, password: str) -> dict:
    """只读采集现场快照（全部 GET）。"""
    client = AuthClient(base)
    client.login_bearer(user, password)

    tournament = client.get(f"/api/tournaments/{tid}").body
    players = client.get(f"/api/tournaments/{tid}/players").body
    entries = client.get(f"/api/tournaments/{tid}/entries").body
    groups = client.get(f"/api/tournaments/{tid}/groups").body
    matches = client.get(f"/api/tournaments/{tid}/matches").body
    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").body
    registrations = client.get(f"/api/tournaments/{tid}/registrations").body

    def score_audit_count(match_id: int) -> int:
        body = client.get(f"/api/matches/{match_id}/score-audits").body
        return len(body) if isinstance(body, list) else -1

    return {
        "tournament": {
            "id": tournament["id"],
            "name": tournament["name"],
            "stage": tournament["stage"],
            "format_code": tournament["format_code"],
            "event_type": tournament["event_type"],
            "roster_confirmed": tournament["roster_confirmed"],
            "registration_enabled": tournament["registration_enabled"],
            "table_count": tournament["table_count"],
            "group_count": tournament["group_count"],
        },
        "players": sorted(
            [{"id": p["id"], "name": p["name"], "college": p.get("college")} for p in players],
            key=lambda p: p["id"],
        ),
        "entries": sorted(
            [{"id": e["id"], "display_name": e["display_name"], "status": e["status"]} for e in entries],
            key=lambda e: e["id"],
        ),
        "groups": sorted(
            [
                {
                    "id": g["id"],
                    "name": g["name"],
                    "qualify_count": g.get("qualify_count"),
                    "entries": sorted(item["id"] for item in (g.get("entries") or [])),
                }
                for g in groups["groups"]
            ],
            key=lambda g: g["id"],
        ),
        "registrations": sorted(
            [{"id": r["id"], "name": r["name"], "status": r["status"]} for r in registrations],
            key=lambda r: r["id"],
        ),
        "matches": sorted(
            [
                {
                    "id": m["id"],
                    "status": m["status"],
                    "stage": m["stage"],
                    "group_id": m["group_id"],
                    "round": m["round"],
                    "table_id": m["table_id"],
                    "entry_a_id": m["entry_a_id"],
                    "entry_b_id": m["entry_b_id"],
                    "player_a_score": m["player_a_score"],
                    "player_b_score": m["player_b_score"],
                    "result_type": m["result_type"],
                    "games": len(m.get("games") or []),
                    "score_audits": score_audit_count(m["id"]),
                }
                for m in matches
            ],
            key=lambda m: m["id"],
        ),
        "tables": sorted(
            [{"id": t["id"], "status": t["status"]} for t in dashboard["tables"]],
            key=lambda t: t["id"],
        ),
        "stats": dashboard["stats"],
    }


def capture(base: str, tid: int, user: str, password: str, out: Path) -> int:
    data = snapshot(base, tid, user, password)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    finished = [m for m in data["matches"] if m["status"] == "FINISHED"]
    print(f"[OK] 已采集重启前快照 -> {out}")
    print(
        f"     stage={data['tournament']['stage']} roster_confirmed={data['tournament']['roster_confirmed']} "
        f"players={len(data['players'])} entries={len(data['entries'])} groups={len(data['groups'])} "
        f"matches={len(data['matches'])} finished={len(finished)} "
        f"playing={sum(1 for m in data['matches'] if m['status'] == 'PLAYING')} "
        f"waiting={sum(1 for m in data['matches'] if m['status'] == 'WAITING')}"
    )
    return 0


def verify(base: str, tid: int, user: str, password: str, src: Path) -> int:
    before = json.loads(src.read_text(encoding="utf-8"))
    after = snapshot(base, tid, user, password)

    t_before, t_after = before["tournament"], after["tournament"]
    check("R1 服务重启后赛事仍存在", t_after["id"] == t_before["id"], f"id={t_after['id']}")
    check("R2 赛事名称未变", t_after["name"] == t_before["name"], t_after["name"])
    check("R3 阶段没有莫名回退", t_after["stage"] == t_before["stage"], f"{t_before['stage']} -> {t_after['stage']}")
    check("R4 赛制未变", t_after["format_code"] == t_before["format_code"], f"{t_before['format_code']} -> {t_after['format_code']}")
    check(
        "R5 名单确认状态未回退",
        t_after["roster_confirmed"] == t_before["roster_confirmed"],
        f"roster_confirmed={t_after['roster_confirmed']}",
    )

    check(
        "R6 正式名单（Player）完整保留",
        after["players"] == before["players"],
        f"{len(before['players'])} -> {len(after['players'])}",
    )
    check(
        "R7 参赛位（Entry）完整保留",
        after["entries"] == before["entries"],
        f"{len(before['entries'])} -> {len(after['entries'])}",
    )
    check(
        "R8 报名台账完整保留（含 CONFIRMED 状态）",
        after["registrations"] == before["registrations"],
        f"{len(before['registrations'])} -> {len(after['registrations'])}",
    )
    check("R9 分组与逐组晋级人数保留", after["groups"] == before["groups"], f"{len(before['groups'])} 组")

    b_matches = {m["id"]: m for m in before["matches"]}
    a_matches = {m["id"]: m for m in after["matches"]}
    check("R10 比赛场次没有丢失", set(b_matches) == set(a_matches), f"{len(b_matches)} -> {len(a_matches)}")

    lost_scores = [
        mid for mid, m in b_matches.items()
        if m["status"] == "FINISHED" and (
            mid not in a_matches
            or a_matches[mid]["player_a_score"] != m["player_a_score"]
            or a_matches[mid]["player_b_score"] != m["player_b_score"]
            or a_matches[mid]["result_type"] != m["result_type"]
        )
    ]
    finished_count = sum(1 for m in b_matches.values() if m["status"] == "FINISHED")
    check(
        "R11 已结束比赛的比分与结果类型逐场一致",
        not lost_scores,
        f"finished={finished_count} mismatched={lost_scores}",
    )

    regressed = [
        mid for mid, m in b_matches.items()
        if mid in a_matches and m["status"] == "FINISHED" and a_matches[mid]["status"] != "FINISHED"
    ]
    check("R12 没有比赛从 FINISHED 回退", not regressed, f"regressed={regressed}")

    playing_before = {mid for mid, m in b_matches.items() if m["status"] == "PLAYING"}
    playing_after = {mid for mid, m in a_matches.items() if m["status"] == "PLAYING"}
    check(
        "R13 重启前后进行中的比赛一致（含球台占用）",
        playing_before == playing_after and after["tables"] == before["tables"],
        f"playing {sorted(playing_before)} -> {sorted(playing_after)}",
    )

    audits_mismatch = [
        mid for mid, m in b_matches.items()
        if mid in a_matches and a_matches[mid]["score_audits"] != m["score_audits"]
    ]
    check("R14 比分审计账本条数一致", not audits_mismatch, f"mismatched={audits_mismatch}")

    check(
        "R15 进度统计一致",
        after["stats"] == before["stats"],
        f"{before['stats']} -> {after['stats']}",
    )

    print()
    print(f"=== D6D restart check: {len(lines) - len(failures)}/{len(lines)} PASS ===")
    if failures:
        print(f"FAILURES: {' | '.join(failures)}")
    return 1 if failures else 0


def main() -> int:
    if len(sys.argv) < 7:
        print(__doc__)
        return 2
    mode, base, tid, user, password, path = sys.argv[1:7]
    tid_int = int(tid)
    if mode == "capture":
        return capture(base, tid_int, user, password, Path(path))
    if mode == "verify":
        return verify(base, tid_int, user, password, Path(path))
    print(f"未知模式: {mode}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
