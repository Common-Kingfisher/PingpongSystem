"""Pydantic 请求/响应模型。"""

from datetime import date

from pydantic import BaseModel, Field

from .models import MatchStage, MatchStatus, TableStatus, TournamentStage


class TournamentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    date: date
    table_count: int = Field(ge=4, le=8)
    group_count: int = Field(ge=1, le=8)
    qualify_per_group: int = Field(ge=1, le=20)


class TournamentOut(BaseModel):
    id: int
    name: str
    date: date
    table_count: int
    group_count: int
    qualify_per_group: int
    stage: TournamentStage
    created_at: str


class PlayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    college: str | None = Field(default=None, max_length=100)


class PlayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    college: str | None = Field(default=None, max_length=100)


class PlayerOut(BaseModel):
    id: int
    tournament_id: int
    name: str
    college: str | None
    group_id: int | None
    seed_no: int | None


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
    players: list[GroupPlayerOut]


class GroupingResult(BaseModel):
    groups: list[GroupOut]


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


class GenerateMatchesResult(BaseModel):
    matches_generated: int
    per_group: dict[str, int]
    tournament: TournamentOut


class AssignTableRequest(BaseModel):
    table_id: int


class ScheduleNextResult(BaseModel):
    assigned: int
    assignments: list[dict[str, int]]


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


class Dashboard(BaseModel):
    tournament: TournamentOut
    stats: DashboardStats
    tables: list[TableWithMatch]
    next_playable: list[MatchOut]


class ScoreRequest(BaseModel):
    player_a_score: int = Field(ge=0)
    player_b_score: int = Field(ge=0)


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


class GroupRankingOut(BaseModel):
    group_id: int
    group_name: str
    total_matches: int
    finished_matches: int
    ambiguous_qualification: bool
    entries: list[RankingEntryOut]


class RankingsResult(BaseModel):
    rankings: list[GroupRankingOut]


class PlayerBrief(BaseModel):
    id: int
    name: str | None
    seed_no: int | None = None


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


class KnockoutRoundOut(BaseModel):
    round: int
    label: str
    matches: list[KnockoutMatchOut]


class KnockoutTree(BaseModel):
    tournament: TournamentOut
    rounds: list[KnockoutRoundOut]
    champion: PlayerBrief | None
    runner_up: PlayerBrief | None
