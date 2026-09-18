"""全部状态枚举。

规则：状态一律使用 Enum，代码中以枚举引用，DB 中存枚举的字符串 code，
API 返回同样的字符串 code。禁止把状态中文字符串散落在业务代码里。
"""

from enum import Enum


class MatchStatus(str, Enum):
    """比赛状态。"""

    WAITING = "WAITING"      # 待安排
    PLAYING = "PLAYING"      # 进行中（已分配球台）
    FINISHED = "FINISHED"    # 已结束（必须有比分与胜者）


class TableStatus(str, Enum):
    """球台状态。"""

    FREE = "FREE"            # 空闲
    OCCUPIED = "OCCUPIED"    # 占用（承载一场 PLAYING 比赛）


class TournamentStage(str, Enum):
    """赛事阶段。"""

    REGISTRATION = "REGISTRATION"  # 报名/筹备（选手管理、分组）
    GROUP_STAGE = "GROUP_STAGE"    # 小组循环赛
    KNOCKOUT = "KNOCKOUT"          # 淘汰赛
    FINISHED = "FINISHED"          # 已结束（产生冠军）


class MatchStage(str, Enum):
    """比赛所属赛段。"""

    GROUP = "GROUP"          # 小组循环赛
    KNOCKOUT = "KNOCKOUT"    # 淘汰赛


class EventType(str, Enum):
    """参赛项目。

    SINGLES / DOUBLES 走现有 Match（Entry vs Entry）引擎；
    TEAM 走 TeamTie / TeamRubber 两层的团体赛引擎（A3 只建立领域模型，
    不生成普通 Match：见 services/teams.py 与 services/team_ties.py）。
    任何"非单打即双打"的二元假设都必须显式改成三分支。
    """

    SINGLES = "SINGLES"
    DOUBLES = "DOUBLES"
    TEAM = "TEAM"


class TeamTieStatus(str, Enum):
    """团体对抗（TeamTie）状态。A3 只建立状态模型，状态机由 A4 实现。"""

    WAITING = "WAITING"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"


class TeamRubberStatus(str, Enum):
    """团体对抗内单盘（Rubber）状态。

    A3 的 skeleton 只会生成 PENDING；A4.1 起真正使用状态机：
    PENDING（未绑定阵容）→ READY（阵容合法）→ PLAYING（已开始）→ FINISHED（已录比分）；
    对抗被一方提前结束时，未打的 PENDING/READY 盘 → SKIPPED。
    """

    PENDING = "PENDING"
    READY = "READY"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"
    SKIPPED = "SKIPPED"


class TeamRubberType(str, Enum):
    """单盘类型：只允许单打或双打盘（TEAM 不是盘类型）。"""

    SINGLES = "SINGLES"
    DOUBLES = "DOUBLES"


class TeamSide(str, Enum):
    """团体对抗的两边（主队 / 客队）；用于盘结果与权限表达，不是球队身份。"""

    HOME = "HOME"
    AWAY = "AWAY"


class TournamentMode(str, Enum):
    """赛事运行模式。正式赛事禁止调用演示数据接口。"""

    LIVE = "LIVE"
    DEMO = "DEMO"


class BronzeMode(str, Enum):
    BRONZE_MATCH = "BRONZE_MATCH"
    JOINT_BRONZE = "JOINT_BRONZE"


class PlacementMode(str, Enum):
    OFF = "OFF"
    COMPLETE = "COMPLETE"
    TIERED = "TIERED"


class ResultType(str, Enum):
    NORMAL = "NORMAL"
    FORFEIT = "FORFEIT"
    WALKOVER = "WALKOVER"
    NO_SHOW = "NO_SHOW"
    DISQUALIFIED = "DISQUALIFIED"


class MatchBracket(str, Enum):
    GROUP = "GROUP"
    MAIN = "MAIN"
    PLACEMENT = "PLACEMENT"


class PreflightLevel(str, Enum):
    READY = "READY"
    WARN = "WARN"
    BLOCK = "BLOCK"
