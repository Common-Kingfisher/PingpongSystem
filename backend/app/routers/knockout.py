"""淘汰赛路由：生成淘汰赛、查看淘汰赛树。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import knockout as knockout_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["knockout"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.post("/generate-knockout", response_model=schemas.KnockoutTree)
def generate_knockout(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        tree = knockout_service.generate_knockout(conn, tournament_id)
    except knockout_service.KnockoutError as exc:
        raise _http(exc)
    return _to_schema(tree)


@router.get("/knockout", response_model=schemas.KnockoutTree)
def get_knockout(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        tree = knockout_service.get_knockout(conn, tournament_id)
    except knockout_service.KnockoutError as exc:
        raise _http(exc)
    return _to_schema(tree)


def _to_schema(tree: dict) -> schemas.KnockoutTree:
    return schemas.KnockoutTree(
        tournament=schemas.TournamentOut(**tree["tournament"]),
        rounds=[
            schemas.KnockoutRoundOut(
                round=r["round"],
                label=r["label"],
                matches=[schemas.KnockoutMatchOut(**m) for m in r["matches"]],
            )
            for r in tree["rounds"]
        ],
        champion=schemas.PlayerBrief(**tree["champion"]) if tree["champion"] else None,
        runner_up=schemas.PlayerBrief(**tree["runner_up"]) if tree["runner_up"] else None,
    )
