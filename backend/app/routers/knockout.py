"""淘汰赛路由：生成淘汰赛、查看淘汰赛树。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_read, require_tournament_write
from ..services import knockout as knockout_service
from ..services import formats as format_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["knockout"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.post("/generate-knockout", response_model=schemas.KnockoutTree)
def generate_knockout(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        handler = format_service.resolve_format_handler(format_service.GROUP_KNOCKOUT)
        tree = handler.advance_participants(conn, tournament_id)
    except format_service.FormatHandlerError as exc:
        raise _http(exc)
    except knockout_service.KnockoutError as exc:
        raise _http(exc)
    return _to_schema(tree)


@router.get("/knockout", response_model=schemas.KnockoutTree)
def get_knockout(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        tree = knockout_service.get_knockout(conn, tournament_id)
    except knockout_service.KnockoutError as exc:
        raise _http(exc)
    return _to_schema(tree)


@router.post("/knockout/undo", response_model=schemas.KnockoutUndoResult)
def undo_knockout(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """撤销淘汰签表（主签 + 名次排位），恢复到可修正小组结果的状态。

    淘汰赛已经开始（有 PLAYING 或已录比分）时返回 409，不静默删除真实结果。
    """
    try:
        result = knockout_service.undo_knockout(conn, tournament_id)
    except knockout_service.KnockoutError as exc:
        raise _http(exc)
    return schemas.KnockoutUndoResult(
        tournament=schemas.TournamentOut(**result["tournament"]),
        deleted_main_matches=result["deleted_main_matches"],
        deleted_placement_matches=result["deleted_placement_matches"],
        deleted_matches=result["deleted_matches"],
    )


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
        placements=tree.get("placements", []),
        placement_matches=tree.get("placement_matches", []),
        champion_path_match_ids=tree.get("champion_path_match_ids", []),
    )
