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
    members: list[EntryMemberOut]


class PairingResult(BaseModel):
    entries: list[EntryOut]
    unpaired_players: list[PlayerOut]
    pairing_seed: int


class PairingRequest(BaseModel):
    pairing_seed: int | None = None


class ConfirmRosterResult(BaseModel):
    tournament: TournamentOut
    entries: list[EntryOut]


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
    derived: TournamentExportDerived
