"""比赛路由：生成小组赛、查看比赛列表。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import formats as format_service
from ..services import matches as matches_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["matches"])


@router.post("/generate-group-matches", response_model=schemas.GenerateMatchesResult)
def generate_group_matches(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        handler = format_service.resolve_format_handler(format_service.GROUP_KNOCKOUT)
        total, per_group = handler.generate_matches(conn, tournament_id)
    except format_service.FormatHandlerError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    except matches_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (
        matches_service.TournamentStageError,
        matches_service.NoGroupsError,
        matches_service.MatchesExistError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return schemas.GenerateMatchesResult(
        matches_generated=total,
        per_group=per_group,
        tournament=schemas.TournamentOut(**repo.get_tournament(conn, tournament_id)),
    )


@router.get("/matches", response_model=list[schemas.MatchOut])
def list_matches(
    tournament_id: int,
    stage: Literal["GROUP", "KNOCKOUT"] | None = Query(default=None),
    status: Literal["WAITING", "PLAYING", "FINISHED"] | None = Query(default=None),
    group_id: int | None = Query(default=None),
    conn: Connection = Depends(get_db),
):
    if repo.get_tournament(conn, tournament_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    matches = repo.list_matches(conn, tournament_id, stage=stage, status=status, group_id=group_id)
    return [schemas.MatchOut(**repo.decorate_match(conn, m)) for m in matches]
