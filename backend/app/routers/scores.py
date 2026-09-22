"""比分与排名路由。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..dependencies import (
    require_public_tournament_read,
    require_tournament_read,
    require_tournament_write,
)
from ..services import rankings as rankings_service
from ..services import scores as scores_service

router = APIRouter(tags=["scores"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.post("/api/matches/{match_id}/score", response_model=schemas.MatchOut)
def record_score(
    match_id: int,
    payload: schemas.ScoreRequest,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        match = scores_service.record_score(
            conn,
            match_id,
            payload.player_a_score,
            payload.player_b_score,
            [(g.side_a_score, g.side_b_score) for g in payload.games] if payload.games is not None else None,
            payload.result_type.value,
            payload.forfeit_entry_id,
            payload.note,
            str(payload.request_id) if payload.request_id is not None else None,
            payload.operator_name,
            payload.change_reason,
        )
    except scores_service.ScoreError as exc:
        raise _http(exc)
    return schemas.MatchOut(**match)


@router.post("/api/matches/{match_id}/revise-score", response_model=schemas.MatchOut)
def revise_score(
    match_id: int,
    payload: schemas.ScoreRevisionRequest,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        match = scores_service.revise_score(
            conn,
            match_id,
            payload.player_a_score,
            payload.player_b_score,
            [(g.side_a_score, g.side_b_score) for g in payload.games] if payload.games is not None else None,
            payload.result_type.value,
            payload.forfeit_entry_id,
            payload.note,
            str(payload.request_id) if payload.request_id is not None else None,
            payload.operator_name,
            payload.change_reason,
            True,
        )
    except scores_service.ScoreError as exc:
        raise _http(exc)
    return schemas.MatchOut(**match)


@router.get("/api/matches/{match_id}/score-audits", response_model=list[schemas.ScoreAuditOut])
def list_score_audits(
    match_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    if repo.get_match(conn, match_id) is None:
        raise HTTPException(status_code=404, detail="比赛不存在")
    result = []
    for item in repo.list_score_audits(conn, match_id):
        item["before_snapshot"] = json.loads(item["before_snapshot"])
        item["after_snapshot"] = json.loads(item["after_snapshot"])
        result.append(schemas.ScoreAuditOut(**item))
    return result


@router.get("/api/tournaments/{tournament_id}/rankings", response_model=schemas.RankingsResult)
def get_rankings(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_public_tournament_read),
):
    try:
        data = rankings_service.get_rankings(conn, tournament_id)
    except rankings_service.RankingError as exc:
        raise _http(exc)
    return schemas.RankingsResult(
        rankings=[schemas.GroupRankingOut(**g) for g in data]
    )
