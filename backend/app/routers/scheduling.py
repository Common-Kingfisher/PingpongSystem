"""调度路由：指定球台上赛 / 批量自动调度 / 下球台 / 控制台数据。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import eta as eta_service
from ..services import scheduling as scheduling_service

router = APIRouter(tags=["scheduling"])


def _http(exc: scheduling_service.SchedulingError) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.post("/api/matches/{match_id}/assign-table", response_model=schemas.MatchOut)
def assign_table(
    match_id: int, payload: schemas.AssignTableRequest, conn: Connection = Depends(get_db)
):
    try:
        match = scheduling_service.assign_table(conn, match_id, payload.table_id)
    except scheduling_service.SchedulingError as exc:
        raise _http(exc)
    return schemas.MatchOut(**repo.decorate_match(conn, match))


@router.post("/api/matches/{match_id}/release", response_model=schemas.MatchOut)
def release_match(match_id: int, conn: Connection = Depends(get_db)):
    try:
        match = scheduling_service.release_match(conn, match_id)
    except scheduling_service.SchedulingError as exc:
        raise _http(exc)
    return schemas.MatchOut(**repo.decorate_match(conn, match))


@router.post(
    "/api/tournaments/{tournament_id}/schedule-next",
    response_model=schemas.ScheduleNextResult,
)
def schedule_next(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        assignments = scheduling_service.schedule_next(conn, tournament_id)
    except scheduling_service.SchedulingError as exc:
        raise _http(exc)
    return schemas.ScheduleNextResult(
        assigned=len(assignments),
        assignments=[{"match_id": m, "table_id": t} for m, t in assignments],
    )


@router.get("/api/tournaments/{tournament_id}/dashboard", response_model=schemas.Dashboard)
def dashboard(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        data = scheduling_service.get_dashboard(conn, tournament_id)
    except scheduling_service.SchedulingError as exc:
        raise _http(exc)
    return schemas.Dashboard(
        tournament=schemas.TournamentOut(**data["tournament"]),
        stats=schemas.DashboardStats(**data["stats"]),
        tables=[
            schemas.TableWithMatch(
                id=t["id"],
                name=t["name"],
                status=t["status"],
                match=schemas.MatchOut(**t["match"]) if t["match"] else None,
                recommended_match_id=t.get("recommended_match_id"),
            )
            for t in data["tables"]
        ],
        next_playable=[schemas.MatchOut(**m) for m in data["next_playable"]],
    )


@router.get(
    "/api/tournaments/{tournament_id}/schedule-estimates",
    response_model=schemas.ScheduleEstimates,
)
def schedule_estimates(tournament_id: int, conn: Connection = Depends(get_db)):
    """预计上场时间（只读模拟）：与自动排台同一套规则，不修改任何业务数据。

    签位尚未确定或超出模拟范围时返回 null，不返回假精确时间。
    """
    try:
        data = eta_service.estimate_schedule(conn, tournament_id)
    except eta_service.ScheduleEstimateError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return schemas.ScheduleEstimates(
        tournament_id=data["tournament_id"],
        generated_at=data["generated_at"],
        estimated_match_duration_seconds=data["estimated_match_duration_seconds"],
        estimate_basis=data["estimate_basis"],
        sample_count=data["sample_count"],
        initial_playing_matches=data["initial_playing_matches"],
        simulated_batches=data["simulated_batches"],
        truncated=data["truncated"],
        matches=[schemas.ScheduleEstimateMatch(**row) for row in data["matches"]],
    )
