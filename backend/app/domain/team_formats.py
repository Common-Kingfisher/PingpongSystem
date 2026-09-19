"""团体赛赛制规格（TeamFormatSpec）与出场骨架（Rubber skeleton）——纯函数。

只描述"一场团体对抗由哪几盘组成、每盘每边需要几个出场位置"，
不涉及谁上场（TeamLineup / 位置分配属于 Runtime），也不涉及排程与比分状态机。

诚实边界（必须保留这些说明，不要删）：
1. **生产注册表只放组织者确认过的平台模板，且必须版本化。** 当前只有
   `LOCAL_CLASSIC_5_V1`（A5）：它是"平台第一版生产团体赛模板"，采用 5 盘、先赢 3 盘、
   单/单/双/单/单的盘结构。它**不声明**等同于任何一届 ITTF / 奥运会 / 中国乒协的官方规则，
   也刻意不使用 `ITTF_*` / `OLYMPIC` / `NATIONAL_STANDARD` 这类会被读成"官方认证"的名字。
   赛事组织方若提供正式规程，一律**新增**版本化 TeamFormatSpec，绝不覆盖已发布的版本。
   测试里使用的规格只存在于测试代码中（`TEST_ONLY_*`），不进入生产注册表。
2. 校验只保证"规格自洽"：结构合法、盘序从 1 连续、每盘位置数符合单打/双打的定义、
   盘数不少于获胜所需盘数。它不假设任何一条真实赛事规则。
3. 快照（snapshot）把规格固化成 JSON：赛事进行中即使注册表升级（新增 V2 或下线 V1），
   已创建的对抗仍按创建时的 format_code + format_version + format_snapshot 解释，
   不会被新规则追溯改写。
4. **只冻结能驱动 Runtime 的最低必要信息**：盘数、盘类型顺序、获胜所需盘数。
   选手角色映射（A/B/C/X/Y/Z）、谁打一单、双打由谁组成、兼项与最多打几盘、替补规则与时机、
   是否必须严格按 sequence 开赛、双打组合提交时机、团体小组积分规则**全部未冻结**，
   因此"位置代号"（slots）只是骨架里的位置标识，不承载"某名固定选手必须打这里"的语义。
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

#: 生产赛制：`LOCAL_CLASSIC_5_V1`（A5 第一版平台生产团体赛模板）。
#:
#: 冻结的只有"驱动 Runtime 的最低必要信息"：
#:   - 5 盘，先赢 3 盘（`rubbers_to_win = 3`）；
#:   - 盘类型顺序 = 单打 / 单打 / 双打 / 单打 / 单打。
#:
#: **没有冻结**（因此下面这些一律不写进规格，Runtime 也不实现）：
#: 选手角色映射（A/B/C/X/Y/Z）、谁必须打一单/二单、双打由哪些人组成、
#: 同一人最多参加几盘、单打与双打能否兼项、是否允许替补与替补人数/时机、
#: 排阵提交时间、是否必须严格按 sequence 开赛、双打组合提交时机、团体小组积分规则。
#:
#: 位置代号用**中性**的 `HOME_R<序>` / `AWAY_R<序>`（双打再加 `_1` / `_2`）：
#: 它们只标"这一盘这一边的第几个位置"，刻意不用 A/B/C/X/Y/Z 之类会暗示
#: "固定角色 = 固定选手"的代号。实际上场人由 Runtime 的 lineup 决定。
LOCAL_CLASSIC_5_V1 = TeamFormatSpec(
    code="LOCAL_CLASSIC_5_V1",
    version=1,
    display_name="经典五盘三胜团体赛",
    rubbers_to_win=3,
    rubbers=(
        RubberTemplate(1, TeamRubberType.SINGLES.value, ("HOME_R1",), ("AWAY_R1",)),
        RubberTemplate(2, TeamRubberType.SINGLES.value, ("HOME_R2",), ("AWAY_R2",)),
        RubberTemplate(
            3,
            TeamRubberType.DOUBLES.value,
            ("HOME_R3_1", "HOME_R3_2"),
            ("AWAY_R3_1", "AWAY_R3_2"),
        ),
        RubberTemplate(4, TeamRubberType.SINGLES.value, ("HOME_R4",), ("AWAY_R4",)),
        RubberTemplate(5, TeamRubberType.SINGLES.value, ("HOME_R5",), ("AWAY_R5",)),
    ),
)

#: 生产赛制注册表：code → 规格。**只登记已确认冻结的平台模板**，不含 `TEST_ONLY_*`。
#: 注册表本身是"当前可用的版本清单"；一场对抗的规则真相永远是它自己的 `format_snapshot`。
PRODUCTION_FORMATS: dict[str, TeamFormatSpec] = {
    LOCAL_CLASSIC_5_V1.code: LOCAL_CLASSIC_5_V1,
}


def register_format_spec(spec: TeamFormatSpec, *, allow_version_bump: bool = False) -> None:
    """登记一个赛制版本；**已经存在的 code 一律拒绝覆盖**。

    为什么不再静默覆盖：`TeamFormat` 是版本化不可变定义。已创建的对抗虽然靠
    `format_snapshot` 自保，但同一个 code 出现两种含义会让导出、审计与人工排查产生歧义
    （"LOCAL_CLASSIC_5_V1 到底是 5 盘还是 7 盘？"）。因此规则变化必须**新增**新 code
    （例如 `..._V2`），而不是改写已发布的 code。

    - 新 code：登记成功。
    - 已存在同一 code：抛 `TeamFormatError`（继承 `ValueError`），**注册表保持原样**；
      即使传入更高的 version 也拒绝，除非显式 `allow_version_bump=True`
      （只有确认要修订同一 code 时才用，正常发版不走这条路）。
    - code 相同且对象就是同一个（幂等重复登记）：视为无操作，避免脚本/测试重复登记时误伤。
    """
    validate_format_spec(spec)
    existing = PRODUCTION_FORMATS.get(spec.code)
    if existing is not None and existing is not spec:
        if not allow_version_bump:
            raise TeamFormatError(
                f"赛制「{spec.code}」已登记（version={existing.version}），不能覆盖；"
                f"规则变化请新增版本化 code（例如 {spec.code}_V{spec.version}）"
            )
        if spec.version <= existing.version:
            raise TeamFormatError(
                f"赛制「{spec.code}」版本必须递增才能替换："
                f"已有 version={existing.version}，收到 version={spec.version}"
            )
    PRODUCTION_FORMATS[spec.code] = spec


def get_format_spec(code: str) -> TeamFormatSpec:
    """按 code 取赛制；未登记一律报错，绝不返回"默认赛制"。"""
    if not isinstance(code, str) or code.strip() == "":
        raise TeamFormatError("赛制 code 不能为空")
    # 通过模块属性读取：测试可以临时替换整个注册表（monkeypatch）而不影响生产清单。
    spec = PRODUCTION_FORMATS.get(code)
    if spec is None:
        raise TeamFormatError(f"未知的团体赛赛制：{code}（未登记的赛制不会被套用）")
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
