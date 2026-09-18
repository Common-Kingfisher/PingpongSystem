"""团体对抗（TeamTie）与盘骨架（TeamRubber）路由。

A3 只提供：建立对抗、读取对抗/盘骨架、按已冻结赛制生成盘骨架。
比分、状态机、排程、对阵编排都不在这里（见 services/team_ties.py 顶部说明）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import team_ties as tie_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/team-ties", tags=["team-ties"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("", response_model=list[schemas.TeamTieOut])
def list_team_ties(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        return tie_service.list_team_ties(conn, tournament_id)
    except tie_service.TeamTieError as exc:
        raise _http(exc)


@router.post("", response_model=schemas.TeamTieOut, status_code=201)
def create_team_tie(
    tournament_id: int,
    payload: schemas.TeamTieCreate,
    conn: Connection = Depends(get_db),
):
    try:
        return tie_service.create_team_tie(
            conn,
            tournament_id,
            payload.entry_a_id,
            payload.entry_b_id,
            payload.stage.value,
            payload.group_id,
            payload.round,
            payload.match_index,
        )
    except tie_service.TeamTieError as exc:
        raise _http(exc)


@router.get("/{tie_id}", response_model=schemas.TeamTieDetailOut)
def get_team_tie(tournament_id: int, tie_id: int, conn: Connection = Depends(get_db)):
    try:
        return tie_service.get_team_tie(conn, tournament_id, tie_id)
    except tie_service.TeamTieError as exc:
        raise _http(exc)


@router.post("/{tie_id}/rubber-skeleton", response_model=schemas.TeamTieDetailOut)
def build_rubber_skeleton(
    tournament_id: int,
    tie_id: int,
    payload: schemas.RubberSkeletonRequest,
    conn: Connection = Depends(get_db),
):
    try:
        return tie_service.build_rubber_skeleton(
            conn, tournament_id, tie_id, payload.format_code, payload.replace
        )
    except tie_service.TeamTieError as exc:
        raise _http(exc)
