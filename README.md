# 乒乓球赛事编排与赛务管理系统 Demo

单机可运行的乒乓球比赛编排 Field Demo v0.2：从报名校验、单打/双打组队、抽签分组、现场排台、大比分录入、自动排名、淘汰与名次排位，到冠军之路和可打印秩序册的完整闭环。赛事分为“正式”和“演示”模式；正式赛事由后端禁止模拟数据写入。

正式主裁判赛程调度的下一阶段方案见 [`docs/SCHEDULING_V1_DESIGN.md`](docs/SCHEDULING_V1_DESIGN.md)。当前自动排台按 硬约束 → 组台亲和 → 组间进度公平 → 连续上场软惩罚 → 稳定确定性排序 选择比赛，并优先避免刚完成比赛的运动员立即再次上场；该规则只是软性排序，在没有其它可执行比赛时仍允许继续安排。当前仍没有分钟级最短休息时间保证，也没有调度预览/确认流程。

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
| 团体赛（TEAM）领域基础：队伍即 Entry、对抗与盘骨架、赛制规格（生产注册表为空） | ⚙️ 仅后端接口，无界面/编排/比分；见 [团体赛领域基础与边界](docs/TEAM_DOMAIN.md) |
| 名单确认、分组抽签过场动画 | ✅ |
| Excel / CSV 预览、校验、确认导入 | ✅ |
| 三局两胜、11 分；先录大比分，小组逐局小比分可随时补录 | ✅ |
| 正常胜 2 / 正常负 1 / 弃权 0 | ✅ |
| 各小组独立设置出线人数 | ✅ |
| 晋级线极端同分时由主裁判人工裁定并留痕 | ✅ |
| 单淘汰、季军赛或并列季军 | ✅ |
| 4 / 8 / 16 人标准签递归排出完整名次 | ✅ |
| WTT 直播感冠军之路、打印秩序册 | ✅ |
| 正式/演示赛事隔离、正式赛事防误删 | ✅ |
| 比分请求防重复提交 | ✅ |
| 双败 / 总决赛重置 | 不在本版范围 |

## 正式与演示模式

- 新建赛事默认是 `LIVE`（正式赛事）：隐藏模拟入口，后端拒绝生成演示选手和随机完成小组赛。
- 需要快速展示时显式选择 `DEMO`（演示赛事），页面会持续显示橙色模式标记。
- 删除正式赛事必须先确认风险，再准确输入完整赛事名称；仅隐藏按钮不是安全边界。
- 比分提交带唯一请求编号；网络异常重试不会把同一操作重复执行。

## 人工晋级裁定

人工裁定不会改写原始比赛成绩或算法排名，只补足晋级线上的剩余名额。裁定必须记录理由、操作者和时间；相关比分、小比分或出线人数变化后自动失效。

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
