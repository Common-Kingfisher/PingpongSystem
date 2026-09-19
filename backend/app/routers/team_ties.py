"""团体对抗（TeamTie）路由：A3 的骨架接口 + A4.1 的 Runtime 接口 + A6.1 的小组循环生成。

- 读取：`GET /team-ties/{tie_id}` 直接返回统一运行态 `TeamTieRuntimeOut`（不另造 runtime 路径）。
- 生成：`POST /team-ties/generate-group-ties` 按小组单循环批量生成小组对抗（全成或全不成）。
- 阵容：`GET .../rubbers/{rubber_id}/lineup-options`、`PUT .../rubbers/{rubber_id}/lineup`
- 生命周期：`POST .../rubbers/{rubber_id}/start`、`POST .../rubbers/{rubber_id}/score`
- 所有写接口都返回最新的完整 `TeamTieRuntimeOut`，前端整体替换即可，无需二次拉取。

比分、状态机与对阵编排仍不在本路由里"重新发明"：实现全部在
services/team_runtime.py 与 services/team_ties.py。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import team_runtime as runtime_service
from ..services import team_ties as tie_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/team-ties", tags=["team-ties"])

# 复用 team_ties 的前置校验（赛事/项目/对抗），因此这里同时包含两类业务错误。
ServiceErrors = (tie_service.TeamTieError, runtime_service.TeamRuntimeError)


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("", response_model=list[schemas.TeamTieOut])
def list_team_ties(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        return tie_service.list_team_ties(conn, tournament_id)
    except ServiceErrors as exc:
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
    except ServiceErrors as exc:
        raise _http(exc)


@router.post("/generate-group-ties", response_model=schemas.GenerateTeamGroupTiesResult)
def generate_group_ties(tournament_id: int, conn: Connection = Depends(get_db)):
    """按小组单循环生成该 TEAM 赛事的全部小组对抗（A6.1）。

    - 使用**子路径**而不是新的 `/team-group-ties` 命名空间：与同一 router 里的
      `.../team-ties/{tie_id}/rubber-skeleton` 一样，动作挂在资源下面，命名空间保持一处。
    - 路由只做参数解析、调 service、错误映射；编排与全部业务校验在
      `services/team_ties.py::generate_group_ties()`（一个写事务，全成或全不成）。
    - 返回 200 + `{"ties_generated", "per_group"}`（不返回对抗明细：需要明细请调
      `GET /team-ties`；不返回赛事对象：本操作**不推进赛事阶段**）。
    """
    try:
        return tie_service.generate_group_ties(conn, tournament_id)
    except ServiceErrors as exc:
        raise _http(exc)


@router.get("/{tie_id}", response_model=schemas.TeamTieRuntimeOut)
def get_team_tie(tournament_id: int, tie_id: int, conn: Connection = Depends(get_db)):
    try:
        return runtime_service.runtime_view(conn, tournament_id, tie_id)
    except ServiceErrors as exc:
        raise _http(exc)


@router.post("/{tie_id}/rubber-skeleton", response_model=schemas.TeamTieRuntimeOut)
def build_rubber_skeleton(
    tournament_id: int,
    tie_id: int,
    payload: schemas.RubberSkeletonRequest,
    conn: Connection = Depends(get_db),
):
    try:
        tie_service.build_rubber_skeleton(
            conn, tournament_id, tie_id, payload.format_code, payload.replace
        )
        return runtime_service.runtime_view(conn, tournament_id, tie_id)
    except ServiceErrors as exc:
        raise _http(exc)


@router.get(
    "/{tie_id}/rubbers/{rubber_id}/lineup-options",
    response_model=schemas.TeamLineupOptionsOut,
)
def get_lineup_options(
    tournament_id: int, tie_id: int, rubber_id: int, conn: Connection = Depends(get_db)
):
    try:
        return runtime_service.lineup_options(conn, tournament_id, tie_id, rubber_id)
    except ServiceErrors as exc:
        raise _http(exc)


@router.put("/{tie_id}/rubbers/{rubber_id}/lineup", response_model=schemas.TeamTieRuntimeOut)
def set_lineup(
    tournament_id: int,
    tie_id: int,
    rubber_id: int,
    payload: schemas.TeamLineupRequest,
    conn: Connection = Depends(get_db),
):
    try:
        return runtime_service.set_lineup(
            conn,
            tournament_id,
            tie_id,
            rubber_id,
            payload.home_player_ids,
            payload.away_player_ids,
        )
    except ServiceErrors as exc:
        raise _http(exc)


@router.post("/{tie_id}/rubbers/{rubber_id}/start", response_model=schemas.TeamTieRuntimeOut)
def start_rubber(
    tournament_id: int, tie_id: int, rubber_id: int, conn: Connection = Depends(get_db)
):
    try:
        return runtime_service.start_rubber(conn, tournament_id, tie_id, rubber_id)
    except ServiceErrors as exc:
        raise _http(exc)


@router.post("/{tie_id}/rubbers/{rubber_id}/score", response_model=schemas.TeamTieRuntimeOut)
def record_rubber_score(
    tournament_id: int,
    tie_id: int,
    rubber_id: int,
    payload: schemas.TeamRubberScoreRequest,
    conn: Connection = Depends(get_db),
):
    try:
        return runtime_service.record_rubber_score(
            conn,
            tournament_id,
            tie_id,
            rubber_id,
            payload.home_score,
            payload.away_score,
        )
    except ServiceErrors as exc:
        raise _http(exc)
