"""Demo 专用路由：一键生成演示选手、一键模拟剩余小组赛。

仅用于快速演示，不影响正式比赛逻辑（复用现有选手/比分服务）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import matches as matches_service
from ..services import players as players_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/demo", tags=["demo"])


def _ensure_demo(conn: Connection, tournament_id: int) -> None:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    if tournament["operation_mode"] != "DEMO":
        raise HTTPException(status_code=409, detail="正式赛事禁止使用演示数据功能")


@router.post("/generate-players", response_model=list[schemas.PlayerOut])
def generate_players(
    tournament_id: int,
    payload: schemas.GenerateDemoPlayersRequest,
    conn: Connection = Depends(get_db),
):
    _ensure_demo(conn, tournament_id)
    try:
        players = players_service.generate_demo_players(
            conn, tournament_id, payload.count, payload.with_seeds
        )
    except players_service.PlayerError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return [schemas.PlayerOut(**p) for p in players]


@router.post("/finish-group-stage", response_model=schemas.DemoFinishGroupStageResult)
def finish_group_stage(tournament_id: int, conn: Connection = Depends(get_db)):
    _ensure_demo(conn, tournament_id)
    try:
        finished = matches_service.finish_group_stage(conn, tournament_id)
    except matches_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except matches_service.TournamentStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return schemas.DemoFinishGroupStageResult(finished=finished)
