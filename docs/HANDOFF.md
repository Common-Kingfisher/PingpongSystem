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
4. [团体赛领域基础与边界](TEAM_DOMAIN.md)：A3 的 TEAM 数据模型、赛制规格、接口清单与"刻意没做"的部分。
5. `PingpongSystem_交接与开发路线.docx`：面向队友的综合阅读版；精确字段和命令以本目录 Markdown、Pydantic 与 OpenAPI 为准。

若文档与代码冲突，以 Pydantic/OpenAPI 和已通过的测试为准，并在同一 PR 修正文档，不能长期保留已知过期说明。

## 已确认的产品范围

- 保留 React + TypeScript + Vite + FastAPI + SQLite，不搬回 Next.js 原型。
- 单打和双打；双打按运动员积分相近进行随机配对，不等于“强弱搭配使各队实力均衡”。
- 比赛第一次上台记录开赛时间，第一次完赛记录结束时间；赛后改分不覆盖这两个事实时间。
- 比分修改必须填写操作人与修改理由，系统保存修改前后完整快照和不可覆盖的操作历史。
- 默认三局两胜、每局 11 分；创建赛事时可在三局两胜 / 五局三胜 / 七局四胜与每局目标分之间选择；常规只录大比分，输入初值为 0。
- 种子按赛事隔离：可在选手页手工排序，也可「按积分生成种子」（单打，积分降序、同分按选手编号）；选手种子与 Entry 种子在每次修改后同步，分组与签表按同一份种子执行。双打种子规则尚未冻结，不套用该规则。
- 比赛时间（A2）：`matches.called_at` = 最近一次安排上球台的时间；`started_at` = 当前有效进行中比赛的开始时间（下球台后置空，重新安排时重写）；`finished_at` = 当前有效比赛产生结果的时间（改分不改动）。三者统一为 UTC SQLite 时间戳 `YYYY-MM-DD HH:MM:SS`，只由 `repository.mark_match_playing / mark_match_waiting / mark_match_finished` 写入；系统轮空不写时间（派生结果）；未排台直接录分只写 `finished_at`，不伪造开始时间。
- 真实耗时与典型耗时（A2）：只有"有开始与结束时间 + 结果类型 NORMAL"的比赛进入耗时样本；系统轮空、未排台直接录分、弃权/未到/取消资格都不计入。赛事典型耗时取中位数，样本不足 3 场时使用按赛制定义的冷启动估算值（技术估算参数，未来可配置）。
- 预计上场时间（A2，`GET /api/tournaments/{id}/schedule-estimates`）：只读模拟，复用自动排台同一套规则（硬约束 → 组台亲和 → 组间进度公平 → 连续上场软惩罚 → 稳定顺序），进行中的比赛按"最大(下限, 典型时长 − 已进行)"推进；签位未定的后续轮次与超出模拟范围的比赛返回 null。
- 团体赛（A3）当前范围：这是**领域地基，不是可用的团体赛功能**，详见 [团体赛领域基础与边界](TEAM_DOMAIN.md)。
  - `EventType` 增加 `TEAM`；旧库启动时自动迁移 `tournaments.event_type` 的 CHECK（重建该表，数据与子表外键保留）。
  - 队伍即参赛实体（`entries.entry_type='TEAM'`），队员即 `entry_members`；**不新建 `teams` / `team_members` 表**。队伍人数只有下限"至少 1 人"，具体人数规则属于赛制（未冻结）。
  - 新增 `team_ties`（一场"A 队 vs B 队"对抗，含赛制快照与预留时间字段）与 `team_rubbers`（盘骨架：单打/双打 + 每边所需出场位置代号）。
  - 赛制（`domain/team_formats.py`）：`TeamFormatSpec` + 校验 + 快照 + 骨架构建；**生产注册表为空**，任何未登记的赛制建盘都返回 422，系统不臆造"经典赛制"。测试用赛制仅存在于测试内。
  - **一盘不是一场 Match**：A3 不创建任何 `matches` 行，`team_rubbers.match_id` 恒为 NULL（原因：`entry_members` 对 player 全局唯一，且 `_match_member_ids()` 会把整队成员标记为占用）。盘 ↔ 比赛的映射、球台占用与兼项校验留给 A4。
  - 未实现：队伍名单界面、赛制冻结、对阵编排、盘的比分与状态机、团体赛排程/ETA、团体排名与晋级、队伍种子、Demo 模拟（对 TEAM 明确 409）。
  - 阶段门禁现状：TEAM 赛事目前没有任何接口能把 `stage` 从 `REGISTRATION` 推进（生成小组赛/淘汰赛对 TEAM 直接 409），因此对抗创建不挂 stage 门禁；队伍编辑仍锁定在 `REGISTRATION`。
- 淘汰赛交叉对阵的冻结范围（A1 复审确认）：
  - 正式冻结：2 组 × 每组前 2（A1-B2、B1-A2）；4 组 × 每组前 2（A1-D2、C1-B2、B1-C2、D1-A2）；偶数组 × 每组前 2 的"首尾交叉"原则（第 i 组第 1 名 ⇄ 倒数第 i 组第 2 名），同组两人与 1/2 号种子分处不同半区。
  - 未正式冻结：需要轮空时的具体轮空落位（例如 6 组 = 12 人进入 16 签）、3/5/7 等奇数组、每组出线人数 != 2 或各组出线人数不一致。
  - 上述未冻结部分当前保留一套确定性的兼容实现（deterministic compatibility implementation），只保证流程可跑完，**不得描述为正式或国际赛制**；以后按真实赛事规程确认。所有这些都属本项目自有规则，不宣称等同于官方/国际赛制。
- 淘汰签表可在尚未开始时撤销（`POST /api/tournaments/{id}/knockout/undo`）：删除主签与名次排位并回到 `GROUP_STAGE`，修正小组比分后重新生成；已开赛（有进行中比赛或已录结果）返回 409，不静默删除真实结果。
- 赛事数据可结构化导出（`GET /api/tournaments/{id}/export`，只读）：用于归档、交付组委会以及删除赛事前的人工备份。
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
| 报名与导入 | 在线报名、增删改选手、积分/单位、种子；CSV/XLSX 预览后确认；预览全部行。导入是正式能力，LIVE 与 DEMO 赛事都可用；只有「生成演示选手」等 Demo 功能限 DEMO | `RegisterPage.tsx`、`PlayersPage.tsx`；`services/import_players.py` |
| Entry 与双打 | 单打 1 人、双打 2 人；近积分候选随机配对；未配齐不能确认名单 | `services/entries.py`、`routers/entries.py` |
| 团体赛（A3 领域基础） | 队伍 = `entry_type='TEAM'` 的 Entry；队伍增删改查与队员唯一归属校验；`team_ties` / `team_rubbers` 对抗与盘骨架；赛制规格校验与快照（生产注册表为空）；**无界面、无编排、无比分、不进排程** | `services/teams.py`、`services/team_ties.py`、`domain/team_formats.py`、`routers/teams.py`、`routers/team_ties.py` |
| 分组 | 种子分散、人数均衡、同单位软回避；解除分组；配置各组出线数 | `services/groups.py`、`routers/groups.py` |
| 录分与排名 | 大比分默认 0；小组小分补录；改分强制操作人/理由并保存前后快照；读取结果重算排名、提示出线歧义 | `ScoreSheet.tsx`、`RankingsPage.tsx`；`services/scores.py`、`domain/ranking.py` |
| 现场控制台 | 真实 API 球台卡、批量/手动排台、下台、比分/弃权；待赛横向换行；已结束场次改分。自动排台优先级＝硬约束 → 组台亲和 → 组间进度公平 → 连续上场惩罚 → 稳定顺序（服务端给出每台建议，前端只展示），更完整的 V1 设计见 `docs/SCHEDULING_V1_DESIGN.md` | `ConsolePage.tsx`、`LiveTableCard.tsx`、`services/scheduling.py` |
| 人工晋级裁定 | 只处理晋级线并列，记录选择、理由、主裁判和时间；相关数据变化后自动失效 | `services/qualification_decisions.py`、`qualification_decisions.py` |
| 淘汰赛与结果 | 主签胜者晋级、轮空、季军或并列季军、4/8/16 人递归完整排位、最终名次；淘汰赛尚未开始时可用「撤销签表」（`POST /api/tournaments/{id}/knockout/undo`）删除主签与排位并回到 `GROUP_STAGE`，修正小组比分后重新生成，已开赛返回 409 | `KnockoutPage.tsx`；`services/knockout.py` |
| 数据导出与删除保护 | `GET /api/tournaments/{id}/export` 导出结构化赛事数据（`schema_version` + 落库数据 + 排名/冠军/名次推导 + 小分 + 人工裁定快照 + 比分写入审计），只读；删除正式赛事须输入完整赛事名，建议删除前先导出备份 | `services/tournament_export.py`、`routers/tournaments.py` |
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
- `frontend/src/api.ts`：目前仍为手写 TypeScript 类型和请求封装，尚无自动生成的 `schema.d.ts`。

| 字段/实体 | 正确理解 | 接手注意 |
|---|---|---|
| Player | 自然人，含 `rating_points`、`college` | 运动员积分不是赛事排名积分 |
| Entry + entry_members | 一次参赛单位及成员 | 比赛业务应逐步统一使用 Entry ID |
| Match.entry_a_id / entry_b_id | 对阵双方 Entry | 不要与 Player ID 混用 |
| player_a_score / player_b_score | 保留旧名称的大比分，即胜局数 | 2:0 表示赢两局，不是单局得分 |
| MatchGame | `game_no`、双方单局得分、胜者 | 缺小分不等于实际得 0 分 |
| started_at / finished_at | 首次上台与首次完赛的事实时间 | 释放重排、改分和补录小分均不覆盖 |
| score_audits | RECORD/REVISE 前后快照、操作者、原因、时间、请求标识 | 历史只追加不覆盖；旧比分可能没有历史审计 |
| winner_entry_id / winner_id | 新旧兼容字段 | 淘汰树 `player_a.id` 与排名 `player_id` 可能实际承载 Entry ID；见 service 映射 |
| result_type | NORMAL、FORFEIT、WALKOVER、NO_SHOW、DISQUALIFIED | 没有完整 CANCELLED 流程 |
| qualify_count | 组级覆盖值；否则用赛事 `qualify_per_group` | 能保存不代表签表支持所有组合 |
| qualification_decisions | 人工补足晋级线名额的审计记录 | 不改写比赛结果和算法 rank；只使用 active 且排名快照匹配的记录 |
| bronze_mode | BRONZE_MATCH / JOINT_BRONZE | 决定 3、4 名是否真的再打一场 |
| placement_mode | OFF / COMPLETE / TIERED | COMPLETE 支持最多 16 人无轮空标准签；TIERED 仍为预留枚举 |
| team_ties / team_rubbers | 团体赛（A3）新增：一场对抗 + 对抗中的盘骨架 | `match_id` 恒为 NULL（A3 不创建 Match）；盘只记录"每边需要几个出场位置"，不是选手 id；生产赛制注册表为空 |

当前赛事状态：REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED。比赛状态：WAITING → PLAYING → FINISHED；下台回 WAITING。尚无独立 Event/Stage 表和通用 MatchSlot 依赖解析器。当前 `EventType` 有 SINGLES / DOUBLES / TEAM 三个取值；TEAM 赛事**不会**进入这条 stage 链路（生成小组赛/淘汰赛对它直接 409），团体赛的阶段推进要与 A4 的团体赛排程一起设计。

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

创建单打赛事：4 小组、每组前 2、4 台、季军赛、完整排位。导入 16 人示例 → 确认名单 → 分组/生成比赛 → 排台 → 按赛事配置录入大比分（默认三局两胜时为 2:0 / 2:1）→ 查看排名 → 小组全部完成且出线明确后生成淘汰赛 → 打完八强 → 查看 5–8 排位 → 打完半决赛后查看季军赛 → 完成全部主签和排位 → 查看冠军之路、打印秩序册。若要验收 16 人淘汰主签，需产生 16 个晋级 Entry，并完成 1–16 名所有排位场次。

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
| A3 团体赛领域基础 | 后端 401 项测试通过（基线 331 + 新增 70）；`pnpm exec tsc --noEmit` 与 `pnpm build` 通过；OpenAPI 快照与 `app.openapi()` 一致；旧库迁移后 `PRAGMA foreign_key_check` 为空；本轮未做浏览器端团体赛操作验证（界面未实现） |
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
