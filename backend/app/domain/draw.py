"""个人赛抽签纯函数。

抽签的硬约束依次为签表容量、种子位置和 BYE；同单位规避只在这些约束
均不受影响的候选位置之间生效。这里不访问数据库，所属单位由 Entry 成员
的 ``college`` 兼容字段聚合而来，未来接入正式 Affiliation 时只需替换调用方
提供的成员数据。
"""

from __future__ import annotations

import random
from itertools import permutations
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


def _collision_count(slots: list[dict[str, Any] | None]) -> int:
    return sum(
        1
        for index in range(0, len(slots), 2)
        if slots[index] is not None
        and slots[index + 1] is not None
        and entry_affiliations(slots[index]) & entry_affiliations(slots[index + 1])
    )


def _optimise_affiliations(
    slots: list[dict[str, Any] | None], locked_slots: set[int], rng: random.Random
) -> None:
    """在不移动种子/BYE 的前提下，降低首轮总单位碰撞数。

    至多八个可动参赛位时枚举全部落位，保证找到总碰撞最小的解；更大签表
    使用严格降碰撞的交换优化，保持可预测的有限运行时间。
    """
    movable = [index for index in range(len(slots)) if index not in locked_slots]
    values = [slots[index] for index in movable]
    if any(value is None for value in values):
        raise ValueError("可调签位不能包含轮空")

    if len(movable) <= 8:
        best: tuple[dict[str, Any], ...] | None = None
        best_count: int | None = None
        ties = 0
        for candidate in permutations(values):
            for index, entry in zip(movable, candidate):
                slots[index] = entry
            count = _collision_count(slots)
            if best_count is None or count < best_count:
                best_count, best, ties = count, candidate, 1
            elif count == best_count:
                ties += 1
                if rng.randrange(ties) == 0:
                    best = candidate
        assert best is not None  # movable 为有限集合，permutations 至少产生一个结果。
        for index, entry in zip(movable, best):
            slots[index] = entry
        return

    # 大签表使用局部交换：每一步必须严格降低全局碰撞数，因而必定终止。
    while True:
        current = _collision_count(slots)
        best_count = current
        swaps: list[tuple[int, int]] = []
        for left, index in enumerate(movable):
            for other in movable[left + 1:]:
                slots[index], slots[other] = slots[other], slots[index]
                count = _collision_count(slots)
                slots[index], slots[other] = slots[other], slots[index]
                if count < best_count:
                    best_count, swaps = count, [(index, other)]
                elif count == best_count and count < current:
                    swaps.append((index, other))
        if not swaps:
            return
        index, other = rng.choice(swaps)
        slots[index], slots[other] = slots[other], slots[index]


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
    locked_slots: set[int] = set()
    for entry, slot in zip(seeded, _seed_slots(size)):
        slots[slot] = entry
        locked_slots.add(slot)

    strength = seeded + [entry for entry in entries if entry.get("seed_no") is None]
    bye_receivers = strength[: size - len(entries)]
    reserved: set[int] = set()
    rng = random.Random(draw_seed)

    def available_slots() -> list[int]:
        return [index for index, entry in enumerate(slots) if entry is None and index not in reserved]

    def place(entry: dict[str, Any], *, reserve_opponent: bool) -> None:
        index = next(
            (slot for slot, value in enumerate(slots) if value is not None and value["id"] == entry["id"]),
            None,
        )
        if index is None:
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
            locked_slots.update((index, opponent))

    for entry in bye_receivers:
        place(entry, reserve_opponent=True)
    bye_receiver_ids = {entry["id"] for entry in bye_receivers}
    for entry in strength:
        if entry["id"] not in bye_receiver_ids:
            place(entry, reserve_opponent=False)

    _optimise_affiliations(slots, locked_slots, rng)

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
