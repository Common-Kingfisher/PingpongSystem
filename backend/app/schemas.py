"""Pydantic 请求/响应模型。"""

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .models import (
    BronzeMode,
    EventType,
    MatchBracket,
    MatchStage,
    MatchStatus,
    PlacementMode,
    PreflightLevel,
    ResultType,
    TableStatus,
    TeamRubberStatus,
    TeamRubberType,
    TeamSide,
    TeamTieStatus,
    TournamentMode,
    TournamentStage,
)


class TournamentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    date: date
    table_count: int = Field(ge=1, le=15)
    group_count: int = Field(ge=1, le=26)
    qualify_per_group: int = Field(ge=1, le=20)
    event_type: EventType = EventType.SINGLES
    bronze_mode: BronzeMode = BronzeMode.JOINT_BRONZE
    placement_mode: PlacementMode = PlacementMode.OFF
    games_to_win: int = Field(default=2, ge=1, le=4)
    points_to_win: int = Field(default=11, ge=1, le=99)
    operation_mode: TournamentMode = TournamentMode.LIVE


class TournamentOut(BaseModel):
    id: int
    name: str
    date: date
    table_count: int
    group_count: int
    qualify_per_group: int
    stage: TournamentStage
    created_at: str
    event_type: EventType = EventType.SINGLES
    bronze_mode: BronzeMode = BronzeMode.JOINT_BRONZE
    placement_mode: PlacementMode = PlacementMode.OFF
    games_to_win: int = 2
    points_to_win: int = 11
    roster_confirmed: bool = False
    confirmed_at: str | None = None
    operation_mode: TournamentMode = TournamentMode.LIVE


class PlayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    college: str | None = Field(default=None, max_length=100)
    rating_points: int = Field(default=1000, ge=0, le=99999)


class PlayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    college: str | None = Field(default=None, max_length=100)
    rating_points: int | None = Field(default=None, ge=0, le=99999)


class PlayerOut(BaseModel):
    id: int
    tournament_id: int
    name: str
    college: str | None
    group_id: int | None
    seed_no: int | None
    rating_points: int = 1000


class EntryMemberOut(BaseModel):
    player_id: int
    name: str
    college: str | None
    rating_points: int
    member_order: int


class EntryOut(BaseModel):
    id: int
    tournament_id: int
    entry_type: EventType
    display_name: str
    rating_points: int
    group_id: int | None
    seed_no: int | None
    status: str
    withdrawn_at: str | None = None
    withdrawn_by: str | None = None
    withdrawal_reason: str | None = None
    members: list[EntryMemberOut]


class EntryWithdrawRequest(BaseModel):
    operator_name: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=2, max_length=500)


class EntryWithdrawalResult(BaseModel):
    entry: EntryOut
    affected_match_ids: list[int]
    preserved_finished_matches: int


class PairingResult(BaseModel):
    entries: list[EntryOut]
    unpaired_players: list[PlayerOut]
    pairing_seed: int


class PairingRequest(BaseModel):
    pairing_seed: int | None = None


class ConfirmRosterResult(BaseModel):
    tournament: TournamentOut
    entries: list[EntryOut]


# ------------------------------------------------------------ 团体赛（A3）
# 队伍本身就是 Entry（entry_type='TEAM'），所以队伍的读写复用 EntryOut / EntryMemberOut，
# 不为"队伍"再造一份字段相同的 DTO。


class TeamEntryCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    member_ids: list[int] = Field(min_length=1)
    # 团体赛种子规则尚未冻结：这里只接受显式积分，不做队员积分推导。缺省 0。
    rating_points: int = Field(default=0, ge=0, le=99999)


class TeamEntryUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    member_ids: list[int] | None = Field(default=None, min_length=1)
    rating_points: int | None = Field(default=None, ge=0, le=99999)


class TeamTieCreate(BaseModel):
    entry_a_id: int
    entry_b_id: int
    stage: MatchStage = MatchStage.GROUP
    group_id: int | None = None
    round: int = Field(default=1, ge=1)
    match_index: int | None = Field(default=None, ge=1)


class GenerateTeamGroupTiesResult(BaseModel):
    """团体小组循环对阵生成结果（A6.1）。

    刻意保持最小：只回答"生成了多少场、每个组多少场"。
    这里**没有**排名、积分、出线、stage 等字段——团体小组积分与晋级规则尚未冻结，
    生成器也不推进赛事阶段，返回一个看起来像"小组赛已完成"的 DTO 会误导消费方。
    """

    ties_generated: int
    #: 组名 → 该组生成的对抗数（例如 {"A组": 6, "B组": 6}）。
    per_group: dict[str, int]


class TeamStandingRowOut(BaseModel):
    """团体小组排名的一行（A6.2）。

    名次用**区间**表示：`rank_start == rank_end` 表示名次唯一；
    并列时同组所有队伍共享同一区间且 `ambiguous = true`（绝不按 id 打破同分）。
    """

    team_entry_id: int
    team_name: str
    #: ACTIVE / WITHDRAWN（退赛队伍保留成绩，但不可晋级）。
    status: str
    #: 比赛积分：正常完赛胜方 2、负方 1；未完成对抗不计入。
    match_points: int
    ties_played: int
    ties_won: int
    ties_lost: int
    rubber_wins: int
    rubber_losses: int
    games_won: int
    games_lost: int
    rank_start: int
    rank_end: int
    ambiguous: bool
    eligible_for_qualification: bool
    #: 名次相对晋级线的**事实描述**（RESOLVED / UNDECIDED / ELIGIBLE_ONLY），
    #: 不是晋级结果；A6.3 才写入真正的 qualification。
    qualification_position_state: str


class TeamGroupStandingsOut(BaseModel):
    """一个小组的团体排名（A6.2，只读、每次从真实事实重算）。

    **刻意不包含** `qualified: true/false`：晋级写入属于 A6.3。
    """

    group_id: int
    group_name: str
    #: 组内是否还有未完成的对抗（含涉及已退赛队伍的）→ 排名不是最终结果。
    provisional: bool
    #: 是否存在无法区分的并列（至少一行 ambiguous）。
    ambiguous: bool
    #: provisional 为真时**必须**为 false：V1 不做结果可能性分析。
    automatic_qualification_allowed: bool
    #: 实际生效的晋级名额（组级覆盖值优先，否则赛事默认值）。
    qualify_count: int
    standings: list[TeamStandingRowOut]


class TeamLineupOptionOut(BaseModel):
    """某一边的候选上场队员（B 直接渲染成可点选列表）。"""

    player_id: int
    name: str
    available: bool
    # available=false 时必须给出可展示原因（例如"本盘已开始或已结束，阵容已锁定"）。
    unavailable_reason: str | None = None


class TeamLineupOptionsOut(BaseModel):
    """候选阵容按边分组：每边的候选只来自本队，不做跨边混合。"""

    home: list[TeamLineupOptionOut]
    away: list[TeamLineupOptionOut]


class TeamPermissionOut(BaseModel):
    """后端计算的操作权限；前端按钮直接消费这些字段，不得自行推导状态机。"""

    can_edit_lineup: bool
    can_confirm_lineup: bool
    can_start: bool
    can_record_score: bool
    can_revise_score: bool


class TeamFormatRuntimeOut(BaseModel):
    """对抗当前使用的赛制（未建盘/未登记时全部为 null，前端不得据此推算盘序）。"""

    code: str | None = None
    version: int | None = None
    display_name: str | None = None
    # 获胜所需盘数，只能由后端从赛制快照读取。
    rubbers_to_win: int | None = None


class TeamSummaryOut(BaseModel):
    """对抗的一边；成员内嵌，避免前端为显示队伍再发多次请求。"""

    entry_id: int
    display_name: str
    status: str
    members: list[EntryMemberOut]


class TeamRubberRuntimeOut(BaseModel):
    """一盘的完整运行态：位置需求 + 实际阵容 + 比分 + 权限 + 候选阵容。"""

    id: int
    team_tie_id: int
    sequence: int
    rubber_type: TeamRubberType
    status: TeamRubberStatus
    # A3 的"位置需求"（例如 DOUBLE 盘需要 2 个位置）；与实际上场人是两件事。
    home_slots: list[str]
    away_slots: list[str]
    # 本盘实际参赛人：id 用于写操作，name 用于展示。
    home_player_ids: list[int]
    away_player_ids: list[int]
    home_players: list[str]
    away_players: list[str]
    home_score: int | None = None
    away_score: int | None = None
    winner_side: TeamSide | None = None
    winner_entry_id: int | None = None
    # 预留给以后的 Match 适配器；A4.1 仍然恒为 None（一盘不是一场普通比赛）。
    match_id: int | None = None
    # 已保存阵容是否仍满足"选手属于本队 + 队伍在赛"；失效时 start 会 409（可重新提交阵容）。
    lineup_valid: bool = True
    lineup_invalid_reason: str | None = None
    permissions: TeamPermissionOut
    lineup_options: TeamLineupOptionsOut
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class TeamTieOut(BaseModel):
    id: int
    tournament_id: int
    stage: MatchStage
    group_id: int | None
    round: int
    match_index: int | None
    entry_a_id: int
    entry_b_id: int
    team_a_score: int
    team_b_score: int
    winner_entry_id: int | None
    status: TeamTieStatus
    format_code: str | None
    format_version: int | None
    # 建盘时固化的赛制快照（原样存储的 JSON 文本，便于排障与回放）。
    format_snapshot: str | None
    called_at: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str


class TeamTieRuntimeOut(TeamTieOut):
    """对抗的统一运行态契约（A4.1）。

    它是 A3 详情响应（TeamTieOut + rubbers）的**超集**：原有字段与命名全部保留，
    只追加 B 需要的运行态字段，因此升级是向后兼容的（旧消费方不会因为改名而断裂）。
    所有修改运行态的写接口都直接返回这个结构，前端整体替换即可，无需二次拉取。
    """

    home_team: TeamSummaryOut
    away_team: TeamSummaryOut
    home_score: int
    away_score: int
    # 从赛制快照读取的获胜所需盘数；没有可用快照时为 null。
    target_wins: int | None = None
    format: TeamFormatRuntimeOut
    rubbers: list[TeamRubberRuntimeOut]
    permissions: TeamPermissionOut


class RubberSkeletonRequest(BaseModel):
    format_code: str = Field(min_length=1, max_length=50)
    replace: bool = False


class TeamLineupRequest(BaseModel):
    """提交一盘的实际参赛人（覆盖式写入）。"""

    home_player_ids: list[int]
    away_player_ids: list[int]


class TeamRubberScoreRequest(BaseModel):
    """盘比分（胜局数）。合法性由后端按赛事 games_to_win 校验，前端不得自行放宽。"""

    home_score: int
    away_score: int


class SetSeedsRequest(BaseModel):
    player_ids: list[int]


class GenerateDemoPlayersRequest(BaseModel):
    count: int = Field(ge=1, le=24)
    with_seeds: bool = True


class DemoFinishGroupStageResult(BaseModel):
    finished: int


class ImportRowError(BaseModel):
    row: int
    message: str


class ImportPlayersResult(BaseModel):
    total_rows: int
    imported: int
    skipped: int
    errors: list[ImportRowError]


class ImportPreviewRow(BaseModel):
    row: int
    name: str
    college: str | None
    rating_points: int
    seed_no: int | None
    status: str
    message: str | None


class ImportPreviewResult(BaseModel):
    total_rows: int
    valid_rows: int
    skipped: int
    errors: list[ImportRowError]
    rows: list[ImportPreviewRow]


class TableOut(BaseModel):
    id: int
    tournament_id: int
    name: str
    status: TableStatus


class GroupPlayerOut(BaseModel):
    id: int
    name: str
    college: str | None


class GroupOut(BaseModel):
    id: int
    name: str
    sort_order: int
    qualify_count: int | None = None
    players: list[GroupPlayerOut]
    entries: list[EntryOut] = []


class GroupingResult(BaseModel):
    groups: list[GroupOut]


class GroupQualifyUpdate(BaseModel):
    qualify_count: int = Field(ge=1, le=20)


class MatchOut(BaseModel):
    id: int
    tournament_id: int
    stage: MatchStage
    group_id: int | None
    round: int
    match_index: int | None
    player_a_id: int | None
    player_b_id: int | None
    player_a_score: int | None
    player_b_score: int | None
    winner_id: int | None
    table_id: int | None
    status: MatchStatus
    prev_match_a_id: int | None
    prev_match_b_id: int | None
    entry_a_id: int | None = None
    entry_b_id: int | None = None
    winner_entry_id: int | None = None
    entry_a_name: str | None = None
    entry_b_name: str | None = None
    result_type: ResultType | None = None
    forfeit_entry_id: int | None = None
    result_note: str | None = None
    bracket: MatchBracket = MatchBracket.GROUP
    placement_min: int | None = None
    placement_max: int | None = None
    # A2 比赛时间基础：UTC SQLite 时间戳 'YYYY-MM-DD HH:MM:SS'
    # called_at 最近一次安排上球台；started_at 当前有效进行中比赛的开始时间（下球台后为空）；
    # finished_at 当前有效比赛产生结果的时间（改分不改变）。
    called_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    games: list["MatchGameOut"] = []


class GenerateMatchesResult(BaseModel):
    matches_generated: int
    per_group: dict[str, int]
    tournament: TournamentOut


class AssignTableRequest(BaseModel):
    table_id: int


class ScheduleNextResult(BaseModel):
    assigned: int
    assignments: list[dict[str, int]]


class ScheduleEstimateMatch(BaseModel):
    """单场 WAITING 比赛的预计上场时间（无法估算时字段为 null）。"""

    match_id: int
    stage: MatchStage
    round: int
    group_id: int | None = None
    estimated_start_at: str | None = None
    estimated_wait_minutes: float | None = None
    queue_ahead: int | None = None
    estimate_basis: str | None = None
    unavailable_reason: str | None = None


class ScheduleEstimates(BaseModel):
    """赛事预计上场时间（只读模拟结果）。"""

    tournament_id: int
    generated_at: str
    estimated_match_duration_seconds: int
    estimate_basis: str
    sample_count: int
    initial_playing_matches: int = 0
    simulated_batches: int = 0
    truncated: bool = False
    matches: list[ScheduleEstimateMatch] = []


class DashboardStats(BaseModel):
    total: int
    finished: int
    playing: int
    waiting: int


class TableWithMatch(BaseModel):
    id: int
    name: str
    status: TableStatus
    match: MatchOut | None
    # 空闲球台的调度建议（服务端调度器算出，前端只展示不重算优先级）。
    recommended_match_id: int | None = None


class Dashboard(BaseModel):
    tournament: TournamentOut
    stats: DashboardStats
    tables: list[TableWithMatch]
    next_playable: list[MatchOut]


class MatchGameInput(BaseModel):
    side_a_score: int = Field(ge=0, le=99)
    side_b_score: int = Field(ge=0, le=99)


class MatchGameOut(BaseModel):
    id: int
    match_id: int
    game_no: int
    side_a_score: int
    side_b_score: int
    winner_entry_id: int | None = None


class ScoreRequest(BaseModel):
    player_a_score: int | None = Field(default=None, ge=0)
    player_b_score: int | None = Field(default=None, ge=0)
    games: list[MatchGameInput] | None = None
    result_type: ResultType = ResultType.NORMAL
    forfeit_entry_id: int | None = None
    note: str | None = Field(default=None, max_length=500)
    request_id: UUID | None = None
    operator_name: str | None = Field(default=None, max_length=100)
    change_reason: str | None = Field(default=None, max_length=500)


class ScoreRevisionRequest(ScoreRequest):
    """改分请求必须在机器可读契约中明确携带操作人和原因。"""

    operator_name: str = Field(min_length=1, max_length=100)
    change_reason: str = Field(min_length=2, max_length=500)


class ScoreAuditOut(BaseModel):
    id: int
    match_id: int
    action: str
    before_snapshot: dict
    after_snapshot: dict
    operator_name: str | None
    change_reason: str | None
    request_id: str | None
    created_at: str


class RankingEntryOut(BaseModel):
    player_id: int
    name: str
    wins: int
    losses: int
    games_won: int
    games_lost: int
    rank: int
    tied: bool
    qualified: bool
    entry_id: int | None = None
    match_points: int = 0
    points_won: int = 0
    points_lost: int = 0
    point_difference: int = 0
    point_ratio: float = 0
    entry_status: str = "ACTIVE"


class QualificationDecisionCreate(BaseModel):
    selected_entry_ids: list[int] = Field(min_length=1)
    reason: str = Field(min_length=2, max_length=500)
    operator_name: str = Field(min_length=1, max_length=100)


class QualificationDecisionRevoke(BaseModel):
    reason: str = Field(min_length=2, max_length=500)
    operator_name: str = Field(min_length=1, max_length=100)


class QualificationDecisionOut(BaseModel):
    id: int
    tournament_id: int
    group_id: int
    selected_entry_ids: list[int]
    reason: str
    operator_name: str
    created_at: str
    invalidated_at: str | None = None
    invalidation_reason: str | None = None
    active: bool


class GroupRankingOut(BaseModel):
    group_id: int
    group_name: str
    qualify_count: int
    total_matches: int
    finished_matches: int
    ambiguous_qualification: bool
    needs_point_scores: bool = False
    point_score_match_ids: list[int] = []
    manually_resolved: bool = False
    manual_candidate_entry_ids: list[int] = []
    manual_slots_remaining: int = 0
    qualification_decision: QualificationDecisionOut | None = None
    entries: list[RankingEntryOut]


class RankingsResult(BaseModel):
    rankings: list[GroupRankingOut]


class PlayerBrief(BaseModel):
    id: int
    name: str | None
    seed_no: int | None = None
    member_names: list[str] = []


class KnockoutMatchOut(BaseModel):
    id: int
    round: int
    match_index: int
    status: MatchStatus
    player_a: PlayerBrief | None
    player_b: PlayerBrief | None
    player_a_score: int | None
    player_b_score: int | None
    winner_id: int | None
    table_id: int | None
    prev_match_a_id: int | None
    prev_match_b_id: int | None
    bracket: MatchBracket = MatchBracket.MAIN
    placement_min: int | None = None
    placement_max: int | None = None
    result_type: ResultType | None = None
    called_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class KnockoutRoundOut(BaseModel):
    round: int
    label: str
    matches: list[KnockoutMatchOut]


class KnockoutTree(BaseModel):
    tournament: TournamentOut
    rounds: list[KnockoutRoundOut]
    champion: PlayerBrief | None
    runner_up: PlayerBrief | None
    placements: list[dict] = []
    placement_matches: list[dict] = []
    champion_path_match_ids: list[int] = []


class OrderBookSnapshot(BaseModel):
    snapshot_at: str
    tournament: TournamentOut
    entries: list[EntryOut]
    groups: GroupingResult
    rankings: RankingsResult
    tree: KnockoutTree
    matches: list[MatchOut]
    dashboard: Dashboard


class TournamentResults(BaseModel):
    tournament: TournamentOut
    champion: PlayerBrief | None
    runner_up: PlayerBrief | None
    placements: list[dict]
    total_matches: int
    finished_matches: int


class PreflightCheckOut(BaseModel):
    code: str
    title: str
    detail: str
    level: PreflightLevel
    action_label: str | None = None
    action_path: str | None = None


class PreflightResult(BaseModel):
    tournament: TournamentOut
    overall: PreflightLevel
    ready_count: int
    warning_count: int
    blocker_count: int
    metrics: dict[str, int]
    checks: list[PreflightCheckOut]


class KnockoutUndoResult(BaseModel):
    """撤销淘汰签表的结果：只报告删除了哪些淘汰阶段派生数据。"""

    tournament: TournamentOut
    deleted_main_matches: int
    deleted_placement_matches: int
    deleted_matches: int


class GroupRecordOut(BaseModel):
    """groups 表的落库形态（与运行期分组视图 GroupOut 区分）。"""

    id: int
    tournament_id: int
    name: str
    sort_order: int
    qualify_count: int | None = None


class EntryMemberRecordOut(BaseModel):
    """entry_members 表的落库形态。"""

    entry_id: int
    player_id: int
    member_order: int


class ScoreRequestOut(BaseModel):
    """比分写入审计账本（幂等编号）。"""

    request_id: str
    match_id: int
    action: str
    payload_fingerprint: str
    created_at: str


class TeamTieRecordOut(BaseModel):
    """team_ties 表的落库形态（A3 追加，单打/双打赛事恒为空列表）。"""

    id: int
    tournament_id: int
    stage: str
    group_id: int | None = None
    round: int
    match_index: int | None = None
    entry_a_id: int
    entry_b_id: int
    team_a_score: int
    team_b_score: int
    winner_entry_id: int | None = None
    status: str
    format_code: str | None = None
    format_version: int | None = None
    format_snapshot: str | None = None
    called_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str


class TeamRubberRecordOut(BaseModel):
    """team_rubbers 表的落库形态：位置需求保持存储时的 JSON 文本，运行态字段一并导出。"""

    id: int
    team_tie_id: int
    sequence: int
    rubber_type: str
    home_slots_json: str
    away_slots_json: str
    status: str
    match_id: int | None = None
    created_at: str
    # A4.1 运行态：lineup 绑定 / 盘比分 / 胜者 / 起止时间
    home_player_ids_json: str | None = None
    away_player_ids_json: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    winner_entry_id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class QualificationDecisionExport(BaseModel):
    """人工晋级裁定的导出形态：额外带上冻结的排名快照证据。

    ranking_snapshot 由 rankings.qualification_snapshot() 写入，是 JSON 对象
    （group_id / qualify_count / 各组进度 / 参赛位名次明细）。
    """

    id: int
    group_id: int
    selected_entry_ids: list[int]
    ranking_snapshot: dict[str, Any] = {}
    reason: str
    operator_name: str
    created_at: str
    invalidated_at: str | None = None
    invalidation_reason: str | None = None
    active: bool


class TournamentExportDerived(BaseModel):
    """运行期推导结果，不属于落库数据。"""

    rankings: list[GroupRankingOut]
    champion: PlayerBrief | None = None
    runner_up: PlayerBrief | None = None
    placements: list[dict] = []


class TournamentExport(BaseModel):
    """赛事结构化导出：schema_version + 落库数据 + 推导结果。"""

    schema_version: str
    exported_at: str
    tournament: TournamentOut
    players: list[PlayerOut]
    entries: list[EntryOut]
    entry_members: list[EntryMemberRecordOut]
    groups: list[GroupRecordOut]
    tables: list[TableOut]
    matches: list[MatchOut]
    match_games: list[MatchGameOut]
    qualification_decisions: list[QualificationDecisionExport]
    score_requests: list[ScoreRequestOut]
    team_ties: list[TeamTieRecordOut]
    team_rubbers: list[TeamRubberRecordOut]
    derived: TournamentExportDerived
