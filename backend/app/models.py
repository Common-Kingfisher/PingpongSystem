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
    """参赛项目。第一版完整支持单打与固定搭档双打。"""

    SINGLES = "SINGLES"
    DOUBLES = "DOUBLES"


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
