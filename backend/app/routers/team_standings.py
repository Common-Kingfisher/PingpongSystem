"""团体小组排名路由（A6.2）：只读。

- `GET /api/tournaments/{id}/team-groups/standings`：本赛事全部小组的团体排名
  （可按 `group_id` 过滤）；按 `groups.sort_order` 稳定排序。
- `GET /api/tournaments/{id}/team-groups/{group_id}/standings`：单个小组的团体排名。

**为什么是独立前缀 `/team-groups`**：`team-ties` 命名空间下已经有 `{tie_id}` 动态段，
把 `/team-ties/standings` 塞进去会与 `{tie_id}` 冲突（必须靠声明顺序规避，很脆弱）。
而 `/groups/{group_id}/qualification` 这类"小组下的资源"在仓库里已有先例，
所以小组排名挂在 `/team-groups/...` 下最贴合现有风格（路径也**不**与 `/groups`
冲突：`/groups/{id}` 是另一条前缀）。

排名规则与统计口径见 `docs/TEAM_GROUP_RULES_V1.md`；本路由不含任何排名逻辑。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import team_standings as standings_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/team-groups", tags=["team-standings"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("/standings", response_model=list[schemas.TeamGroupStandingsOut])
def list_team_group_standings(
    tournament_id: int,
    group_id: int | None = Query(default=None, description="只看某个小组"),
    conn: Connection = Depends(get_db),
):
    try:
        return standings_service.list_team_group_standings(conn, tournament_id, group_id)
    except standings_service.TeamStandingsError as exc:
        raise _http(exc)


@router.get("/{group_id}/standings", response_model=schemas.TeamGroupStandingsOut)
def get_team_group_standings(
    tournament_id: int, group_id: int, conn: Connection = Depends(get_db)
):
    try:
        return standings_service.get_team_group_standings(conn, tournament_id, group_id)
    except standings_service.TeamStandingsError as exc:
        raise _http(exc)
