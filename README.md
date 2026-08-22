# 乒乓球赛事编排与赛务管理系统 Demo

单机可运行的乒乓球比赛编排 Demo：从创建赛事、自动分组、小组循环赛编排、球台分配、比分录入、排名计算、自动晋级到淘汰赛产生冠军的完整闭环。

## 技术栈

- 前端：React 18 + TypeScript + Vite
- 后端：Python 3.10 + FastAPI
- 数据库：SQLite（stdlib `sqlite3`，无 ORM）
- 接口：REST API（JSON）

## 目录结构

```text
backend/
  app/
    db.py             # SQLite 连接、建表 schema、get_db 依赖
    models.py         # 全部状态 Enum（MatchStatus / TableStatus / TournamentStage / MatchStage）
    schemas.py        # Pydantic 请求/响应模型
    repository.py     # SQL 访问层（repository）
    services/         # 应用服务层（事务编排、业务规则）
    routers/          # REST 路由层（薄）
    main.py           # FastAPI 入口
  tests/              # pytest 单元/接口测试
  requirements.txt
frontend/
  src/
    api.ts            # 后端类型定义 + fetch 封装
    pages/            # 5 个页面（任务 1 为占位）
  package.json
```

分层：`frontend → REST API → services → repository → SQLite`，核心业务算法位于 `app/domain/`（后续任务加入），与 UI 解耦。

## 启动方式

### 后端（默认端口 8000）

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>

数据库默认写入 `backend/data/demo.db`，可通过环境变量 `DEMO_DB_PATH` 覆盖。

### 前端（默认端口 5173）

```bash
cd frontend
pnpm install
pnpm dev
```

打开 <http://localhost:5173>。开发服务器已配置 `/api` 代理到后端 8000。

### 运行测试

```bash
cd backend
python -m pytest -v
```

## 开发进度

| 任务 | 状态 |
|---|---|
| 1. 项目骨架 + 数据模型 | ✅ |
| 2. 选手管理 + 自动分组 | ✅ |
| 3. 小组循环赛生成 | ✅ |
| 4. 比赛状态 + 球台调度 | ✅ |
| 5. 比分录入 + 小组排名 | ✅ |
| 6. 晋级 + 淘汰赛 | ✅ |
| 7. 比赛控制台 UI | ⏳ |
| 8. 全流程验收与修复 | ⏳ |
