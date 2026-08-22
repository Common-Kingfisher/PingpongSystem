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
