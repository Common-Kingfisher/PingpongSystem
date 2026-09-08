# 乒乓球赛事编排与赛务管理系统 Demo

单机可运行的乒乓球比赛编排 Field Demo v0.2：从报名校验、单打/双打组队、抽签分组、现场排台、大比分录入、自动排名、淘汰与名次排位，到冠军之路和可打印秩序册的完整闭环。

正式主裁判赛程调度的下一阶段方案见 [`docs/SCHEDULING_V1_DESIGN.md`](docs/SCHEDULING_V1_DESIGN.md)。当前自动排台是演示级贪心调度，不包含最短休息时间和预览确认。

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
    components/       # 抽签动画、比赛大比分/小组小比分、淘汰签表
    pages/            # 现场控制、排名、大屏、冠军之路、秩序册等页面
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

## V0.2 演示范围

| 任务 | 状态 |
|---|---|
| 单打 / 双打统一 Entry，按相近积分随机配对 | ✅ |
| 名单确认、分组抽签过场动画 | ✅ |
| Excel / CSV 预览、校验、确认导入 | ✅ |
| 三局两胜、11 分；先录大比分，小组逐局小比分可随时补录 | ✅ |
| 正常胜 2 / 正常负 1 / 弃权 0 | ✅ |
| 各小组独立设置出线人数 | ✅ |
| 单淘汰、季军赛或并列季军 | ✅ |
| 8 人首轮负者独立争夺第 5–8 名 | ✅ |
| WTT 直播感冠军之路、打印秩序册 | ✅ |
| 双败 / 总决赛重置 | 不在本版范围 |

## 快速开始

```bash
# 后端
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
pnpm install && pnpm dev
```

打开 <http://localhost:5173>，或用种子脚本一键准备演示数据：

```bash
cd backend
.\.venv\Scripts\python.exe seed_demo.py        # 24 人 / 6 台 / 4 组×6 / 晋级 2
```

测试：`cd backend && python -m pytest -q`。前端检查：`cd frontend && pnpm run build`。

## 给队友引用 API 字段

FastAPI/Pydantic 是字段定义唯一来源。仓库内已生成 [docs/openapi-v0.2.json](docs/openapi-v0.2.json)，队友可直接用 OpenAPI 工具导入；如需生成 TypeScript 声明：

```bash
npx openapi-typescript ../docs/openapi-v0.2.json -o src/api/generated/schema.d.ts
```

字段改动后在 `backend` 目录运行 `python export_openapi.py` 即可刷新契约文件。

手写的前端消费类型集中在 `frontend/src/api.ts`，不要在页面里重复声明接口字段。后端 Schema 变化后应重新导出 OpenAPI，并先通过 TypeScript 编译再合并。

详细操作步骤、已知限制与不支持功能见 [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md)。
