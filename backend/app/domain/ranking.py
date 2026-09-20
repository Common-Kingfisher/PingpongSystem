"""小组排名计算（纯函数，与 UI / DB 解耦）。

排名规则（明确且诚实）：
1. 主排序：胜场数（wins）降序；
2. 次级：净胜局（games_won - games_lost）降序；
3. 赛事积分（胜 2、正常负 1、弃权负 0）；
4. 两人仍同分时看直接交锋；三人及以上循环同分时，只有在相关场次
   已补录逐局小分后，才按乒联思路比较得失分比率；
5. 小分未录齐或比率仍相同则保持并列，绝不编造名次。

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
            "match_points": 0,
            "points_won": 0,
            "points_lost": 0,
        }

    finished: list[dict[str, Any]] = []
    for m in matches:
        if m.get("status") == "FINISHED" and (
            m.get("winner_entry_id") is not None or m.get("winner_id") is not None
        ):
            finished.append(m)

    for m in finished:
        a = m.get("entry_a_id") or m.get("player_a_id")
        b = m.get("entry_b_id") or m.get("player_b_id")
        if a is None or b is None or a == b:
            continue
        sa, sb = m["player_a_score"], m["player_b_score"]
        winner = m.get("winner_entry_id") or m.get("winner_id")
        stats[a]["games_won"] += sa
        stats[a]["games_lost"] += sb
        stats[b]["games_won"] += sb
        stats[b]["games_lost"] += sa
        if winner == a:
            stats[a]["wins"] += 1
            stats[b]["losses"] += 1
            stats[a]["match_points"] += 2
            stats[b]["match_points"] += 1 if m.get("result_type") in (None, "NORMAL") else 0
        else:
            stats[b]["wins"] += 1
            stats[a]["losses"] += 1
            stats[b]["match_points"] += 2
            stats[a]["match_points"] += 1 if m.get("result_type") in (None, "NORMAL") else 0
        for game in m.get("games", []):
            stats[a]["points_won"] += game["side_a_score"]
            stats[a]["points_lost"] += game["side_b_score"]
            stats[b]["points_won"] += game["side_b_score"]
            stats[b]["points_lost"] += game["side_a_score"]

    # 常规录分只保存大比分。小分不能在缺失时用 0 冒充，因此先按
    # 胜场 → 净胜局 → 2/1/0 赛事积分分桶，真正需要时再比较得失分比率。
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for pid, s in stats.items():
        s["point_difference"] = s["points_won"] - s["points_lost"]
        s["point_ratio"] = _ratio(s["points_won"], s["points_lost"])
        key = (
            s["wins"],
            s["games_won"] - s["games_lost"],
            s["match_points"],
        )
        buckets.setdefault(key, []).append(pid)

    result: list[dict[str, Any]] = []
    rank = 1
    for key in sorted(buckets, key=lambda k: (-k[0], -k[1], -k[2])):
        bucket = buckets[key]
        for subgroup in _resolve_bucket(finished, bucket):
            if len(subgroup) == 1:
                result.append({**stats[subgroup[0]], "rank": rank, "tied": False})
                rank += 1
            else:
                for pid in subgroup:
                    result.append({**stats[pid], "rank": rank, "tied": True})
                rank += len(subgroup)
    return result


def _ratio(won: int, lost: int) -> float:
    """乒联排名使用比率；0 失分时视为正无穷。"""
    if lost == 0:
        return 999999.0 if won > 0 else 0.0
    return won / lost


def _resolve_by_point_ratio(
    finished: list[dict[str, Any]], bucket: list[int]
) -> list[list[int]] | None:
    """三人及以上循环同分时，按相互比赛的小分得失比率分组。

    返回按 ratio 降序排列的子组列表：每个子组内 ratio 相同（组内按 pid 升序），
    因此 singleton 子组可确定名次，多元素子组仍并列。
    相关正常完赛场次缺逐局小分时返回 None（无法解析，整桶并列）。
    """
    ids = set(bucket)
    relevant = []
    for match in finished:
        a = match.get("entry_a_id") or match.get("player_a_id")
        b = match.get("entry_b_id") or match.get("player_b_id")
        if a in ids and b in ids and match.get("result_type") in (None, "NORMAL"):
            relevant.append(match)
    if not relevant or any(not match.get("games") for match in relevant):
        return None

    points = {pid: [0, 0] for pid in bucket}
    for match in relevant:
        a = match.get("entry_a_id") or match.get("player_a_id")
        b = match.get("entry_b_id") or match.get("player_b_id")
        for game in match.get("games", []):
            points[a][0] += game["side_a_score"]
            points[a][1] += game["side_b_score"]
            points[b][0] += game["side_b_score"]
            points[b][1] += game["side_a_score"]
    ratios = {pid: _ratio(*points[pid]) for pid in bucket}
    order = sorted(bucket, key=lambda pid: (-ratios[pid], pid))
    groups: list[list[int]] = []
    for pid in order:
        if not groups or round(ratios[pid], 12) != round(ratios[groups[-1][0]], 12):
            groups.append([pid])
        else:
            groups[-1].append(pid)
    return groups


def missing_point_score_match_ids(
    matches: list[dict[str, Any]], entries: list[dict[str, Any]], qualify_count: int
) -> list[int]:
    """返回影响出线线且尚未补录小分的场次。"""
    tied_ids = {
        entry["player_id"] for entry in entries
        if entry.get("tied") and entry.get("rank", 9999) <= qualify_count
    }
    if not tied_ids:
        return []
    missing = []
    for match in matches:
        a = match.get("entry_a_id") or match.get("player_a_id")
        b = match.get("entry_b_id") or match.get("player_b_id")
        if (a in tied_ids and b in tied_ids
                and match.get("status") == "FINISHED"
                and match.get("result_type") in (None, "NORMAL")
                and not match.get("games")):
            missing.append(match["id"])
    return missing


def _resolve_head_to_head(
    finished: list[dict[str, Any]], bucket: list[int]
) -> tuple[list[int], bool]:
    """两人并列时按直接交锋分胜负。返回 (顺序, 是否已解决)。"""
    if len(bucket) == 2:
        a, b = bucket
        for m in finished:
            ma = m.get("entry_a_id") or m.get("player_a_id")
            mb = m.get("entry_b_id") or m.get("player_b_id")
            winner = m.get("winner_entry_id") or m.get("winner_id")
            if {ma, mb} == {a, b}:
                if winner == a:
                    return ([a, b], True)
                return ([b, a], True)
    return (sorted(bucket), False)


def _resolve_bucket(
    finished: list[dict[str, Any]], bucket: list[int]
) -> list[list[int]]:
    """把同分 bucket 解析为若干按名次排序的子组。

    - singleton 子组 → 已确定名次（tied=False）；
    - 多元素子组 → 仍并列（组内共享 rank、tied=True）；
    - 整桶无法解析时返回单个整桶子组。
    """
    if len(bucket) == 1:
        return [list(bucket)]
    order, resolved = _resolve_head_to_head(finished, bucket)
    if resolved:
        return [[pid] for pid in order]
    if len(bucket) > 2:
        subgroups = _resolve_by_point_ratio(finished, bucket)
        if subgroups is not None:
            return subgroups
    return [sorted(bucket)]


def compute_qualification(
    entries: list[dict[str, Any]], qualify_per_group: int
) -> tuple[list[int], bool]:
    """按排名决定晋级名单。返回 (晋级选手 id 列表, 是否出现并列跨晋级线)。

    以"完整同 rank 组"为单位处理：
    - 整组能放进剩余名额 → 整组晋级（并列不等于 ambiguity）；
    - 晋级线切开某个组（组人数 > 剩余名额）→ ambiguous=True，不从该组任选成员。
    """
    qualified: list[int] = []
    ambiguous = False
    groups: dict[int, list[int]] = {}
    for e in sorted(entries, key=lambda e: (e["rank"], e["player_id"])):
        groups.setdefault(e["rank"], []).append(e["player_id"])
    for rank in sorted(groups):
        group = groups[rank]
        remaining = qualify_per_group - len(qualified)
        if remaining <= 0:
            break
        if len(group) <= remaining:
            qualified.extend(group)
        else:
            ambiguous = True
            break
    return qualified, ambiguous
