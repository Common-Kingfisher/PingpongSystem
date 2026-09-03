"""比分与排名路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import rankings as rankings_service
from ..services import scores as scores_service

router = APIRouter(tags=["scores"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.post("/api/matches/{match_id}/score", response_model=schemas.MatchOut)
def record_score(
    match_id: int, payload: schemas.ScoreRequest, conn: Connection = Depends(get_db)
):
    try:
        match = scores_service.record_score(
            conn,
            match_id,
            payload.player_a_score,
            payload.player_b_score,
            [(g.side_a_score, g.side_b_score) for g in payload.games] if payload.games else None,
            payload.result_type.value,
            payload.forfeit_entry_id,
            payload.note,
        )
    except scores_service.ScoreError as exc:
        raise _http(exc)
    return schemas.MatchOut(**match)


@router.post("/api/matches/{match_id}/revise-score", response_model=schemas.MatchOut)
def revise_score(
    match_id: int, payload: schemas.ScoreRequest, conn: Connection = Depends(get_db)
):
    try:
        match = scores_service.revise_score(
            conn,
            match_id,
            payload.player_a_score,
            payload.player_b_score,
            [(g.side_a_score, g.side_b_score) for g in payload.games] if payload.games else None,
            payload.result_type.value,
            payload.forfeit_entry_id,
            payload.note,
        )
    except scores_service.ScoreError as exc:
        raise _http(exc)
    return schemas.MatchOut(**match)


@router.get("/api/tournaments/{tournament_id}/rankings", response_model=schemas.RankingsResult)
def get_rankings(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        data = rankings_service.get_rankings(conn, tournament_id)
    except rankings_service.RankingError as exc:
        raise _http(exc)
    return schemas.RankingsResult(
        rankings=[schemas.GroupRankingOut(**g) for g in data]
    )
