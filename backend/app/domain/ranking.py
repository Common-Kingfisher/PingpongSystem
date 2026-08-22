"""小组排名计算（纯函数，与 UI / DB 解耦）。

排名规则（明确且诚实）：
1. 主排序：胜场数（wins）降序；
2. 次级：净胜局（games_won - games_lost）降序；
3. 若（1）（2）仍并列且恰好两人：按两人直接交锋胜负关系决定先后；
4. 仍无法区分（三人及以上连环、或二人无交锋记录）：并列处理——
   同 rank、tied=True，绝不编造先后次序。

排名在读取时由"全部已结束比赛"重新计算，因此修改比分天然整体重算，
不会在旧统计上做增减，不存在累计污染。

晋级判定 compute_qualification：
- rank <= qualify_per_group 且未并列 → 晋级；
- 涉及并列（含晋级线附近并列）→ 返回 ambiguous=True，由人工裁决，不替系统做决定。
"""

from typing import Any


def compute_group_rankings(
    matches: list[dict[str, Any]],
    player_ids: list[int],
) -> list[dict[str, Any]]:
    """根据某小组的比赛记录计算排名。

    matches: 该小组全部比赛（含未结束的；只统计 status=FINISHED 且有 winner 的）。
    player_ids: 组内全部选手 id。
    返回按名次排序的条目列表，每条含：
      player_id / wins / losses / games_won / games_lost / rank / tied
    """
    stats: dict[int, dict[str, Any]] = {}
    for pid in player_ids:
        stats[pid] = {
            "player_id": pid,
            "wins": 0,
            "losses": 0,
            "games_won": 0,
            "games_lost": 0,
        }

    finished: list[dict[str, Any]] = []
    for m in matches:
        if m.get("status") == "FINISHED" and m.get("winner_id") is not None:
            finished.append(m)

    for m in finished:
        a, b = m["player_a_id"], m["player_b_id"]
        if a is None or b is None or a == b:
            continue
        sa, sb = m["player_a_score"], m["player_b_score"]
        winner = m["winner_id"]
        stats[a]["games_won"] += sa
        stats[a]["games_lost"] += sb
        stats[b]["games_won"] += sb
        stats[b]["games_lost"] += sa
        if winner == a:
            stats[a]["wins"] += 1
            stats[b]["losses"] += 1
        else:
            stats[b]["wins"] += 1
            stats[a]["losses"] += 1

    # 按 (wins, 净胜局) 分桶
    buckets: dict[tuple[int, int], list[int]] = {}
    for pid, s in stats.items():
        key = (s["wins"], s["games_won"] - s["games_lost"])
        buckets.setdefault(key, []).append(pid)

    result: list[dict[str, Any]] = []
    rank = 1
    for key in sorted(buckets, key=lambda k: (-k[0], -k[1])):
        bucket = buckets[key]
        if len(bucket) == 1:
            pid = bucket[0]
            result.append({**stats[pid], "rank": rank, "tied": False})
            rank += 1
            continue
        order, resolved = _resolve_head_to_head(finished, bucket)
        if resolved:
            for pid in order:
                result.append({**stats[pid], "rank": rank, "tied": False})
                rank += 1
        else:
            for pid in order:
                result.append({**stats[pid], "rank": rank, "tied": True})
            rank += len(bucket)
    return result


def _resolve_head_to_head(
    finished: list[dict[str, Any]], bucket: list[int]
) -> tuple[list[int], bool]:
    """两人并列时按直接交锋分胜负。返回 (顺序, 是否已解决)。"""
    if len(bucket) == 2:
        a, b = bucket
        for m in finished:
            if {m["player_a_id"], m["player_b_id"]} == {a, b}:
                if m["winner_id"] == a:
                    return ([a, b], True)
                return ([b, a], True)
    return (sorted(bucket), False)


def compute_qualification(
    entries: list[dict[str, Any]], qualify_per_group: int
) -> tuple[list[int], bool]:
    """按排名决定晋级名单。返回 (晋级选手 id 列表, 是否出现无法判定的并列)。"""
    qualified: list[int] = []
    ambiguous = False
    for e in sorted(entries, key=lambda e: (e["rank"], e["player_id"])):
        if e["rank"] <= qualify_per_group:
            if e["tied"]:
                ambiguous = True
            else:
                qualified.append(e["player_id"])
    return qualified, ambiguous
