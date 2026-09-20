"""FastAPI 入口。"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import init_db
from .routers import (
    demo,
    entries,
    groups,
    knockout,
    matches,
    players,
    preflight,
    qualification_decisions,
    scheduling,
    scores,
    seeds,
    team_knockout,
    team_qualification,
    team_standings,
    team_ties,
    team_roster,
    teams,
    tournaments,
)

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="乒乓球赛事编排与赛务管理系统 Demo", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """开发期请求日志：method / path / status / duration，便于定位 500。"""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理：未预期异常统一返回 JSON 500（而非纯文本），并记录完整 traceback。

    业务异常（404/409/422）由各 router 显式映射为 HTTPException，
    本处理器只兜住真正未预期的服务器错误，避免前端收到非 JSON 500。
    """
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请查看后端日志"})

# 本地开发：允许 Vite dev server（5173）跨域直连；生产无需考虑（Demo 单机）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tournaments.router)
app.include_router(players.router)
app.include_router(entries.router)
app.include_router(groups.router)
app.include_router(seeds.router)
app.include_router(demo.router)
app.include_router(matches.router)
app.include_router(scheduling.router)
app.include_router(scores.router)
app.include_router(preflight.router)
app.include_router(qualification_decisions.router)
app.include_router(knockout.router)
# 团体赛（A3）：队伍 + 团体对抗/盘骨架
app.include_router(teams.router)
app.include_router(team_roster.router)
app.include_router(team_ties.router)
app.include_router(team_standings.router)
app.include_router(team_qualification.router)
app.include_router(team_knockout.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
