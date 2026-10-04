# PingpongSystem V0.3 — C 轨 D5 现场运行收口

状态：**C-Day5 CLOSED**（Phase 1–4 完成，等待 review）

基线：`master@9dbcd6b3b82e4685fc79bac2bf08d97975c1c91a`（PR #65 合并后的状态）

工作分支：`feat/v03-c-d5-field-ops-closeout`

| Phase | 内容 | 结论 |
| --- | --- | --- |
| Phase 1 | 赛事 Dashboard / 赛事总览 + 现场状态同步（PR #64） | **DONE**（本轮未重写，回归通过） |
| Phase 2 | Console 现场操作 + 5 秒同步 | **DONE** |
| Phase 3 | 赛程与秩序 + A4 打印 | **DONE** |
| Phase 4 | 16 人 / 6 台现场 E2E + D5 Closeout | **DONE**（管理端现场链）· **PARTIAL**（物理设备覆盖，见第 9 节） |

## 1. D5 总目标

D5 不继续横向堆叠页面，而是把已经存在的比赛能力收口为主裁判可顺序操作、可辨认现场状态、网络异常时不误导的运行系统。

## 2. Phase 1 保持不变

根页面仍然有清晰的两种状态（无有效赛事 → 创建与列表；有效单打/双打赛事 → 真实赛事总览；TEAM → 独立团体入口）。Dashboard 继续使用真实后端 API、Preflight、10 秒 polling、hidden 暂停、visible 立即刷新、stale 保留快照、TEAM 与个人 Match 分离。

本轮**没有重写 Phase 1**：`AdminDashboardPage.tsx` 仅在测试夹具中补了新的 `completion` 字段，页面实现未改。

## 3. Phase 2：Console 现场操作收口

### 3.1 后端权威：阶段完成状态（本轮唯一后端契约变更）

收口前 `ConsolePage` 自己统计"小组赛总场数 / 已结束场数"再配合 `Tournament.stage` 推断阶段是否结束。这是**前端第二套业务事实**，在三种赛制下都会给出错误入口。

问题在于：后端**已经有**唯一权威（`backend/app/services/formats.py` 各 Handler 的 `get_completion_state`，`sync_round_robin_stage` 也在用它），但**没有对外暴露**，generated OpenAPI 里也没有对应字段。按"C 轨先判断后端是否已有等价接口 / 是否只是前端没接线"的规则，这属于**前端确实拿不到的最小事实**，因此做了最小后端改动：

- `schemas.py`：新增 `DashboardCompletion`（`format_code` / `state` / `can_advance` / `completed`），并把它挂到既有 `Dashboard` 响应上；
- `services/scheduling.py`：新增 `resolve_completion_state()`，**只做只读透传**，不复制任何完成判定；
- `routers/scheduling.py`：把该字段带进 `GET /api/tournaments/{id}/dashboard`。

不适用场景显式返回 `NOT_APPLICABLE`（团体赛 / 未设置赛制的历史赛事），处理器拒绝配置时返回 `UNAVAILABLE` —— **绝不猜成"可以推进"**。`docs/openapi-v0.2.json` 与 `frontend/src/generated/openapi.d.ts` 已同步，contract check 通过。

Console 侧的判定逻辑随之下线，全部改为消费后端字段。

### 3.2 5 秒同步与 stale 语义

- 首次进入正常 loading；核心数据失败显示"现场数据加载失败 + 服务端文案 + 重试"，不白屏、不无限 loading；
- 成功后每 `5000ms` 静默刷新现场状态，**不整页 loading、不清空卡片、不重置浏览位置**；
- `document.hidden` 时暂停计时器，恢复可见后立即刷新一次再恢复 5 秒周期；
- 刷新失败保留最近一次成功快照，显示"当前显示可能不是最新状态"与"最近同步：HH:mm:ss"；下一次成功后自动清除；
- 卸载时清理计时器与 visibility listener。

断网期间不出现：比赛列表清空、球台变空、比分变 0、Preflight 伪装 READY。

### 3.3 球台与排台

- 球台**固定按台号排列**（`sortTablesByNumber`），OCCUPIED/FREE 变化不会导致顺序跳动；
- OCCUPIED 显示球台号、对阵双方、比赛阶段 + Match 状态、录分入口、下球台；
- FREE 显示"空闲"与当前合法的比赛安排入口；
- 顶部只保留高频动作（自动安排下一批比赛 / 刷新），实时赛程、打印快照、排名、淘汰赛、Demo 模拟收进"更多"；
- 已结束比赛行内只留"修改大比分"，修改小比分 / 操作记录 / 打印成绩单收进行内"更多"。

### 3.4 后端是调度权威（本轮修掉的前端算法）

收口前 Console 里有两处**前端排台算法**，已删除：

1. `preferredGroupForTable()` —— 前端复刻了后端 `group_table_affinity` 软约束；
2. `nextMatchForTable()` —— 在推荐缺失时前端自行按"本台对应小组 → 任意一场"挑选比赛。

现在：空闲球台只读展示后端 `recommended_match_id` 对应的比赛（标注"后端推荐"）；点"安排比赛"弹出的是**后端 `next_playable` 全量合法候选**，由主裁选择，页面明确写出"比赛优先级由后端调度器决定，本页不重新排序"。前端不再有"谁最应该先打"的算法。

### 3.5 赛制感知与阶段完成

`frontend/src/fieldOps.ts` 把后端 `completion.state` 映射为现场文案（纯展示映射，不做业务判定）：

| 后端 state | Console 表现 |
| --- | --- |
| `GROUP_MATCHES_NOT_GENERATED` / `MATCHES_NOT_GENERATED` | 按 `format_code` 分别提示"小组赛 / 循环赛 / 淘汰签尚未生成"，引导到抽签与编排；单淘汰明确写"不存在小组阶段" |
| `GROUP_STAGE_IN_PROGRESS` / `ROUND_ROBIN_IN_PROGRESS` / `KNOCKOUT_IN_PROGRESS` | 正常进行，无横幅 |
| `QUALIFICATION_UNRESOLVED` / `KNOCKOUT_NOT_READY` | 显示后端阻断原因，引导到排名 |
| `KNOCKOUT_READY` | "小组赛已全部完成" + 进入淘汰赛；隐藏自动排台，空闲球台显示"本阶段已结束" |
| `RANKING_DATA_INSUFFICIENT` / `RANKING_UNRESOLVED` | 循环赛结束但排名未决，引导到排名 |
| `COMPLETED` | 循环赛结束只说"循环赛已全部完成"（**不诱导生成淘汰赛**）；其他赛制说"赛事已全部完成" |
| `NOT_APPLICABLE`（`format_code=null`） | "尚未设置赛制"，不默认为小组淘汰 |

阶段标签统一走 `tournamentStageLabel(stage, format_code)`，不再把所有赛制写死成"小组赛 → 淘汰赛"。

### 3.6 TEAM 硬边界

Console 对 `event_type === 'TEAM'` 直接给出独立团体入口，**不请求普通 Match Dashboard**、不渲染球台与比分、不把 TeamTie 转成 Match。

## 4. Phase 3：赛程与秩序 + A4 打印

### 4.1 实时赛程 vs 官方秩序册

两个概念在本轮被明确分开：

- **实时赛程**：来自运行数据库，表示系统当前真实比赛计划与状态 —— `/schedule` 默认展示；
- **官方秩序册**：赛前发布 / 文件 / 快照 / 打印材料，**不是**运行数据库事实源。

后端当前**没有任何"官方秩序册文件"业务事实**（`order-book-snapshot` 是实时聚合快照）。因此 `/orderbook` 明确显示：

> 官方秩序册：暂未关联官方秩序册

并说明本页是实时赛程快照、**不是**赛事方发布的正式秩序册。既不伪造"已生成"，也不自动生成文件再声称那是赛事方发布版本，更不让运行逻辑反向读取打印文件。

### 4.2 Schedule 页面

管理端 `/schedule` 默认展示实时赛程，包含轮次/阶段、对阵、球台、状态、比分、预计上场时间。淘汰赛轮次名**直接取后端签表 `label`**（"8强赛/半决赛/决赛"），不由前端按 `round` 数字自行命名。预计上场时间取 `schedule-estimates`，无法估算时显示后端原因。

Public 端 `/public/t/:tid/schedule` 复用同一组件但不传 `variant`，因此**继续拿到既有的 public"选手赛程"行为**，`PublicRoutes.tsx` 未被修改。

### 4.3 A4 打印

`@page { size: A4; margin: 12mm }` + `@media print`：

- 隐藏管理端侧边栏、顶栏、工具栏、`.btn`、`.no-print` 与模态层；
- 黑白打印：去掉深色底、渐变与阴影，统一黑字白底；
- 表格取消屏幕最小宽度、按固定列宽重排，A4 下不出现一列被截断；
- `tr { break-inside: avoid }` 避免把一场比赛拆到两页；`thead` 作为 `table-header-group` 跨页重复。

打印内容带快照语义，屏幕与纸张上都可见：

```text
赛事名称：…
生成时间：2026/10/4 16:37:33
当前阶段：淘汰赛阶段
数据状态：实时系统快照（24 / 31 场已结束）· 非官方秩序册
```

不引入任何第三方打印库（React + CSS + 浏览器打印）。

## 5. Phase 4：16 人 / 6 台现场 E2E

### 5.1 标准验收赛事

`16 人 / 4 组 / 每组 4 人 / 每组前 2 / 6 张球台 / GROUP_KNOCKOUT`，由 `c_day5_admin_fixture.py` 全程走真实 HTTP 契约创建（bootstrap → EVENT_ADMIN → bearer → 建赛事 → 录名单 → 确认名单 → 生成分组 → 生成 24 场小组赛），**不预先排台**，排台留给浏览器里的真实点击。

### 5.2 复用的 D6D harness

| harness | 本轮用法 | 结果 |
| --- | --- | --- |
| `day6d_field_simulation.mjs` | E5 全链跨轨回归（Public / Mobile Score / BigScreen / 并发 / 断网恢复） | **113/113 PASS** |
| `day6d_public_viewport_check.mjs` | 360/375/390/430 Public 与 Mobile Score 布局回归 | **168/168 PASS** |
| `day6d_restart_check.py` | 服务重启前后现场事实比对 | **15/15 PASS** |
| `day6d_field_fixture.py` / `day6d_longname_fixture.py` | 复用其数据前置，未新造第二套 | — |

**没有复制第二套现场 harness。**

### 5.3 新增的 C 轨专项验收

| 脚本 / 文件 | 覆盖 | 结果 |
| --- | --- | --- |
| `c_day5_admin_field_check.mjs` | 1280×900 / 1440×900 打开 `/`、`/console`、`/schedule`、`/orderbook`；无白屏、无未处理 console error、无够不到的横向溢出；Console 5 秒轮询真实发生、hidden 暂停、断网 stale + 保留快照、恢复后自动清除；排台后现场状态更新；A4 打印隐藏导航与控件且快照语义齐全；失效 tid 不无限 loading | **75/75 PASS** |
| `c_day5_field_chain_check.mjs`（ranked） | 排台 → 录分 → Console 无需手动刷新即反映结果 → 24/24 → 阶段收口（无排台、有进入淘汰赛、空闲球台"本阶段已结束"）→ 生成淘汰签 → 淘汰赛**恢复**排台能力（不被小组赛逻辑锁死）→ Schedule 31 场 + 后端轮次名 → 秩序册语义 | **23/23 PASS** |
| `c_day5_field_chain_check.mjs`（blocked） | 只录大比分路径的**不变量**：界面"能不能推进/能不能排台"与后端 `completion` 完全一致，后端拒绝时前端不得给出淘汰赛入口 | **11/11 PASS** |
| `backend/tests/test_c_d5_dashboard_completion.py` | 后端 `completion` 契约、小组淘汰三场景、循环赛永不 `can_advance`、单淘汰无小组阶段、团体赛/未设置赛制 `NOT_APPLICABLE`、并列阻断、只读不变量 | **16 passed** |
| `frontend/src/__tests__/AdminD5ConsoleFieldOps.test.tsx` | 5 秒 polling / hidden 暂停 / visible 立即刷新 / stale 保留与恢复 / 球台稳定排序 / 推荐只读 / 候选来自后端 / 阶段收口 / ROUND_ROBIN 无淘汰入口 / SINGLE_ELIMINATION 无小组文案 / TEAM 隔离 / 空态与错误态 / 长文本 | **25 passed** |
| `frontend/src/__tests__/AdminD5SchedulePrint.test.tsx` | 实时赛程展示、后端轮次名、预计时间存在与缺失、空态、错误态、失效 tid、打印快照语义、Public 行为不回归、秩序册"暂未关联"、打印工具栏 `no-print` | **15 passed** |

### 5.4 现场链实际走通的路径（ranked 模式真实输出）

```text
进度 0/24 空闲台=6 → 点击自动排台 → 6 张球台全部进行中
录分 6 场 200 → Console 无需手动刷新：已完成 0 → 6/24（最近同步 16:37:25）
…推进… → 24/24
后端 completion = KNOCKOUT_READY / can_advance=true
过渡窗口：无"自动安排下一批比赛"；横幅"小组赛已全部完成"；入口"进入淘汰赛"
        空闲球台 6/6 显示"本阶段已结束"
生成淘汰签 HTTP 200 → 回到 Console：自动排台恢复（等待 7 场），横幅消失
淘汰赛自动排台 → 4 张球台进行中
Schedule：31 行（24 小组 + 7 淘汰），轮次名 [8强赛, 半决赛, 决赛]，已结束 24
OrderBook：31 行完整赛程 + 仍明确"非官方秩序册"
```

### 5.5 现场观察到的真实阻断路径

第一轮现场运行时，主裁只录大比分（不带逐局小分）造成了**真实的组内三循环并列**：后端报告 `QUALIFICATION_UNRESOLVED`，Console 原样显示"小组出线存在无法判定的并列 / 前往排名"，**没有**给出淘汰赛入口，后端 `generate-knockout` 也确实返回 409（"A组 晋级判定数据不足，请先补录相关场次逐局小分"）。

这是**正确行为**而非缺陷：前端没有因为"24 场都打完了"就自行开放淘汰赛。该路径已固化为 `test_c_d5_dashboard_completion.py::test_unresolved_qualification_blocks_advance_and_is_reported`（确定性构造 0>1>2>0 三循环），以及 harness 的 blocked 模式不变量断言。

## 6. 缺陷

### P0（本轮发现并修复）

无。本轮未发现数据丢失、越权、错误比分、错误比赛、错误晋级或球台重复占用。

### P1（本轮发现并修复）

1. **Console 用前端统计推断阶段完成，导致错误操作入口**
   - 复现：小组赛打完、淘汰签未生成时，旧逻辑靠 `finished/waiting/playing` 计数判断；ROUND_ROBIN 打完会显示"晋级名单已确定，可以进入淘汰赛"并给出淘汰赛按钮（循环赛根本没有淘汰阶段）；`format_code=null` 会被当成小组淘汰。
   - 根因：前端建立了第二套业务事实。
   - 修复：后端透传赛制 Handler 的 `completion`，前端只做文案映射（第 3.1 / 3.5 节）。
2. **Console 无自动同步**：只有手动"刷新"，现场状态不会自己更新。
   - 修复：5 秒静默轮询 + hidden 暂停 + visible 立即刷新 + stale 快照（第 3.2 节）。
3. **Console 存在前端排台算法**：`preferredGroupForTable` 复刻后端组台亲和，`nextMatchForTable` 在前端挑"该台该打哪场"。
   - 修复：删除，改为展示后端 `recommended_match_id`，并从后端 `next_playable` 全量候选中由主裁选择（第 3.4 节）。
4. **球台顺序不稳定**：按后端返回顺序渲染，未显式按台号排序。
   - 修复：`sortTablesByNumber`。
5. **OrderBookPage 失效 tid 无限 loading**：`tid` 为 null 时 `load()` 直接 return，页面永远停在"正在整理赛事资料…"。
   - 修复：显式空态 + 错误态 + 重试。
6. **打印会打印出管理端导航**：`@media print` 只隐藏 `.app-header`，而管理端用的是 `.admin-sidebar` / `.admin-topbar`。
   - 修复：扩展打印隐藏规则并补齐 A4 表格/分页处理（第 4.3 节）。

### P2（仅记录，本轮不改）

1. `/orderbook` 的"完整赛程"小节在比赛很多时仍是一张长表；已用 `break-inside: avoid` 保证不切断单场，但未做按组分页。
2. Console"待进行比赛"在等待场次很多时（规模赛事）会很长；本轮未加分页或折叠。
3. `format_code` 为 null 的历史赛事在 Console 仍可排台（只是提示"尚未设置赛制"）；是否应直接阻断属 A/B 轨契约问题。

### Cross-track

```text
CROSS_TRACK DEFECT
Owner: D
Severity: P2
Reproduction: Mobile Score 页「比分已保存」与 refreshWarning 文案重复
              （"比分已保存 比分已保存，但最新状态刷新失败…"）
Status: D-Day6D 已记录，本轮复跑 D6D 现场模拟时依然可见（113/113 PASS，非阻塞）
```

本轮**未修改**以下 D 轨文件：`PublicRoutes.tsx`、Public 报名相关页面、Mobile Score 核心业务、BigScreen Public 行为、LAN 启动策略。`SchedulePage` 的 public 分支保持原行为并已加回归测试。

## 7. 验证

全部数字来自本轮真实执行。

```text
backend pytest           1053 passed, 0 failed, 0 skipped, 4 warnings (4m1s)
frontend pnpm test       17 files / 259 tests passed（基线 15 / 219）
pnpm exec tsc --noEmit   exit 0
pnpm build               PASS（dist/index.html + hashed css/js）
pnpm contract:check      PASS（提交后 openapi-typescript 重新生成无差异）
python export_openapi.py --check   OpenAPI snapshot is up to date
git diff --check         干净（无空白错误）
```

跨轨回归（D6D 既有 Gate 全部复跑）：

```text
day6d_field_simulation.mjs   113/113 PASS   E5 全链 / Mobile Score / Public / BigScreen / 并发 / 断网恢复
day6d_public_viewport_check.mjs 168/168 PASS 360/375/390/430 布局
day6d_restart_check.py        15/15 PASS     重启前后 15 项事实一致
```

C 轨专项：

```text
c_day5_admin_field_check.mjs        75/75 PASS   1280×900 + 1440×900 管理端现场
c_day5_field_chain_check.mjs ranked 23/23 PASS   16 人 / 6 台完整现场链
c_day5_field_chain_check.mjs blocked 11/11 PASS  后端阻断时前端不变量
```

浏览器验收环境：production 单服务（`uvicorn app.main:app`，同一进程托管 `frontend/dist`）+ 真实 Chrome 154（headless / CDP 9333）+ 独立 BrowserContext 登录真实 EVENT_ADMIN。验收使用的赛事 tid 为运行期创建的真实赛事，**未把任何 tid 写进生产代码**。

## 8. 修改文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/schemas.py` | 新增 `DashboardCompletion`，挂到 `Dashboard` 响应 |
| `backend/app/services/scheduling.py` | 新增 `resolve_completion_state()` 只读透传 Handler 状态 |
| `backend/app/routers/scheduling.py` | Dashboard 路由带出 `completion` |
| `docs/openapi-v0.2.json` | 契约快照同步 |
| `frontend/src/generated/openapi.d.ts` | openapi-typescript 重新生成 |
| `frontend/src/api.ts` | 导出 `DashboardCompletion` 类型 |
| `frontend/src/fieldOps.ts` | 新增：completion 文案映射、球台排序、可操作性判定（纯展示层，无业务算法） |
| `frontend/src/pages/ConsolePage.tsx` | 5 秒同步 / stale / 阶段收口 / 后端候选排台 / 操作分层 / TEAM 边界 |
| `frontend/src/components/LiveTableCard.tsx` | 后端推荐只读展示、阶段原因、Match 状态 |
| `frontend/src/pages/SchedulePage.tsx` | 管理端默认实时赛程 + 打印快照语义（public 分支不变） |
| `frontend/src/pages/OrderBookPage.tsx` | "暂未关联官方秩序册"、实时快照语义、空态/错误态/重试 |
| `frontend/src/App.tsx` | 管理端 `/schedule` 显式传 `variant="admin"` |
| `frontend/src/index.css` | Console / 实时赛程 / 秩序册样式；`@page` + `@media print` A4 收口 |
| `frontend/src/__tests__/AdminD5Dashboard.test.tsx` | 夹具补 `completion` 字段 |
| `frontend/src/__tests__/AdminD5ConsoleFieldOps.test.tsx` | 新增（25 tests） |
| `frontend/src/__tests__/AdminD5SchedulePrint.test.tsx` | 新增（15 tests） |
| `backend/tests/test_c_d5_dashboard_completion.py` | 新增（16 tests） |
| `backend/c_day5_admin_fixture.py` | 新增：C-D5 标准验收赛事 fixture（16 人 / 4 组 / 6 台） |
| `backend/c_day5_admin_field_check.mjs` | 新增：管理端桌面现场 gate（1280/1440） |
| `backend/c_day5_field_chain_check.mjs` | 新增：16 人 / 6 台现场主链 gate（ranked / blocked） |

> 说明：`frontend/src/index.css` 是 Console 与打印共用的单一全局样式表，Phase 2 与 Phase 3 的样式改动落在同一个文件中。

## 9. 本轮判定与遗留

```text
Phase 1: DONE
Phase 2: DONE
Phase 3: DONE
Phase 4: DONE（管理端现场链）· PARTIAL（物理设备覆盖）
```

Phase 4 的 `PARTIAL` 只指一件事，且与 D-Day6D 记录的缺口相同：

- **真实手机数量 = 0、真实无线路由器 = 0、第二台终端 = 0**。本轮的"录分"是通过页面会话调用真实比分 API 完成的，管理端 Console/Schedule/OrderBook 与 Public/Mobile Score 的**页面行为**分别由 C 轨浏览器 gate 与 D6D 视口 gate 覆盖，但"多台物理手机 + 真实无线路由"这一条无法在本机声明为达标。
- 该项属 **D 轨**既有缺口（`docs/D6D_FIELD_SIMULATION.md` 第 10 节），C 轨不重复登记，也未把模拟结果写成物理现实。

其它未在本轮处理的跨轨待办（与 C-D4 记录一致，不阻塞 C-Day5 收口）：

- **A 轨**：统一 Rules Settings API、基本信息修改 API、`public_enabled`、动态球台与 `DISABLED` 状态。
- **B 轨**：按当前 `format_code` 的统一生成入口（`ROUND_ROBIN` / `SINGLE_ELIMINATION` 目前**没有 HTTP 生成入口**，路由仍固定 `GROUP_KNOCKOUT`），因此循环赛/单淘汰在真实界面上只能走到 `MATCHES_NOT_GENERATED`；C 轨已按此诚实展示，未在前端伪造生成能力。
- **D 轨**：官方秩序册文件、`public_enabled` 合入后的 Public 可见性。

## 10. 停止点

本轮唯一目标已达成：把 C 轨 Day5 从"Dashboard Phase 1 已完成"推进到"管理端现场运行链完整收口"。

PR 创建并请求 review 后**立即停止**，不自行 approve / merge，不进入 C-Day6。
