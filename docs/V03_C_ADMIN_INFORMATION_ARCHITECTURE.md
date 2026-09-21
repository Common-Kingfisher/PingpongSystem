# PingpongSystem V0.3 — C 轨管理端信息架构冻结稿

状态：Day 1 冻结稿
负责人：C 轨｜管理端前端
基线：`origin/master@d821b0d`（2026-09-21）
工作分支：`feat/v03-admin-layout`

## 1. Day 1 结论

V0.3 管理端采用“我的赛事 → 选择赛事 → 进入赛事 Admin”的两层结构。赛事内部采用固定左侧导航与右侧工作区；旧 URL 暂时保留，通过 Layout 包装实现迁移，不在 Day 1 重写成熟业务页面或复制后端算法。

当前协作状态：B 轨 Day 1 已合入 `master`；A 轨 PR #35 仍开放且修改 `App.tsx`、`api.ts`、`index.css`；D 轨已冻结 Public/mobile/deploy 设计但尚无开放 PR。因此 C Day 1 只新增独立文档、Layout、Dashboard 和共置 CSS，不改三份共享入口文件。

## 2. 设计方向

### 2.1 使用对象与单一任务

- 对象：桌面端主裁判、赛事管理员。
- 单一任务：在一场已选择的赛事中，快速判断当前阶段并进入正确操作页面。
- 视觉语义：赛事操作台，而非通用 SaaS 后台。

### 2.2 视觉 Token

| Token | 色值 | 用途 |
| --- | --- | --- |
| 深海军蓝 | `#102A43` | 固定侧栏、进度主面板 |
| 墨色 | `#0B1F33` | 正文与高密度数据 |
| 信号蓝 | `#1769E0` | 当前导航、主要动作 |
| 判定红 | `#D84A4A` | 比分轨、警示与现场态 |
| 球台绿 | `#16825D` | 已完成进度 |
| 纸面灰 | `#F4F7FA` | 工作区底色 |

字体分工：标题与数字使用 Bahnschrift / Arial Narrow，正文使用 Microsoft YaHei UI / PingFang SC，状态标签使用等宽字体。唯一视觉标志是侧栏左缘的红蓝“双线比分轨”，其余区域保持克制。

### 2.3 布局

```text
┌──────────────────────┬────────────────────────────────────────────┐
│ TT 赛事管理          │ 当前赛事              Public  用户  退出 │
│ 当前赛事 / 我的赛事  ├────────────────────────────────────────────┤
│                      │                                            │
│ 赛事总览             │                  Outlet                    │
│ 参赛名单             │                                            │
│ 分组抽签             │   Console 可切换为更紧凑的全宽内容模式     │
│ 秩序册               │                                            │
│ 比赛控制             │                                            │
│ 排名                 │                                            │
│ 淘汰赛               │                                            │
│ ─────────────        │                                            │
│ 赛事设置             │                                            │
└──────────────────────┴────────────────────────────────────────────┘
```

## 3. AdminLayout 冻结

### 3.1 顶部栏

只保留：当前赛事名称、Public 快捷入口、当前用户、退出。功能导航不再堆放在顶部。

### 3.2 左侧导航顺序

1. 赛事总览
2. 参赛名单
3. 分组抽签
4. 秩序册
5. 比赛控制
6. 排名
7. 淘汰赛
8. 分隔线
9. 赛事设置

秩序册位于比赛控制之前，因为它在开赛前生成、赛中持续更新，是执行主链的一部分。

### 3.3 权限灰态

菜单不因无权限而消失。无权项目保持原位置、显示灰态，并在点击时明确提示“无权限”。后端仍是权限唯一权威；前端只消费 A 轨提供的授权结果，不自行判断角色或赛事归属。

### 3.4 多赛事切换

侧栏只保留轻量“当前赛事 / 返回我的赛事”。切换赛事时，Day 2 优先保持当前功能页；目标不存在或无权访问时再回到赛事总览。不建设复杂 workspace。

## 4. Dashboard 定义

Dashboard 只包含六类信息：

1. 当前赛事阶段；
2. 已完成 / 总场数、进行中、待比赛；
3. 运动员、Entry、小组数量；
4. 后端提供的下一步推荐操作；
5. 少量正在进行的比赛；
6. Public 快捷入口。

`AdminDashboardPage` 使用显式 ViewModel 边界。没有数据时显示“等待赛事概览数据”，不填演示数字、不根据前端已有字段复制业务状态机。未来 next action 与 completion state 必须直接消费 B/A 后端权威结果。

## 5. 赛事设置

赛事设置只用页面内 Tab，不增加第二套左侧导航：

| Tab | 内容边界 |
| --- | --- |
| 基本信息 | 名称、日期、Organization、Venue、其他基础信息 |
| 赛制与规则 | `format_code`、`rule_config`、局制、晋级规则、种子规则 |
| 报名设置 | 开放/关闭、报名状态、Registration 相关设置 |
| 公开与展示 | Public 入口、大屏、公开签表、选手赛程、报名页与展示开关 |
| 高级操作 | 结束、封存、解锁、删除等高风险操作 |

种子规则和每组晋级人数只能在“赛制与规则”配置。分组抽签页只读展示当前配置，不提供第二修改入口。

## 6. 参赛名单与分组抽签边界

### 6.1 参赛名单：谁参加比赛

承载名单概况、添加/编辑/删除、Excel/CSV、Player/Entry、Affiliation、积分、双打/团体名单入口、退赛、名单确认。确认名单后不自动抽签，只显示：

```text
✓ 名单已确认
[下一步：前往分组抽签]
```

比赛开始后普通增删改可以锁定，但 Entry 状态、办理退赛和退赛记录仍在名单页。退赛对比赛、排名和晋级的影响完全由后端处理。

### 6.2 分组抽签：如何进入比赛结构

承载赛制摘要、后端种子结果、抽签规则摘要、一键抽签、分组结果、重新抽签、晋级规则只读展示、生成比赛。

抽签优先级只展示 B 轨冻结结果：

```text
赛制合法性 > 种子保护 > 同单位/同队伍规避 > 组人数/签区均衡 > 随机性
```

前端不排序决定种子，不实现单位规避，不生成对阵。

### 6.3 一键正式抽签

抽签前展示规则摘要，点击“一键抽签”后进行一次确认：

```text
即将按照以上规则执行正式抽签。
[取消并返回修改] [确认开始抽签]
```

抽签后、生成比赛前可重新抽签；重新抽签再次确认。生成比赛后普通 UI 锁定分组，不在 Day 1 发明高级解锁流程。

```text
名单确认 → 种子结果 → 一键抽签 → 分组结果 → 生成比赛
                                             ├─ 查看秩序册
                                             └─ 进入比赛控制
```

## 7. URL 与页面迁移表

| 当前 URL / 页面 | V0.3 管理端位置 | 复用策略 | 新页面 | 后端依赖 |
| --- | --- | --- | --- | --- |
| `/` HomePage | 登录后“我的赛事”；选中后进入赛事总览 | 拆分并复用赛事列表/创建能力 | `AdminDashboardPage` | 当前用户可管理赛事列表、Dashboard completion state |
| `/players` PlayersPage | 参赛名单 | 复用名单、导入、Entry、退赛与确认能力；移出抽签区域 | 否，后续拆组件 | A：Registration/Affiliation；现有名单 API |
| `/draw`（暂无） | 分组抽签 | 从 PlayersPage 迁移抽签、分组、生成比赛能力 | 是 | B：种子/抽签规则结果、可复现随机种子、completion state |
| `/orderbook` OrderBookPage | 秩序册 | 原页复用，保持全量打印 | 否 | 现有秩序册/比赛数据 |
| `/console` ConsolePage | 比赛控制 | 原页复用，Layout 使用密集模式 | 否 | 现有调度与比分 API；B 的最终比分契约 |
| `/rankings` RankingsPage | 排名 | 原页复用 | 否 | 后端排名与数据不足状态 |
| `/knockout` KnockoutPage | 淘汰赛 | 原页复用 | 否 | 后端签表、BYE、晋级结果 |
| `/preflight` PreflightPage | 赛事总览中的检查入口，不占主导航 | 保留旧深链 | 否 | 现有 preflight API |
| `/schedule` SchedulePage | Public 快捷入口/公开展示 | 保留旧 URL；交由 D 包装 PublicLayout | 否 | D 的 Public 路由与公开读取权限 |
| `/bigscreen` BigScreenPage | Public 快捷入口 | 原页复用；保留旧 URL | 否 | D 的 Public 路由 |
| `/register` RegisterPage | Public 报名 | 保留旧 URL；待 A 的 Registration contract 后切换 | 否 | A：Registration、registration_enabled |
| `/journey` ChampionJourneyPage | 淘汰赛的展示入口 / Public | 保留旧 URL | 否 | D 的 Public 路由 |
| `/match-print` MatchPrintPage | 比赛控制/秩序册的打印动作 | 原页复用 | 否 | 现有 Match DTO |
| `/team-roster` TeamRosterPage | 参赛名单（团体分支） | 必须保留 | 否 | 现有 TEAM runtime；A 契约同步 |
| `/team-ties` TeamTiesPage | 比赛控制（团体分支） | 必须保留 | 否 | 现有 TEAM runtime |
| `/team-tie` TeamTiePage | 单场团体对抗详情 | 保留深链 | 否 | 现有 TEAM runtime |
| `/team-rankings` TeamRankingsPage | 排名（团体分支） | 必须保留 | 否 | 后端团体排名 |
| `/team-qualification` TeamQualificationPage | 淘汰赛前晋级确认 | 必须保留 | 否 | 后端团体资格确认 |
| `/team-knockout` TeamKnockoutPage | 淘汰赛（团体分支） | 必须保留 | 否 | 后端团体签表 |
| `/settings`（暂无） | 赛事设置 | 无旧页可直接复用 | 是 | A：Organization/Venue/Registration/权限；B：format/rule config |

Day 2 可以在不改变上述 URL 的前提下用 AdminLayout 包装。是否最终迁移到 `/admin/...` 留到兼容期之后；本阶段不追求 URL 完美。

## 8. C / D 共享边界

- C 拥有 AdminLayout、管理端 IA、赛事内部导航和桌面体验。
- D 拥有 PublicLayout、公开报名/实况/签表、手机录分 UI、部署与 LAN。
- 手机录分属于受保护的 Admin 域，复用 C/A 的 AuthGuard，不另建第二套管理 Layout。
- C Day 1 不修改 `App.tsx`；D 挂 Public route 前先等待 C/A 冻结 route shell。
- Public 页面不得依赖管理员浏览器的 active tournament localStorage；必须由 URL 显式携带赛事 ID。

## 9. API 依赖点

| Owner | C 等待的权威能力 | C 不做什么 |
| --- | --- | --- |
| A | 当前用户、登录/退出、401/403、赛事授权、TournamentAdmin、Organization、Venue、Registration、公开开关 | 不自定义临时 JWT/session，不在前端判定真实权限 |
| B | format summary、rule config、种子结果、抽签结果、completion state、next action、排名数据不足、最终比分契约 | 不复制赛制、排名、种子、单位规避、比分合法性算法 |
| D | Public route、公开页面 URL、手机录分路由、公开展示入口 | 不修改 PublicLayout 和移动端录分 |

所有 API 类型继续以 generated OpenAPI contract 为准。Day 1 不修改 `api.ts`、OpenAPI snapshot 或后端 Schema。

## 10. Day 2 接入清单

1. 等 A PR #35 合入后先同步 `master`，复核 `App.tsx/api.ts/index.css`。
2. 接入 Login、AuthGuard、当前用户和角色分流。
3. 把“我的赛事”和赛事 Admin 路由拆成 route shell；旧 URL 作为 alias 保留。
4. 将 AdminLayout 接到现有成熟 Page，不重写 Page 业务。
5. 从 PlayersPage 抽出名单区与抽签区；先复用组件，再建立 `/draw`。
6. 对接后端 completion state / next action，替换 Dashboard 空态。
7. 对接权限结果，驱动菜单灰态；服务端 403 仍是最终防线。
8. 与 D 共同合并 Public 快捷入口和受保护手机录分 route。
9. 增加键盘导航、桌面宽度和 Console 密集模式浏览器验收。

## 11. Day 1 非目标

未实现登录/JWT/session、后端权限、规则算法、API contract、完整赛事设置、完整名单拆页、完整抽签页、PublicLayout、移动端录分，也未修改 `App.tsx`、`api.ts`、`index.css`、后端模型或业务服务。
