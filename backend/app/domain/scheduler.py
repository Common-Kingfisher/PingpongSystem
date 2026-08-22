"""球台贪心调度算法（纯函数，与 UI / DB 解耦）。

策略：按传入顺序（一般为比赛 id 升序）依次取出可执行的比赛，
每场分配给一张空闲球台。

硬约束（由本函数保证）：
1. 同一名选手不能被同时安排进两场比赛（含本次批内与批外已占用选手）；
2. 同一张球台一次只安排一场比赛；
3. 已结束（FINISHED）或进行中（PLAYING）的比赛不参与安排。

返回 [(match_id, table_id), ...]。
"""

from typing import Any, Sequence


def schedule_batch(
    matches: Sequence[dict[str, Any]],
    free_table_ids: Sequence[int],
) -> list[tuple[int, int]]:
    """贪心分配。

    matches: 已按优先级排序的候选比赛（含 id/status/player_a_id/player_b_id）。
    free_table_ids: 空闲球台 id 列表。
    """
    tables = list(free_table_ids)
    playing_players: set[int] = set()
    assignments: list[tuple[int, int]] = []

    for match in matches:
        if not tables:
            break
        if match["status"] != "WAITING":
            continue
        a, b = match["player_a_id"], match["player_b_id"]
        if a in playing_players or b in playing_players:
            continue
        assignments.append((match["id"], tables.pop(0)))
        if a is not None:
            playing_players.add(a)
        if b is not None:
            playing_players.add(b)

    return assignments
