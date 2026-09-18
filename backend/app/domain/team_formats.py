"""团体赛赛制规格（TeamFormatSpec）与出场骨架（Rubber skeleton）——纯函数。

A3 只描述"一场团体对抗由哪几盘组成、每盘每边需要几个出场位置"，
不涉及谁上场（TeamLineup / 位置分配属于 A4），也不涉及排程与比分状态机。

诚实边界（必须保留这些说明，不要删）：
1. PRODUCTION_FORMATS 故意为空。团体赛赛制差异极大（几单几双、是否必须打满、
   双打是否允许兼项、决胜盘规则……），任何具体规则都必须由赛事组织方确认冻结后
   才能写进生产注册表。A3 绝不臆造 "奥运赛制 / ITTF 经典赛制" 之类的规则；
   测试里使用的规格只存在于测试代码中，不通过任何 API 暴露，也不代表官方规则。
2. 校验只保证"规格自洽"：结构合法、盘序从 1 连续、每盘位置数符合单打/双打的定义、
   盘数不少于获胜所需盘数。它不假设任何一条真实赛事规则。
3. 快照（snapshot）把规格固化成 JSON：赛事进行中即使注册表升级，
   已创建的对抗仍按创建时的 format_code + format_version + format_snapshot 解释，
   不会被新规则追溯改写。
"""

import json
from dataclasses import dataclass, field
from typing import Any

from ..models import TeamRubberStatus, TeamRubberType

SNAPSHOT_VERSION = 1

#: 每种盘的每边位置数。这是"单打/双打"两个词本身的结构含义，不是赛事规则。
SLOTS_PER_SIDE = {
    TeamRubberType.SINGLES.value: 1,
    TeamRubberType.DOUBLES.value: 2,
}


class TeamFormatError(ValueError):
    """赛制规格不合法或未知。服务层负责映射为 HTTP 状态码。"""


@dataclass(frozen=True)
class RubberTemplate:
    """一盘的结构需求：第几盘、单打还是双打、每边各要几个出场位置。

    home_slots / away_slots 只是"位置代号"（例如 "H1"、"A2"），
    不是选手 id：把选手填进位置属于 A4 的 TeamLineup。
    """

    sequence: int
    rubber_type: str
    home_slots: tuple[str, ...]
    away_slots: tuple[str, ...]


@dataclass(frozen=True)
class TeamFormatSpec:
    """一个团体赛赛制版本。

    code 稳定不变，version 递增；两者一起构成"这场对抗按哪版规则解释"的锚点。
    """

    code: str
    version: int
    display_name: str
    rubbers_to_win: int
    rubbers: tuple[RubberTemplate, ...] = field(default_factory=tuple)


def _check_slot_codes(slots: tuple[str, ...], side_label: str, sequence: int) -> None:
    if not slots:
        raise TeamFormatError(f"第 {sequence} 盘的{side_label}位置列表不能为空")
    seen: set[str] = set()
    for slot in slots:
        if not isinstance(slot, str) or slot.strip() == "":
            raise TeamFormatError(f"第 {sequence} 盘的{side_label}位置代号不能为空")
        if slot != slot.strip():
            raise TeamFormatError(f"第 {sequence} 盘的{side_label}位置代号不能含首尾空白：{slot!r}")
        if slot in seen:
            raise TeamFormatError(f"第 {sequence} 盘的{side_label}位置代号重复：{slot}")
        seen.add(slot)


def validate_format_spec(spec: TeamFormatSpec) -> None:
    """校验规格自洽；不合法一律抛 TeamFormatError（不要用 assert，生产会 -O 掉）。"""
    if not isinstance(spec.code, str) or spec.code.strip() == "":
        raise TeamFormatError("赛制 code 不能为空")
    if spec.code != spec.code.strip():
        raise TeamFormatError(f"赛制 code 不能含首尾空白：{spec.code!r}")
    if not isinstance(spec.version, int) or isinstance(spec.version, bool) or spec.version < 1:
        raise TeamFormatError(f"赛制版本号必须是 >= 1 的整数：{spec.version!r}")
    if not isinstance(spec.display_name, str) or spec.display_name.strip() == "":
        raise TeamFormatError(f"赛制「{spec.code}」缺少显示名称")
    if not isinstance(spec.rubbers_to_win, int) or isinstance(spec.rubbers_to_win, bool):
        raise TeamFormatError(f"赛制「{spec.code}」的获胜所需盘数必须是整数")
    if spec.rubbers_to_win < 1:
        raise TeamFormatError(f"赛制「{spec.code}」的获胜所需盘数必须 >= 1")
    if not spec.rubbers:
        raise TeamFormatError(f"赛制「{spec.code}」至少要包含一盘")
    if spec.rubbers_to_win > len(spec.rubbers):
        raise TeamFormatError(
            f"赛制「{spec.code}」获胜需要 {spec.rubbers_to_win} 盘，但只定义了 {len(spec.rubbers)} 盘"
        )

    sequences = [r.sequence for r in spec.rubbers]
    for seq in sequences:
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise TeamFormatError(f"赛制「{spec.code}」的盘序号必须是 >= 1 的整数：{seq!r}")
    if len(set(sequences)) != len(sequences):
        raise TeamFormatError(f"赛制「{spec.code}」的盘序号重复：{sorted(sequences)}")
    if sorted(sequences) != list(range(1, len(sequences) + 1)):
        raise TeamFormatError(
            f"赛制「{spec.code}」的盘序号必须从 1 开始且连续：{sorted(sequences)}"
        )

    for rubber in spec.rubbers:
        if rubber.rubber_type not in SLOTS_PER_SIDE:
            raise TeamFormatError(
                f"赛制「{spec.code}」第 {rubber.sequence} 盘的盘类型不合法：{rubber.rubber_type!r}"
            )
        expected = SLOTS_PER_SIDE[rubber.rubber_type]
        _check_slot_codes(tuple(rubber.home_slots), "主队", rubber.sequence)
        _check_slot_codes(tuple(rubber.away_slots), "客队", rubber.sequence)
        if len(rubber.home_slots) != expected:
            raise TeamFormatError(
                f"赛制「{spec.code}」第 {rubber.sequence} 盘是 {rubber.rubber_type}，"
                f"主队需要 {expected} 个位置，实际 {len(rubber.home_slots)} 个"
            )
        if len(rubber.away_slots) != expected:
            raise TeamFormatError(
                f"赛制「{spec.code}」第 {rubber.sequence} 盘是 {rubber.rubber_type}，"
                f"客队需要 {expected} 个位置，实际 {len(rubber.away_slots)} 个"
            )


# ------------------------------------------------------------ 快照（序列化）

def snapshot_dict(spec: TeamFormatSpec) -> dict[str, Any]:
    """规格 -> 可 JSON 化的快照字典（先校验，保证写进 DB 的东西一定是自洽的）。"""
    validate_format_spec(spec)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "code": spec.code,
        "version": spec.version,
        "display_name": spec.display_name,
        "rubbers_to_win": spec.rubbers_to_win,
        "rubbers": [
            {
                "sequence": r.sequence,
                "rubber_type": r.rubber_type,
                "home_slots": list(r.home_slots),
                "away_slots": list(r.away_slots),
            }
            for r in sorted(spec.rubbers, key=lambda r: r.sequence)
        ],
    }


def dump_snapshot(spec: TeamFormatSpec) -> str:
    """规格 -> 存储用 JSON 文本（紧凑、键序稳定，便于断言与 diff）。"""
    return json.dumps(snapshot_dict(spec), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _slots_from_json(value: Any, sequence: int, side_label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
        raise TeamFormatError(f"快照第 {sequence} 盘的{side_label}位置必须是字符串列表")
    return tuple(value)


def spec_from_snapshot(data: Any) -> TeamFormatSpec:
    """快照字典 -> 规格（读取历史快照时必须走这里，不要信任 DB 里的 JSON）。"""
    if not isinstance(data, dict):
        raise TeamFormatError("赛制快照必须是 JSON 对象")
    version = data.get("snapshot_version", SNAPSHOT_VERSION)
    if version != SNAPSHOT_VERSION:
        raise TeamFormatError(f"不支持的赛制快照版本：{version!r}")
    raw_rubbers = data.get("rubbers")
    if not isinstance(raw_rubbers, list):
        raise TeamFormatError("赛制快照缺少 rubbers 列表")

    rubbers: list[RubberTemplate] = []
    for item in raw_rubbers:
        if not isinstance(item, dict):
            raise TeamFormatError("赛制快照的每一盘必须是 JSON 对象")
        sequence = item.get("sequence")
        rubber_type = item.get("rubber_type")
        rubbers.append(
            RubberTemplate(
                sequence=sequence if isinstance(sequence, int) else -1,
                rubber_type=rubber_type if isinstance(rubber_type, str) else "",
                home_slots=_slots_from_json(item.get("home_slots"), sequence, "主队"),
                away_slots=_slots_from_json(item.get("away_slots"), sequence, "客队"),
            )
        )

    spec = TeamFormatSpec(
        code=data.get("code") if isinstance(data.get("code"), str) else "",
        version=data.get("version") if isinstance(data.get("version"), int) else 0,
        display_name=data.get("display_name") if isinstance(data.get("display_name"), str) else "",
        rubbers_to_win=data.get("rubbers_to_win") if isinstance(data.get("rubbers_to_win"), int) else 0,
        rubbers=tuple(rubbers),
    )
    validate_format_spec(spec)
    return spec


def load_snapshot(text: str) -> TeamFormatSpec:
    """存储的 JSON 文本 -> 规格。"""
    if not isinstance(text, str) or text.strip() == "":
        raise TeamFormatError("赛制快照文本为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeamFormatError(f"赛制快照不是合法 JSON：{exc.msg}") from None
    return spec_from_snapshot(data)


# ------------------------------------------------------------ 生产注册表

#: 生产赛制注册表。A3 故意留空：没有任何一条团体赛规则被确认冻结。
PRODUCTION_FORMATS: dict[str, TeamFormatSpec] = {}


def register_format_spec(spec: TeamFormatSpec) -> None:
    """登记一个赛制版本（同一 code 视为同一赛制，用 version 区分版本）。"""
    validate_format_spec(spec)
    PRODUCTION_FORMATS[spec.code] = spec


def get_format_spec(code: str) -> TeamFormatSpec:
    """按 code 取赛制；未登记一律报错，绝不返回"默认赛制"。"""
    if not isinstance(code, str) or code.strip() == "":
        raise TeamFormatError("赛制 code 不能为空")
    spec = PRODUCTION_FORMATS.get(code)
    if spec is None:
        raise TeamFormatError(f"未知的团体赛赛制：{code}（生产注册表尚未冻结任何赛制）")
    return spec


# ------------------------------------------------------------ 骨架构建

def build_rubber_skeleton(spec: TeamFormatSpec) -> list[dict[str, Any]]:
    """按规格生成盘骨架。

    返回的每一项对应 team_rubbers 的一行（服务层负责 JSON 序列化与落库）：
      sequence / rubber_type / home_slots / away_slots / status
    A3 只生成 status=PENDING 且 match_id 为 NULL 的骨架：
    一盘具体对应哪场 Match、由谁上场、什么时候打，全部留给 A4。
    """
    validate_format_spec(spec)
    skeleton: list[dict[str, Any]] = []
    for rubber in sorted(spec.rubbers, key=lambda r: r.sequence):
        skeleton.append(
            {
                "sequence": rubber.sequence,
                "rubber_type": rubber.rubber_type,
                "home_slots": list(rubber.home_slots),
                "away_slots": list(rubber.away_slots),
                "status": TeamRubberStatus.PENDING.value,
            }
        )
    return skeleton
