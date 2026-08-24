"""Demo 专用路由：一键生成演示选手、一键模拟剩余小组赛。

仅用于快速演示，不影响正式比赛逻辑（复用现有选手/比分服务）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import matches as matches_service
from ..services import players as players_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/demo", tags=["demo"])


@router.post("/generate-players", response_model=list[schemas.PlayerOut])
def generate_players(
    tournament_id: int,
    payload: schemas.GenerateDemoPlayersRequest,
    conn: Connection = Depends(get_db),
):
    try:
        players = players_service.generate_demo_players(
            conn, tournament_id, payload.count, payload.with_seeds
        )
    except players_service.PlayerError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return [schemas.PlayerOut(**p) for p in players]


@router.post("/finish-group-stage", response_model=schemas.DemoFinishGroupStageResult)
def finish_group_stage(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        finished = matches_service.finish_group_stage(conn, tournament_id)
    except matches_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except matches_service.TournamentStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return schemas.DemoFinishGroupStageResult(finished=finished)
