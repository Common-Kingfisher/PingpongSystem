# PingpongSystem 开发交接

最近维护：2026-09-09。当前集成分支：`develop/field-demo-v02`；精确基线以该分支最新提交为准。

维护规则：每个功能 PR 必须同步更新相关 Markdown、OpenAPI 快照（接口变化时）和 `CHANGELOG.md`；不再把文档集中留到最后补写。

## 先看结论

当前版本已具有“报名 → 确认名单 → 分组 → 小组比赛 → 排名 → 单淘汰 → 季军/排位 → 冠军展示”的主要链路，是可以继续联调的 Demo 基线，**不是已经通过完整现场验收的 V0.2 发布版**。下一步优先修复规则边界和改分保护，再完善现场调度、秩序册和大规模验证。

正式开发目录为 `pingpong_plantform`。`teammate-draft/pingpong_plantform` 是旧副本；`frontend-demo` 是早期独立视觉原型，不是当前应用入口。交接前，正式目录与 `teammate-draft/pingpong_plantform` 的 95 个源码、配置和文档文件内容一致，依赖、数据库和缓存未参与比较。今后只在正式目录开发，避免双副本漂移。

仓库：[Common-Kingfisher/PingpongSystem](https://github.com/Common-Kingfisher/PingpongSystem)。当前新增 120 人规模验收数据与自动化闭环测试，详见 [120 人规模验收数据](SCALE_VALIDATION_120.md)。

## 阅读顺序

1. 本文：接手、运行、模块和验证情况。
2. [V0.2 对比](V02_COMPARISON.md)：原稿要求、后续确认、当前差距。
3. [开发路线](DEVELOPMENT_ROADMAP.md)：优先级、风险、责任边界和验收门槛。
4. `PingpongSystem_交接与开发路线.docx`：面向队友的综合阅读版；精确字段和命令以本目录 Markdown、Pydantic 与 OpenAPI 为准。

若文档与代码冲突，以 Pydantic/OpenAPI 和已通过的测试为准，并在同一 PR 修正文档，不能长期保留已知过期说明。

## 已确认的产品范围

- 保留 React + TypeScript + Vite + FastAPI + SQLite，不搬回 Next.js 原型。
- 单打和双打；双打按运动员积分相近进行随机配对，不等于“强弱搭配使各队实力均衡”。
- 默认三局两胜、每局 11 分；常规只录大比分，输入初值为 0。
- 小组正常完赛场次可补录/修改小比分，用于同分排名；淘汰赛 UI 仍只录大比分。
- 小组排序已确认前缀：胜场数 → 净胜局 → 赛事积分（胜 2、正常负 1、弃权负 0）。后续同分细则仍须专项确认，不宣称已完整实现 ITTF 官方算法。
- 小组出线数可配置；各组不同人数的组合仍有后端限制，见风险 R03。
- 不做双败。所谓败者组是争夺较低名次的排位赛，不会返回主签争冠军。
- 创建赛事选择季军赛或并列季军；完整排位支持 4 / 8 / 16 人无轮空标准签。非标准人数仍可完成冠军主签，但不会虚构无法由比赛确定的低位名次。
- 名单确认后的过场动画、比赛球台视觉、从下到上的冠军之路继续保留。
- 秩序册先用浏览器打印/保存 PDF，后续接组委会官方模板。

## 当前功能和入口

| 模块 | 现有能力 | 主要代码 |
|---|---|---|
| 赛事首页 | 创建、选择、删除赛事；单/双打、球台、小组、出线数、季军与排位配置 | `frontend/src/pages/HomePage.tsx` |
| 赛前检查 | 面向主裁聚合名单、参赛位、分组、赛程、球台、晋级和规则状态；只读检查，不替主裁自动决策 | `PreflightPage.tsx`；`services/preflight.py` |
| 报名与导入 | 在线报名、增删改选手、积分/单位、种子；CSV/XLSX 预览后确认；预览全部行 | `RegisterPage.tsx`、`PlayersPage.tsx`；`services/import_players.py` |
| Entry 与双打 | 单打 1 人、双打 2 人；近积分候选随机配对；未配齐不能确认名单 | `services/entries.py`、`routers/entries.py` |
| 分组 | 种子分散、人数均衡、同单位软回避；解除分组；配置各组出线数 | `services/groups.py`、`routers/groups.py` |
| 现场控制台 | 真实 API 球台卡、批量/手动排台、下台、比分/弃权；待赛横向换行；已结束场次改分。当前自动排台仍是按记录顺序贪心，V1 设计见 `docs/SCHEDULING_V1_DESIGN.md` | `ConsolePage.tsx`、`LiveTableCard.tsx` |
| 录分与排名 | 大比分默认 0；小组小分补录；读取结果重算排名、提示出线歧义 | `ScoreSheet.tsx`、`RankingsPage.tsx`；`services/scores.py`、`domain/ranking.py` |
| 人工晋级裁定 | 只处理晋级线并列，记录选择、理由、主裁判和时间；相关数据变化后自动失效 | `services/qualification_decisions.py`、`qualification_decisions.py` |
| 淘汰赛与结果 | 主签胜者晋级、轮空、季军或并列季军、4/8/16 人递归完整排位、最终名次 | `KnockoutPage.tsx`；`services/knockout.py` |
| 展示与输出 | 大屏、名单过场、冠军路径高亮、秩序册打印 | `BigScreenPage.tsx`、`RosterLaunch.tsx`、`ChampionJourneyPage.tsx`、`OrderBookPage.tsx` |

规模验收数据位于 `docs/demo-data/realistic_players_120.csv` 和 `.xlsx`；24 组×5 人、15 台、每组前 2 的验证命令见 `backend/tests/test_scale_120.py`。

新建赛事默认 `operation_mode=LIVE`；只有显式 `DEMO` 赛事可以调用演示数据接口。正式赛事删除需要完整名称确认。比分写入支持可选 `request_id`，前端默认生成并在网络失败时用同一编号重试一次。

表中前端短文件名均位于 `frontend/src/pages/`，组件位于 `frontend/src/components/`；后端短路径均位于 `backend/app/`。存在页面不代表所有 V0.2 要求都已满足，特别是 Schedule 页面不是完整计划时间引擎。

## 架构与字段契约

请求路径：页面/组件 → `frontend/src/api.ts` → FastAPI router → service/domain → repository → SQLite。

- `backend/app/schemas.py`：请求与响应 Pydantic 定义。
- `backend/app/models.py`：枚举；`backend/app/db.py`：数据库结构及启动时兼容迁移。
- `backend/app/repository.py`：持久化与旧 Player / 新 Entry 的兼容映射。
- `docs/openapi-v0.2.json`：OpenAPI 快照；本轮确认与 `app.openapi()` 相等。
- `frontend/src/api.ts`：手写请求封装；`frontend/src/generated/openapi.d.ts` 为 OpenAPI 生成类型，接口改动时必须同步刷新。

| 字段/实体 | 正确理解 | 接手注意 |
|---|---|---|
| Player | 自然人，含 `rating_points`、`college` | 运动员积分不是赛事排名积分 |
| Entry + entry_members | 一次参赛单位及成员 | 比赛业务应逐步统一使用 Entry ID |
| Match.entry_a_id / entry_b_id | 对阵双方 Entry | 不要与 Player ID 混用 |
| player_a_score / player_b_score | 保留旧名称的大比分，即胜局数 | 2:0 表示赢两局，不是单局得分 |
| MatchGame | `game_no`、双方单局得分、胜者 | 缺小分不等于实际得 0 分 |
| winner_entry_id / winner_id | 新旧兼容字段 | 淘汰树 `player_a.id` 与排名 `player_id` 可能实际承载 Entry ID；见 service 映射 |
| result_type | NORMAL、FORFEIT、WALKOVER、NO_SHOW、DISQUALIFIED | 没有完整 CANCELLED 流程 |
| qualify_count | 组级覆盖值；否则用赛事 `qualify_per_group` | 能保存不代表签表支持所有组合 |
| qualification_decisions | 人工补足晋级线名额的审计记录 | 不改写比赛结果和算法 rank；只使用 active 且排名快照匹配的记录 |
| bronze_mode | BRONZE_MATCH / JOINT_BRONZE | 决定 3、4 名是否真的再打一场 |
| placement_mode | OFF / COMPLETE / TIERED | COMPLETE 支持最多 16 人无轮空标准签；TIERED 仍为预留枚举 |

当前赛事状态：REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED。比赛状态：WAITING → PLAYING → FINISHED；下台回 WAITING。尚无独立 Event/Stage 表和通用 MatchSlot 依赖解析器。

## 队友如何启动

推荐在新文件夹 clone，不要覆盖已有同名目录：

```powershell
git clone https://github.com/Common-Kingfisher/PingpongSystem.git
cd PingpongSystem
python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
pnpm -C frontend install --frozen-lockfile
```

`pingpong_plantform` 是当前机器上的目录名；clone 后的 `PingpongSystem` 就是同一仓库根目录，无需再进入同名子目录。

需要 Python 3.10+、Node.js 和 pnpm。核查机使用 Node 24.13.0、pnpm 11.19.0；这只是本次环境记录，不是长期版本推荐。后端依赖目前使用最低版本范围，没有完全锁定。前端 package 与 FastAPI 应用版本仍标为 `0.1.0`；本报告中的 V0.2 指需求对比目标，不代表已发 V0.2 版本。

开两个终端，均从仓库根目录启动：

```powershell
# 终端一：后端
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

```powershell
# 终端二：前端
pnpm -C frontend dev
```

打开 `http://localhost:5173`；健康检查 `http://127.0.0.1:8000/api/health`；API 文档 `http://127.0.0.1:8000/docs`。环境装齐后也可双击 `start_demo.bat`。

端口占用先确认是不是已经启动了本项目；检查进程身份后再关闭自己的旧终端，不要盲目结束所有 Python/Node 进程。现有启动脚本只检查 `node_modules` 目录存在，不保证其中链接完整；遇到模块缺失先重新执行锁文件安装。

数据库默认 `backend/data/demo.db`，不上传 GitHub。运行服务前先确认路径；升级或清理前停止服务并单独备份。测试使用独立临时库，不能对真实比赛库运行重置/造数脚本。仓库附有虚构的 16 人 CSV/XLSX，路径 `docs/demo-data/`。

## 建议的首次演示

创建单打赛事：4 小组、每组前 2、4 台、季军赛、完整排位。导入 16 人示例 → 确认名单 → 分组/生成比赛 → 排台 → 录 2:0 或 2:1 → 查看排名 → 小组全部完成且出线明确后生成淘汰赛 → 打完八强 → 查看 5–8 排位 → 打完半决赛后查看季军赛 → 完成全部主签和排位 → 查看冠军之路、打印秩序册。若要验收 16 人淘汰主签，需产生 16 个晋级 Entry，并完成 1–16 名所有排位场次。

本次演示先使用各组一致的出线数，不在正式比赛中试验已知改分风险。每组可先让固定顺序的高位选手全胜以得到无歧义排名。循环同分另建测试赛事，不要修改正在使用的演示数据来凑名次。双打建议另建 8 或 16 名运动员的赛事，注意 8 名运动员只有 4 个 Entry。

## 本轮验证记录

| 验证 | 结果与边界 |
|---|---|
| 正式目录后端现有测试 | 157 项通过；使用旧副本中现成的 Python 虚拟环境运行正式目录代码，已核实模块实际加载路径 |
| 前端类型检查与生产构建 | `pnpm run build` 通过（包含 `tsc`，Vite 5.4.11，50 modules） |
| 依赖完整性 | 正式目录原有链接损坏；已按锁文件重装，锁文件和业务代码未改 |
| OpenAPI | 快照与当前应用生成结构一致；自动 TS 类型生成仍缺失 |
| 额外隔离诊断 | 复现非法比分校验不足、不等额出线拒绝、半决赛改分不更新季军参与者、淘汰生成后仍可改小组结果 |
| Git 发布前检查 | 21 个历史提交范围内，未发现已跟踪依赖目录/数据库/私钥文件或常见 Token 特征；这不是完整安全审计 |
| 本轮未执行 | 浏览器完整 E2E、120 人/15 台闭环、并发录分、目标机器安装演练、完整规则符合性认证 |
| Word | 使用系统设计模板，完成结构校验；本机缺 LibreOffice，未完成逐页渲染视觉验收 |

测试命令（配置好自己的后端环境后）：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
pnpm -C frontend run build
```

测试通过不表示所有规则正确：当前测试未覆盖本轮发现的若干反例。具体修复顺序及待确认事项见开发路线。

## 交接协作方式

你负责页面、组件、交互、打印样式与 UI 验收；队友负责赛制、排名、数据迁移、接口和服务层；集成/复核职责须明确指定，可轮流承担，但修改者不能独自宣布核心规则通过。

从本次基线开始使用功能分支、小批 PR。每次字段变更同时更新 Pydantic、OpenAPI、前端消费类型、测试与文档。不要复制整个 `node_modules`、`.venv`、`.pnpm-store` 来交接；GitHub 上传代码不等于网站已部署上线。
