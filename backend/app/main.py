"""FastAPI 入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routers import groups, players, tournaments


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="乒乓球赛事编排与赛务管理系统 Demo", version="0.1.0", lifespan=lifespan)

# 本地开发：允许 Vite dev server（5173）跨域直连；生产无需考虑（Demo 单机）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tournaments.router)
app.include_router(players.router)
app.include_router(groups.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
