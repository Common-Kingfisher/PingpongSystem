"""个人赛抽签纯函数。

抽签的硬约束依次为签表容量、种子位置和 BYE；同单位规避只在这些约束
均不受影响的候选位置之间生效。这里不访问数据库，所属单位由 Entry 成员
的 ``college`` 兼容字段聚合而来，未来接入正式 Affiliation 时只需替换调用方
提供的成员数据。
"""

from __future__ import annotations

import random
from typing import Any


def entry_affiliations(entry: dict[str, Any]) -> set[str]:
    """返回 Entry 全部非空所属单位；双打取两名成员的并集。"""
    return {
        member["college"]
        for member in entry.get("members", [])
        if member.get("college")
    }


def _bracket_size(participant_count: int) -> int:
    size = 1
    while size < participant_count:
        size *= 2
    return size


def _seed_slots(size: int) -> list[int]:
    """给 1、2、… 号种子的稳定槽位；前两位必然分处不同半区。"""
    if size == 1:
        return [0]
    half = size // 2
    return [slot for pair in zip(_seed_slots(half), [slot + half for slot in _seed_slots(half)]) for slot in pair]


def build_single_elimination(
    entries: list[dict[str, Any]], draw_seed: int | None = None
) -> list[list[dict[str, int | None]]]:
    """根据 ACTIVE Entry 生成单淘汰签表规格。

    非 2 幂人数扩展到下一档签位；排名靠前的参赛者获得 BYE。种子槽位先固定，
    其余候选仅在同等合法时按首轮单位碰撞数选择，并以 ``draw_seed`` 保证可复现。
    """
    if len(entries) < 2:
        raise ValueError("单淘汰至少需要 2 名有效参赛位")
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("参赛位存在重复")
    seeded = sorted(
        (entry for entry in entries if entry.get("seed_no") is not None),
        key=lambda entry: (entry["seed_no"], entry["id"]),
    )
    if len({entry["seed_no"] for entry in seeded}) != len(seeded):
        raise ValueError("种子序号不能重复")

    size = _bracket_size(len(entries))
    slots: list[dict[str, Any] | None] = [None] * size
    for entry, slot in zip(seeded, _seed_slots(size)):
        slots[slot] = entry

    strength = seeded + [entry for entry in entries if entry.get("seed_no") is None]
    bye_receivers = strength[: size - len(entries)]
    reserved: set[int] = set()
    rng = random.Random(draw_seed)

    def available_slots() -> list[int]:
        return [index for index, entry in enumerate(slots) if entry is None and index not in reserved]

    def place(entry: dict[str, Any], *, reserve_opponent: bool) -> None:
        try:
            index = slots.index(entry)
        except ValueError:
            candidates = available_slots()
            if not candidates:
                raise ValueError("签表槽位不足")
            # 已经落位的对手决定当前首轮碰撞数；无对手的位置不优于有空位，
            # 因为其未来对手仍会按同一规则选择。
            affiliation = entry_affiliations(entry)
            collision = {
                slot: len(affiliation & entry_affiliations(slots[slot ^ 1]))
                if slots[slot ^ 1] is not None else 0
                for slot in candidates
            }
            minimum = min(collision.values())
            best = [slot for slot in candidates if collision[slot] == minimum]
            index = rng.choice(best)
            slots[index] = entry
        if reserve_opponent:
            opponent = index ^ 1
            if slots[opponent] is not None:
                raise ValueError("种子位置与轮空位置冲突")
            reserved.add(opponent)

    for entry in bye_receivers:
        place(entry, reserve_opponent=True)
    for entry in strength:
        if entry not in bye_receivers:
            place(entry, reserve_opponent=False)

    first_pairs = [(slots[index], slots[index + 1]) for index in range(0, size, 2)]
    rounds: list[list[dict[str, int | None]]] = []
    round_no = 1
    while True:
        rounds.append([
            {
                "round": round_no,
                "match_index": index,
                "player_a_id": a["id"] if a is not None else None,
                "player_b_id": b["id"] if b is not None else None,
            }
            for index, (a, b) in enumerate(first_pairs)
        ])
        if len(first_pairs) == 1:
            return rounds
        round_no += 1
        first_pairs = [(None, None)] * (len(first_pairs) // 2)
