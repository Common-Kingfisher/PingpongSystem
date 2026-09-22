"""分组路由：自动分组、清空分组、查看分组。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..dependencies import (
    require_public_tournament_read,
    require_tournament_write,
)
from ..services import groups as groups_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["groups"])


@router.get("/groups", response_model=schemas.GroupingResult)
def get_groups(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_public_tournament_read),
):
    if repo.get_tournament(conn, tournament_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return schemas.GroupingResult(
        groups=groups_service.get_groups_with_players(conn, tournament_id)
    )


@router.post("/auto-group", response_model=schemas.GroupingResult)
def auto_group(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        groups = groups_service.auto_group_tournament(conn, tournament_id)
    except groups_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except groups_service.TournamentStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return schemas.GroupingResult(groups=groups)


@router.post("/ungroup", status_code=204)
def ungroup(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        groups_service.ungroup_tournament(conn, tournament_id)
    except groups_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except groups_service.TournamentStageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.patch("/groups/{group_id}/qualification", response_model=schemas.GroupOut)
def set_group_qualification(
    tournament_id: int,
    group_id: int,
    body: schemas.GroupQualifyUpdate,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    tournament = repo.get_tournament(conn, tournament_id)
    group = repo.get_group(conn, group_id)
    if tournament is None or group is None or group["tournament_id"] != tournament_id:
        raise HTTPException(status_code=404, detail="小组不存在")
    if tournament["stage"] not in ("REGISTRATION", "GROUP_STAGE"):
        raise HTTPException(status_code=409, detail="淘汰赛开始后不能修改出线人数")
    source = repo.list_entries(conn, tournament_id) or repo.list_players(conn, tournament_id)
    member_count = sum(1 for item in source if item.get("group_id") == group_id)
    if body.qualify_count >= member_count and member_count > 1:
        raise HTTPException(status_code=422, detail="出线人数必须少于本组参赛单位数")
    updated = repo.update_group_qualify_count(conn, group_id, body.qualify_count)
    repo.invalidate_qualification_decision(conn, group_id, "小组出线人数已修改")
    conn.commit()
    decorated = groups_service.get_groups_with_players(conn, tournament_id)
    return next(g for g in decorated if g["id"] == updated["id"])
