# 现场问题清单修复与验收（2026-10-05）

分支：`fix/field-issues-20261005`
基线：`master @ d6c4d3dd4c7f3a328ac918d22f3d7ed9be62023e`
范围：现场试跑反馈的 5 个缺陷（A–E）。本轮不新增功能、不改赛制 / 排名 / 晋级 / 认证 / 数据库。
浏览器证据目录：[`docs/evidence/field-issues-20261005/`](evidence/field-issues-20261005/)

## 0. Supervisor 根因判断核对结果

对 5 条根因逐条与仓库真实代码核对，**全部与代码一致，0 处偏差**：

| 问题 | Supervisor 判断 | 代码核对 |
| --- | --- | --- |
| A | 后端 `assign-table` 已存在，缺的是 Match→Table 的操作入口 | ✅ `POST /api/matches/{match_id}/assign-table`（`routers/scheduling.py:23`）与 `scheduling_service.assign_table()`（`services/scheduling.py:509`，带写锁重校验）均存在；ConsolePage 只有 Table→Match |
| B | 弹窗缺短 viewport / 高缩放处理 | ✅ `.modal-backdrop` 为 `grid + place-items:center` 且**不可滚动**；`.score-sheet` 无 `max-height` |
| C | 规则存在但 UI 没说"至少 2 个字" | ✅ 前端 `changeReason.trim().length >= 2`、后端 `_require_revision_audit`「修改比分必须填写至少 2 个字的修改理由」，而 placeholder 只有「必填：说明为什么修改本场结果」 |
| D | 测量只依赖 `[rounds, champion]`，且 SVG 在滚动容器之外 | ✅ effect 依赖 `[rounds, champion]`；`.ko-bracket{overflow-x:auto}`，`.ko-lines` 是 `.ko-bracket-wrap` 的直接子元素 |
| E | 409 后失败端停在旧表单 | ✅ `MobileScorePage.runSubmit` catch 只 `setFormError`；`ConsolePage.saveScoreSheet` catch 只 `setScoreSubmitError`；后端并发语义正确（1 成功 / 1 个 409） |

## 1. Issue A — 指定某场比赛到指定球台

### 现象与根因

现场需要「先找到张三 VS 李四，再指定到 3 号台」，但 Console 只提供反向路径
（空闲球台 → 安排比赛）。后端 `assign-table` 一直是完整的，缺的是产品入口。

### 修复

- `frontend/src/fieldOps.ts`：新增 `freeTables()`（候选只取后端 `tables[].status === 'FREE'`）
  与 `isPlayableMatch()`（成员资格判定复用既有 `canAssignMatches` + `dashboard.next_playable`）。
- `frontend/src/pages/ConsolePage.tsx`：「待进行比赛」卡片增加 `[指定球台]`，弹出面板列出后端 FREE 球台，
  提交走**同一个** `api.assignTable(matchId, tableId)`。冲突时相信后端 409 → 强制刷新 → 提示重新选择，**不重发**。
- `frontend/src/index.css`：`.waiting-match-actions` / `.console-table-item` 两个小规则。

**没有**第二套调度逻辑：前端不挑比赛、不重排优先级、不允许重新组合两名选手临时造 Match。

### 验收

| 断言 | 实测 |
| --- | --- |
| 后端可安排比赛 + FREE 球台 ≥ 2 | playable=4 free=4 |
| 卡片出现「指定球台」入口 | ✅ |
| 候选只列 FREE 球台 | 候选 = 1/2/3/4 号台（当时全部空闲），占用球台 0 张 |
| 指定后 `Match.status` / `table_id` | match#25 → `PLAYING`，`table_id=2`（指定 2 号台） |
| 对应球台状态 | 2 号台 → `OCCUPIED` |
| 其他 WAITING 比赛不受影响 | ✅ #26 仍未上任何球台 |
| 已占用球台从候选消失 | 二次开面板：候选 = 1/3/4 号台，2 号台已排除 |
| 自动排台仍可用（CASE B） | `playing 1 → 4` |

## 2. Issue B — 录分弹窗在手机 / 高缩放下完整可操作

### 根因

`.modal-backdrop, .score-sheet-backdrop` 使用 `position: fixed; inset: 0; display: grid;
place-items: center`，**本身不可滚动**：内容高于 viewport 时居中会把上下两端同时挤出容器，
超出部分永久不可达；`.score-sheet` 又没有 `max-height`，内容有多高就多高。

### 修复（`frontend/src/index.css`）

- 遮罩：保留 `position: fixed; inset: 0`，新增 `overflow-y: auto`、
  `overscroll-behavior: contain`、`padding-bottom: max(20px, env(safe-area-inset-bottom))`；
  居中方式由 `place-items: center` 改为 flex `align-items: flex-start` + 面板 `margin: auto`
  （有剩余空间时才吸收，放不下时贴顶开始，向下滚动全部可达）。
- `.score-sheet`：`box-sizing: border-box`、`width: min(600px, 100%)`（不再用 `96vw`）、
  `max-height: calc(100dvh - 40px)`（`vh` 兜底）、`overflow-y: auto`、`overscroll-behavior: contain`。
- 面板底部操作与「确认修改」条在弹窗内**吸底**（`bottom: -26px` 抵消面板下内边距），
  实测 1280×720 与 360×640 下未滚动时主操作就已在屏内。
- 同一套约束覆盖 `.console-assign-panel` / `.score-audit-panel`（否则只是修好了一个弹窗）。

**未重写 Modal 系统**：`.modal` / `.roster-modal` / `.team-modal` 已带 `margin: auto`，行为不变；
打印媒体查询里 `.modal-backdrop { display: none }` 亦未改动。

### 验收（真实 Chromium，含 jsdom 覆盖不到的布局）

5 组 viewport × 11 个控件全部可达（滚动到控件后盒模型完整落在视口内、中心点最上层元素仍属于弹窗）：

| viewport | 控件可达 | 横向溢出 | 弹窗盒 | 未滚动时主操作位置 |
| --- | --- | --- | --- | --- |
| 360×640 | 11/11 | 0px | 320×600 | top=581 bottom=618（vh=640） |
| 390×844 | 11/11 | 0px | 350×779 | top=746 bottom=783（vh=844） |
| 768×1024 | 11/11 | 0px | 600×749 | top=821 bottom=858（vh=1024） |
| 1280×720（普通电脑 100%） | 11/11 | 0px | 600×680 | top=661 bottom=698（vh=720） |
| 360×420（等效短 viewport） | 11/11 | 0px | 320×380 | top=361 bottom=398（vh=420） |

- 覆盖项：标题 / 双方选手 / 大比分控件 / 备注 / 操作人 / 修改理由 / 取消 / 确认 / 关闭。
- 弹窗是 `position: fixed; z-index: 150` 的 viewport overlay，中心点最上层元素属于弹窗；
  背景列表滚动 600px 后弹窗几何完全不变（`before == after`）且仍在最上层。
- 高页面缩放（1280×720 @ CSS zoom 2 ≈ 640×360 布局）：8/8 关键控件可达；
  弹窗不引入任何横向页面溢出（有弹窗 1460 = 无弹窗 1460）。

截图：[`scoresheet-360x640.png`](evidence/field-issues-20261005/scoresheet-360x640.png)、
[`scoresheet-360x420.png`](evidence/field-issues-20261005/scoresheet-360x420.png)、
[`scoresheet-1280x720.png`](evidence/field-issues-20261005/scoresheet-1280x720.png)、
[`scoresheet-zoom2.png`](evidence/field-issues-20261005/scoresheet-zoom2.png)

## 3. Issue C — 明确说明"修改理由至少 2 个字"

### 根因

规则本身两侧都已存在（前端 `>= 2`、后端 422「必须填写至少 2 个字的修改理由」），
但 UI 只有一个「必填：说明为什么修改本场结果」的 placeholder：裁判填了 1 个字后按钮直接变灰，
页面不说为什么，现场只能反复重试。这是 UX 缺陷，不是规则缺陷。

### 修复（`frontend/src/components/ScoreSheet.tsx`、`frontend/src/index.css`）

- `auditMode === 'revise'` 时字段下方常驻规则说明：**「修改已结束比赛时必填，至少 2 个字」**，
  并实时显示「当前已填 N 个字」。
- 输入 1 个字或只填空格时给出**字段级错误**（`role="alert"`、`aria-invalid`），
  文案带上被禁用的按钮名（「检查并修改」/「保存小分」）与当前有效字数。
- `textarea` 加 `minLength={2}` 与 `aria-describedby`，但**不依赖**原生校验。
- 提示文本刻意放在 `<label>` 之外：label 的可访问名必须保持"修改理由"本身。

**未改变** `auditMode === 'record'`（首次录分）的既有规则 —— 该模式根本不渲染修改理由字段。

### 验收

| 断言 | 实测 |
| --- | --- |
| 未输入时规则可见 | 「修改已结束比赛时必填，至少 2 个字。」 |
| `minLength=2` | ✅（`aria-describedby=score-change-reason-rule`） |
| 填 1 个字 | 错误「修改理由不足 2 个字，「检查并修改」暂时不能提交；当前有效字数 1 个」+ 按钮 disabled |
| 补足 2 个字 | 错误消失、按钮可点 |
| 只填空格 | 按 0 个字处理并给出字段级错误 |
| 补录 / 修改逐局小分 | 同一条 revise 规则（文案显示「保存小分」） |
| 首次录分 record | 不出现修改理由字段 |

## 4. Issue D — 淘汰赛移动端 SVG 分支线错位

### 根因（两条，缺一不可）

1. SVG 被放在横向滚动容器**外面**：`.ko-bracket` 一滚动，卡片跟着动而 SVG 不动，连线立即与卡片分离；
2. 测量 effect 只依赖 `[rounds, champion]`，viewport 变化 / 横竖屏 / 字体与卡片尺寸变化 /
   容器 resize 之后卡片几何已变而 path 仍是旧坐标。

### 修复

- `frontend/src/components/KnockoutBracket.tsx`：抽出 `recomputeLines()`；
  把 SVG 移入与全部卡片**共处**的 `.ko-canvas`（滚动时两者同时平移，坐标系不变）；
  监听 `ResizeObserver`（画布 + 外层容器）、`window resize`、`orientationchange`，
  用 `requestAnimationFrame` 合并同一帧内的多次触发；卸载时 `cancelAnimationFrame` +
  `observer.disconnect()` + 移除两个 listener（逐项有回归测试）。
- `frontend/src/index.css`：`.ko-bracket` 只保留 `overflow-x: auto`；
  新增 `.ko-canvas { position: relative; display: flex; gap: 56px; width: max-content; min-width: 100% }`。

**刻意不监听 canvas 的 scroll**：SVG 与卡片同在 canvas 内，滚动同时平移两者，为滚动重算既无必要
也会让移动端每帧都读一次布局。未引入 React Flow / D3，未按人数复制第二套 SVG。

### 验收（视口坐标逐条对齐校验，容差 0.75px）

判据：每条 path 换算回视口坐标后，起点必须等于某张卡片右边缘 × 垂直中心，
终点必须等于另一张卡片左边缘 × 垂直中心（冠军线终点对应冠军卡左侧 −14px）。

| 场景 | 360×640 | 390×844 | 1280×900 |
| --- | --- | --- | --- |
| 初始（6 条分支线） | 6/6 | 6/6 | 6/6 |
| 横向滚动到最右 | 6/6（scrollLeft=696/1008） | 6/6（666/1008） | 6/6（28/1008） |
| 横向滚动到中间 | 6/6 | 6/6 | 6/6 |
| 页面横向溢出 | 0px | 0px | 0px |
| 满签表（八强→半决赛→决赛→冠军） | 6/6 + 冠军线 | 6/6 + 冠军线 | 6/6 + 冠军线 |
| 满签表滚动到最右 | 6/6 + 冠军线 | 6/6 + 冠军线 | 6/6 + 冠军线 |

- resize 宽 → 窄 → 宽：`wide1=6/6 narrow=6/6 wide2=6/6`
- 竖屏 ↔ 横屏：`portrait=6/6 landscape=6/6`
- 八强 → 半决赛 → 决赛关系未串线（反向断言也覆盖：不存在"八强直接连到决赛"的 path）

截图：[`bracket-full-390x844-left.png`](evidence/field-issues-20261005/bracket-full-390x844-left.png)（初始）、
[`bracket-full-360x640-mid.png`](evidence/field-issues-20261005/bracket-full-360x640-mid.png)（滚动到中间）

## 5. Issue E — 两个裁判同场，失败端自动收口到权威状态

### 根因

后端正确：`write_transaction` + `request_id` 幂等 + 同 Match 并发测试已保证"一人成功、一人 409、
数据库只保留一份结果"。缺陷在失败端 UX：`MobileScorePage.runSubmit` 的 catch 只 `setFormError`，
`ConsolePage.saveScoreSheet` 的 catch 只 `setScoreSubmitError`，于是裁判停在旧的可提交表单上，
看起来像"卡住"，还可能诱发重复提交。

### 修复

- `frontend/src/pages/MobileScorePage.tsx`：POST 捕获到 `ApiError.status === 409` 时
  **不重发**，改为：置冲突提示 → 调用既有 `load()` → 经既有 generation 守卫 `applyLoadResult()` →
  服务端已 `FINISHED` 时页面自然进入真实完成态并展示对方保存的比分 →
  在 `finally` 中释放 `inFlight` / `submitting`。
  权威重载失败时退出"提交中"、如实说明「比赛状态已经变化，但暂时无法取得最新结果，请重新加载。」、
  给出明确的「重新加载」按钮，并**锁死**再次提交（状态已确认过期）。
  新增 `conflictNotice` / `conflictReloadFailed` 两个状态，与既有的 `refreshWarning`（"POST 成功但刷新失败"）
  **刻意分开**，避免把"本次没写入"说成"已保存"。
- `frontend/src/pages/ConsolePage.tsx`：`refresh()` 现在返回"本次是否真的提交了新快照"并支持 `force`
  （冲突收口必须拿到此刻的权威状态，不能被更早的在途请求代表）；
  首次录分（record）遇 409 → 关闭旧弹窗 → 强制刷新 → 反馈「该场比赛状态已由其他终端更新，已加载最新现场状态。」；
  刷新失败时明确提示「检测到状态冲突，但刷新最新现场状态失败，请手动重试」。
  **revise 的 409 保持服务端真实语义**（例如淘汰赛下游已开打），不假设"别人已经录分"。

### 验收（真实双终端）

| 断言 | 实测 |
| --- | --- |
| 裁判 A 提交 | 200，比赛 FINISHED |
| 裁判 B 只发出 1 次比分 POST | POST 次数 = 1（409 未被自动重试） |
| B 自动 reload 并进入完成态 | ✅ 旧可提交表单按钮数 = 0 |
| B 展示服务端真实比分 | `2 : 1`（不是本地待提交的 `2 : 0`） |
| B 收到冲突说明 | 「该场比赛已由其他终端更新，已加载最新结果。（服务端：只有进行中或待安排的比赛可以录入比分）」 |
| 无无限 loading | 提交中状态已释放 |
| 数据库结果唯一 | `score_audits = 1`，状态 FINISHED，比分 2:1 |
| CASE H 不同 Match 并发 | 两个请求都 200，各自写入自己的结果（未被冲突收口误伤） |

截图：[`conflict-finished-390x844.png`](evidence/field-issues-20261005/conflict-finished-390x844.png)

## 6. 回归测试

| gate | 基线（d6c4d3dd） | 本轮 |
| --- | --- | --- |
| `pytest`（backend） | 1065 passed / 80 files | **1067 passed**（exit 0） |
| `pnpm test`（frontend） | 280 passed / 20 files | **308 passed / 21 files** |
| `pnpm exec tsc --noEmit` | exit 0 | exit 0 |
| `pnpm build` | exit 0 | exit 0 |
| 真实 Chromium 验收 | — | **80/80 通过**（`results.json`） |

新增 / 扩展的回归：

- `src/__tests__/ConsoleScoreWorkflow.test.tsx`：Issue C 规则可见性、1 个字 / 空格字段级错误、
  `minLength`、detailMode、record 模式不受影响。
- `src/__tests__/AdminD5ConsoleFieldOps.test.tsx`：Issue A 入口只对后端合法比赛出现、
  候选只来自 FREE、409 后刷新且不重发、批量排台仍可用；Issue E 首次录分 409 收口与 revise 不被改写。
- `src/__tests__/MobileScorePage.test.tsx`：Issue E 三条（重载成功 / 已 FINISHED / 重载失败锁死重复提交），
  并把两条断言旧行为的用例改写为新要求的行为（保留其原本要保护的"不静默、不卡死"语义）。
- `src/__tests__/KnockoutBracketGeometry.test.tsx`（新增）：SVG 与卡片同处滚动画布、
  6 条分支线拓扑不串线、resize / window resize 触发重算、rAF 合并、卸载彻底清理。
- `src/__tests__/PhysicalFieldDefects.test.tsx`：Issue B 的 CSS 契约与弹窗 DOM 可达性前置条件。
- `backend/tests/test_d6a_concurrency.py`：`test_d6a_two_referees_same_match_one_succeeds_one_409`、
  `test_d6a_two_referees_different_matches_both_succeed`（纯新增，未改动既有用例）。

## 7. 已知剩余问题 / 本轮未做

1. **背景控制台表格在 200% 页面缩放下的既有横向溢出**：1280×720 @ zoom 2 时
   `documentElement.scrollWidth = 1460`（有弹窗与无弹窗完全相同，弹窗贡献为 0）。
   这是控制台页面自身的响应式问题，不属于本轮 5 个问题，未修。
2. **手机录分页没有改分入口**：仍与既有一致（本轮只用于现场首次录分），未扩大范围。
3. **未做真实手机 / LAN 回验**：本轮证据来自真实 Chromium + 真实前后端 + viewport 模拟，
   不等于真机 LAN 验收；按 `docs/D6_PHYSICAL_FIELD_DEFECT_REGISTER.md` 的关闭规则，
   真机回验仍需在现场完成。
4. 未发现新的 P0 / P1。
