"""分组路由：自动分组、清空分组、查看分组。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import groups as groups_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["groups"])


@router.get("/groups", response_model=schemas.GroupingResult)
def get_groups(tournament_id: int, conn: Connection = Depends(get_db)):
    if repo.get_tournament(conn, tournament_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return schemas.GroupingResult(
        groups=groups_service.get_groups_with_players(conn, tournament_id)
    )


@router.post("/auto-group", response_model=schemas.GroupingResult)
def auto_group(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        groups = groups_service.auto_group_tournament(conn, tournament_id)
    except groups_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except groups_service.TournamentStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return schemas.GroupingResult(groups=groups)


@router.post("/ungroup", status_code=204)
def ungroup(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        groups_service.ungroup_tournament(conn, tournament_id)
    except groups_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except groups_service.TournamentStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
