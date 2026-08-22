"""Pydantic 请求/响应模型。"""

from datetime import date

from pydantic import BaseModel, Field

from .models import TableStatus, TournamentStage


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
