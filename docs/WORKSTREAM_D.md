# PingpongSystem V0.3 — D 轨 Day 1 设计冻结稿

基线仓库：`Common-Kingfisher/PingpongSystem`
检查分支：`master`
检查时 master HEAD：`5f198ea80b398420039188f564a148a3f69c80ea`

## 1. D 轨 Day 1 目标

根据 V0.3 五人分工，D 轨 Day 1 只完成设计冻结，不提前抢 Day 2/Day 3 的实现工作：

- 设计 PublicLayout / 公共端路由结构
- 设计手机录分入口和交互边界
- 设计 production 单服务 + LAN 启动流程
- 明确与 A/B/C/E 的接口依赖
- 明确兼容策略，保证 V0.2 现有 Demo 主链不被破坏

Day 1 不改比分业务算法、不实现认证、不改 Registration 数据模型、不重写现有页面。

---

## 2. 当前仓库真实状态

### 2.1 前端路由

当前 `frontend/src/App.tsx` 使用一套统一顶部导航，管理员、报名者、观众共用同一 App Shell。

当前相关页面已经存在：

- `/console`
- `/rankings`
- `/knockout`
- `/schedule`
- `/bigscreen`
- `/register`
- `/journey`
- `/orderbook`

因此 V0.3 不需要重写页面，主要工作是重新组织 Layout / Route。

### 2.2 在线报名

当前 `RegisterPage.tsx` 直接调用：

`api.addPlayer(tid, ...)`

即公开报名会直接写入正式 Player。

这与 V0.3 冻结规则不一致：

公开报名应先进入 `Registration(pending)`，再由 EVENT_ADMIN 确认入赛。

因此 Day 1 只记录该差异；真正切换 API 要等 A 轨 Registration contract。

### 2.3 赛事大屏

当前 `BigScreenPage.tsx` 已经具备：

- 赛事阶段展示
- 球台状态
- 当前比赛
- 即将开始
- 小组排名
- 淘汰 Bracket
- 冠军展示
- 约 2 秒 polling
- 单次轮询失败保留旧数据

这些能力应直接复用到 PublicLayout，不应重写业务。

### 2.4 手机录分基础

现有 `ConsolePage + ScoreSheet + TouchScoreInput` 已有：

- 大比分录入
- 触屏输入
- 异常结果
- 裁判/操作人字段
- 修改审计
- request_id 幂等重试

但是当前逐局小比分主要是“赛后补录模式”。

V0.3 冻结要求是：

- 大比分必填
- 小比分可选
- 若小比分同次提交，则必须与大比分一致

因此手机录分页不能复制当前校验逻辑；应等待 B 轨最终 Score contract，并复用统一 API。

### 2.5 API 地址

`frontend/src/api.ts` 使用相对路径：

`/api/...`

这是 production 单服务的理想形式，无需改成固定 IP/端口。

### 2.6 当前启动方式

`start_demo.ps1` 当前启动：

- FastAPI：8000
- Vite：5173

是双进程开发模式。

后端 `main.py` 当前：

- 没有托管 `frontend/dist`
- CORS 只放行 localhost/127.0.0.1:5173
- uvicorn 启动未指定 `--host 0.0.0.0`

所以当前启动方式不满足：

“单服务 + 局域网手机访问”。

---

## 3. PublicLayout 路由冻结方案

### 3.1 原则

公共页面必须满足：

1. PUBLIC 免登录
2. URL 可直接分享给手机
3. 不依赖管理员浏览器的 `localStorage.activeTournamentId`
4. URL 中必须显式包含 tournament id
5. 不出现录分、改规则、抽签、删除等管理按钮
6. 尽量复用现有 Page / 组件

### 3.2 推荐路由

```text
/public/t/:tid
/public/t/:tid/live
/public/t/:tid/register
/public/t/:tid/schedule
/public/t/:tid/rankings
/public/t/:tid/bracket
/public/t/:tid/champion
```

含义：

- `/public/t/:tid`：公共赛事首页，默认展示赛事概要并导向 live
- `/live`：复用 BigScreen / 实况能力
- `/register`：公开报名
- `/schedule`：选手个人赛程
- `/rankings`：排名
- `/bracket`：签表
- `/champion`：冠军之路

`orderbook` 本轮不作为 PUBLIC 主导航 P0；保留现有兼容入口即可。

### 3.3 PublicLayout 结构

```text
PublicLayout
├─ Tournament public header
│  ├─ 赛事名称
│  ├─ 当前阶段
│  └─ 简单状态
├─ Public navigation
│  ├─ 实况
│  ├─ 赛程
│  ├─ 排名
│  ├─ 签表
│  └─ 报名（仅 registration_enabled=true 时）
└─ Outlet
```

手机端导航优先使用：

- 横向可滚动 tabs，或
- 底部轻量导航

不要沿用当前十多个管理入口的顶部导航。

### 3.4 兼容策略

Day 2 不删除旧路由：

```text
/register?tid=...
/bigscreen?tid=...
/schedule?tid=...
/rankings?tid=...
/knockout?tid=...
/journey?tid=...
```

先让新 Public route 与旧页面共存。

旧入口后续可：

- redirect 到新路径，或
- 作为 route alias

这样避免破坏 V0.2 Demo、旧链接和其他开发轨道。

---

## 4. 手机录分入口冻结方案

### 4.1 权限归属

手机录分不是 PUBLIC。

它属于：

`EVENT_ADMIN`

D 只负责手机 UI；认证与赛事授权由 A 轨提供，业务校验由 B 轨提供。

### 4.2 推荐路由

```text
/admin/t/:tid/matches/:matchId/score
```

理由：

- 明确属于 Admin 域
- URL 能由控制台、球台二维码或待办列表直接打开
- 手机只聚焦一场比赛
- 复用 C 轨 Admin auth guard

如 C 轨最终冻结其他 Admin namespace，以 C/A 共识为准，但语义必须保持“受保护的单场录分页”。

### 4.3 手机录分页 UI

目标宽度：

`360–430px`

布局：

```text
赛事名
球台 / 场次 / 阶段
--------------------
选手/Entry A
[ 大比分触控输入 ]

        :

[ 大比分触控输入 ]
选手/Entry B
--------------------
[ + 可选录入逐局小比分 ]
--------------------
[ 正常完赛 ] [ 异常结果 ]
--------------------
备注 / 操作人
--------------------
[ 固定底部：确认提交 ]
```

要求：

- 一页只处理一场 Match
- 选手姓名大字号
- 主要按钮至少适合手指点击
- 提交按钮 sticky bottom
- loading 时防止重复点击
- 网络失败保留用户输入
- 401/403 明确提示重新登录/无赛事权限
- 409/422 显示服务端 detail，不自行猜业务原因
- 提交后显示成功态并返回赛事待录分列表或上一页

### 4.4 业务规则边界

D 不在页面复制以下规则：

- 什么大比分合法
- 小比分与大比分一致性
- 弃权如何计排名
- 改分是否允许影响下游
- WALKOVER / NO_SHOW / DISQUALIFIED 的领域规则

这些全部由 B/A 后端契约决定。

前端只做：

- 基础输入约束
- 可读错误展示
- 交互防重复
- 响应式布局

---

## 5. production 单服务 / LAN 启动冻结方案

### 5.1 目标

最终用户启动一次：

```powershell
.\start_pingpong.ps1
```

只启动一个对外 HTTP 服务。

手机、电脑全部访问：

```text
http://<LAN-IP>:8000
```

### 5.2 构建结构

发布前：

```text
frontend
  pnpm build
       ↓
frontend/dist
       ↓
FastAPI production static hosting
```

最终运行时不需要 Vite dev server。

发布包原则上不要求目标机器安装 Node；`dist` 在发布阶段提前构建。

### 5.3 FastAPI 托管策略

保持所有 `/api/*` router 不变。

production 模式增加：

```text
/assets/* -> frontend/dist/assets
其他非 /api GET -> frontend/dist/index.html
```

从而兼容 React BrowserRouter 深链接，例如：

```text
/public/t/12/live
/admin/t/12/matches/99/score
```

注意：

SPA fallback 必须放在 API routers 之后，不能吞掉 `/api/*`。

### 5.4 LAN 监听

production uvicorn：

```text
--host 0.0.0.0 --port 8000
```

启动脚本自动查找可用的私网 IPv4，并打印：

```text
本机管理：
http://127.0.0.1:8000

局域网访问：
http://192.168.x.x:8000
```

二维码属于 P1，可 Day 5/Day 7 再加。

### 5.5 CORS

production 前后端同源时不依赖 CORS。

开发环境仍保留 Vite 5173 → FastAPI 8000 的代理/开发配置。

不要为了 LAN production 把 CORS 粗暴改成 `*`。

### 5.6 Windows 防火墙

Day 1 只记录风险：

首次 LAN 访问可能被 Windows 防火墙阻挡。

本轮不默认让脚本自动创建管理员权限防火墙规则。

发布手册提供：

- 放行 Python/8000 的操作说明
- 或显式可选参数后续再实现

---

## 6. D 与其他轨道接口冻结

### A 轨

D 等待 A 提供：

- 登录方式（token/session）
- 当前用户接口
- 401/403 语义
- EVENT_ADMIN tournament authorization
- Registration API
- `registration_enabled`

D 不自行定义临时 auth 字段。

### B 轨

D 等待 B 提供：

- V0.3 ScoreRequest 最终字段
- 同次提交 games 的 contract
- 异常结果 contract
- 改分影响返回/错误码

D 复用服务端规则，不复制算法。

### C 轨

D 与 C 共用：

- `/admin/...` route tree
- AdminLayout
- AuthGuard
- 登录后跳转策略

D 不另起第二套管理员 Layout。

### E 轨

D 交给 E 的验收点：

- 375px / 390px / 430px 手机宽度
- Public 页面无管理操作
- 深链接刷新不 404
- LAN 地址可由第二台设备打开
- 前端 production build 后只需 8000
- 断网/刷新后的错误态
- 多手机同时读实况
- 手机重复点击比分提交不会双写

---

## 7. Day 2 / Day 3 文件边界预案

### Day 2 预计新增/修改

```text
frontend/src/App.tsx            或新 router 文件
frontend/src/layouts/PublicLayout.tsx
frontend/src/pages/...          仅做 route param 适配
backend/app/main.py             production static hosting PoC
start_pingpong.ps1              PoC
```

如果 C 同时重构 App/router：

D 不直接大改同一段 `App.tsx`，
先由 C 冻结 route shell，再把 Public route 挂入。

### Day 3 预计新增/修改

```text
frontend/src/pages/MobileScorePage.tsx
frontend/src/components/ScoreSheet.tsx（仅在 B 契约落地后最小适配）
frontend/src/api.ts             只消费 OpenAPI 生成 contract
frontend/src/index.css          手机布局
```

---

## 8. Day 1 明确不做

- 不实现 User/Auth
- 不实现 Registration schema
- 不把 RegisterPage 继续直写 Player 当成 V0.3 最终方案
- 不修改排名/晋级
- 不新增比分业务算法
- 不删除现有旧路由
- 不重写 BigScreen
- 不引入 Redux
- 不引入 WebSocket
- 不改数据库
- 不自动开放 Windows 防火墙
- 不要求 production 运行 Vite

---

## 9. Day 1 退出条件

D 轨 Day 1 达标标准：

- [x] 已核对当前 Public/报名/大屏/录分/启动代码
- [x] PublicLayout 信息架构已冻结
- [x] 公共路由 namespace 已冻结
- [x] 手机录分页定位与 route 已冻结
- [x] 手机录分只做 UI、业务规则归后端的边界已冻结
- [x] production 单服务拓扑已冻结
- [x] LAN 启动流程已冻结
- [x] 旧 Demo 路由兼容策略已冻结
- [x] A/B/C/E 接口依赖已写清
- [x] Day 2/Day 3 文件修改边界已预案

唯一待外部确认项：

1. C/A 最终管理员 route namespace 是否采用 `/admin/...`
2. A 的 auth 方式及 Registration contract
3. B 的 V0.3 ScoreRequest contract

这些不是 D Day 1 阻塞项，不需要在今天自行发明字段。

---

## 10. 推荐 D 分支

从当前最新 `master` 拉出：

```bash
git fetch origin --prune
git switch master
git pull --ff-only origin master

git switch -c feat/d-public-mobile-deploy
```

Day 1 如只提交设计文档，建议 commit：

```bash
git add docs/
git commit -m "docs(v0.3): freeze D-track public mobile deployment design"
```

Day 2 在同一 D 轨分支继续实现 PublicLayout / static hosting PoC，或按团队 PR 粒度再拆子分支。

---
---

# D 轨 Day 2 实施结果

分支：`feat/d-public-mobile-deploy`
Day 2 起点基线：`origin/master@b8fe480`（含 C 轨 Day 1 `AdminLayout`，PR #38）
Day 1 设计内容（第 1–10 节）未改动，本节只追加实施记录。

## 11. 本轮实际修改文件

### 11.1 新增

| 文件 | 目的 |
| --- | --- |
| `frontend/src/layouts/PublicLayout.tsx` | Public 端布局：赛事名 / 阶段 / 横向 Public 导航 / `Outlet` / 打印。tid 只取自 path param |
| `frontend/src/layouts/PublicLayout.css` | Public 布局样式，手机优先（360/375/390/430px），独立 CSS 命名空间 `.pub-*` |
| `frontend/src/PublicRoutes.tsx` | Public 路由表 + route adapter（tid 注入、legacy 标记、`readOnly`） |
| `frontend/src/publicTournament.ts` | `useTidFromPath()`：从 path param 解析 tid（不读 localStorage） |
| `backend/app/static_hosting.py` | production 单服务静态托管：`/assets/*` + SPA fallback（含 `/api/*` 排除） |
| `backend/tests/test_static_hosting.py` | 静态托管与 SPA fallback 安全测试（36 例） |
| `start_pingpong.ps1` | production / LAN 单服务启动脚本（UTF-8 BOM，见 17.4） |

### 11.2 修改

| 文件 | 目的 | 改动性质 |
| --- | --- | --- |
| `backend/app/main.py` | 在所有 router 之后调用 `install_static_hosting(app)` | +5 行 |
| `frontend/src/App.tsx` | `/public/...` 提前返回 `PublicRoutes`，不渲染管理端 Shell | +9 行，未动现有路由 |
| `frontend/src/pages/BigScreenPage.tsx` | 新增可选 `tid` prop | tid 解析 1 行 |
| `frontend/src/pages/SchedulePage.tsx` | 同上 | tid 解析 1 行 |
| `frontend/src/pages/ChampionJourneyPage.tsx` | 同上 | tid 解析 1 行 |
| `frontend/src/pages/RegisterPage.tsx` | 同上 + legacy 说明注释 | tid 解析 1 行 |
| `frontend/src/pages/RankingsPage.tsx` | 新增 `readOnly`，屏蔽写操作控件 | 条件渲染 |
| `frontend/src/pages/KnockoutPage.tsx` | 新增 `readOnly`，屏蔽写操作与生成入口 | 条件渲染 |

`start_demo.ps1`、`api.ts`、`index.css`、`AdminLayout.*`、A/B/C 轨页面与后端业务代码**均未修改**。

### 11.3 目录约定

Public 与 Admin 两套 Layout 统一放在 `frontend/src/layouts/`，便于对照与后续维护：

```text
frontend/src/layouts/AdminLayout.tsx     ← C 轨
frontend/src/layouts/AdminLayout.css
frontend/src/layouts/PublicLayout.tsx    ← D 轨
frontend/src/layouts/PublicLayout.css
```

`PublicRoutes.tsx` 与 `publicTournament.ts` 仍留在 `frontend/src/` 根：

* `PublicRoutes.tsx` 是**路由表**而非 Layout，与 `App.tsx` 同级更符合其“路由接线入口”的定位；
* `publicTournament.ts` 是与 `activeTournament.ts`（同在 src 根）配对的 tid 解析工具。

两者都保持独立文件，不并入 `App.tsx`，以降低与 A/C 轨的合并冲突面。

## 12. Public 路由矩阵

| Route | Page / Component | tid 来源 | Public |
| --- | --- | --- | --- |
| `/public/t/:tid` | `PublicIndexRedirect` → `/live` | path param | ✅ |
| `/public/t/:tid/live` | `BigScreenPage`（复用，含 2s polling） | path param → `tid` prop | ✅ |
| `/public/t/:tid/schedule` | `SchedulePage`（复用） | path param → `tid` prop | ✅ |
| `/public/t/:tid/rankings` | `RankingsPage`（复用，`readOnly`） | path param → `tid` prop | ✅ |
| `/public/t/:tid/bracket` | `KnockoutPage`（复用，`readOnly`） | path param → `tid` prop | ✅ |
| `/public/t/:tid/champion` | `ChampionJourneyPage`（复用） | path param → `tid` prop | ✅ |
| `/public/t/:tid/register` | `RegisterPage`（复用，**legacy**） | path param → `tid` prop | ✅ |
| `/public/t/:tid/*`（未知） | `PublicIndexRedirect` → `/live` | path param | ✅ |

旧 V0.2 URL 全部保留且未加 redirect：`/bigscreen`、`/schedule`、`/rankings`、`/knockout`、`/journey`、`/register`、`/orderbook`、`/players`、`/console`、`/preflight`、`/match-print`、`/team-*`。它们继续走 `?tid=` / `localStorage` 解析（`tid` prop 缺省时回退）。

### 12.1 tid 解析优先级

```text
显式 tid prop（Public path param）
  > ?tid= 查询参数
  > localStorage.activeTournamentId（仅 V0.2 旧路由回退）
```

Public URL 形如 `/public/t/12/live`，可复制、可发手机、可新开浏览器、可局域网访问、刷新后仍定位同一赛事。

### 12.2 公共页面禁止出现的控件（本轮已落实）

`RankingsPage` / `KnockoutPage` 含管理端写操作，Public 复用时必须屏蔽，因此新增 `readOnly`：

* 屏蔽：Demo 模拟完成小组赛、补录小分、人工裁定 / 撤销裁定、录入大比分、生成淘汰赛签表、季军赛录分、指向管理页的链接；
* 保留：排名表、并列状态说明、签表结构、季军/名次排位、最终名次；
* 未复制任何排名 / 淘汰赛推进 / 比分 / 阶段判断算法，全部仍由原页面与后端承担。

### 12.3 报名入口的 legacy 状态

`/public/t/:tid/register` 已建立，复用现有 `RegisterPage`，并在页面上方显示明确的 legacy 提示条：

> 当前报名入口仍是 V0.2 行为：提交后直接进入正式参赛名单，没有「待审核 → 管理员确认入赛」流程。

本轮**没有**：设计 Registration schema / API、伪造 `registration_enabled` 字段、把 `addPlayer` 包装成 V0.3 最终方案。切换等待 A 轨正式 Registration contract。

导航中的「报名」入口固定保留：在缺少 `registration_enabled` 权威字段的前提下，不自行发明显隐规则。

## 13. production 静态托管实现

### 13.1 架构

```text
浏览器（PC / 手机）
      │  http://127.0.0.1:8000  或  http://<LAN-IP>:8000
      ▼
FastAPI（单进程 uvicorn --host 0.0.0.0 --port 8000）
      ├── /api/*            → 原有业务 router（不变）
      ├── /api/health       → {"status":"ok"}
      ├── /openapi.json /docs /redoc → FastAPI 自带（先注册，不被覆盖）
      ├── /assets/*         → frontend/dist/assets（StaticFiles）
      └── 其他 GET/HEAD     → frontend/dist/index.html（SPA fallback）
```

production 运行期**不需要 Vite**，也不需要目标机器安装 Node（dist 预构建）。

### 13.2 三个关键实现决策

1. **SPA fallback 注册在所有 API router 之后**（`main.py` 末尾调用），保证不覆盖已注册端点。
2. **`/api/*` 在路径匹配阶段被排除**（`SpaFallbackRoute.matches` 返回 `Match.NONE`），而不是在 handler 里返回 404。
   这是本轮修掉的一个真实回归，见 17.1。
3. **`dist` 不存在时退化为 API-only 模式**：`install_static_hosting()` 返回 `False` 且不注册任何路由，
   只记一条 INFO 日志。因此开发环境未执行 `pnpm build` 时，`import app.main` 与全部业务 API 均正常。

`/assets/*` 使用 `StaticFiles` 而非手写实现，直接获得路径逃逸防护、ETag 与正确 MIME。
dist 根下其他真实文件（`favicon.svg` 等）走 `resolve_dist_file()`，该函数拒绝越界路径与目录。
缺失的构建资源返回 404（而不是 index.html），避免浏览器报 MIME 错误。

### 13.3 CORS

未改动。仍为 `["http://localhost:5173", "http://127.0.0.1:5173"]`。
production 前后端同源 `:8000`，不依赖 CORS，因此没有为 LAN 改成 `*`。

## 14. LAN 启动脚本实现

`start_pingpong.ps1`（`start_demo.ps1` 保留为开发/Demo 双服务模式，未改动）：

```text
1. 定位项目根目录（按脚本自身位置，与调用目录无关）
2. 检查 Python
3. 检查 / 创建 backend\.venv
4. 检查 / 安装 backend\requirements.txt
5. 检查 frontend\dist
     不存在 → 有 Node/pnpm 则执行 production build
     不存在且无 Node → 明确报错并给出构建命令（不静默失败）
     -SkipBuild 时 → 直接失败并给出构建命令
6. 检查端口（默认 8000，可用 -Port 覆盖）
7. uvicorn --host 0.0.0.0 --port <Port>
8. 等待 /api/health 200（最多 40 次）
9. 额外探测 / 是否返回 SPA（确认单服务生效）
10. 枚举并打印私网 IPv4
11. 可用 -NoBrowser 关闭自动打开浏览器
```

### 14.1 LAN IP 处理

保留 RFC1918 私网地址：`192.168.x.x`、`10.x.x.x`、`172.16–31.x.x`。
排除：`127.x.x.x`、APIPA `169.254.x.x`、非 `Preferred` 状态地址。
多个私网地址**全部列出**并提示逐个尝试，不硬编码、也不猜唯一网卡。

本机实测输出（含一张 VirtualBox 虚拟网卡，脚本按设计全部列出）：

```text
局域网访问（手机与电脑需在同一 Wi-Fi/局域网）：
   http://192.168.56.1:8000    [以太网 2]
   http://192.168.68.150:8000  [WLAN]
   （检测到多个私网地址：请逐个尝试，脚本无法可靠判断哪张网卡连通手机所在网络）
```

### 14.2 脚本明确不做的事

不申请管理员权限、不改 Windows 防火墙、不结束其他进程、不暴露公网、不改系统网络配置。
若手机打不开，只输出排查提示（防火墙放行 Python「专用网络」）。

### 14.3 开发模式的注意点

开发期一旦执行过 `pnpm build`，`http://127.0.0.1:8000/` 也会开始返回**构建产物**（而非 Vite 页面）。
这是单服务托管的预期行为，不影响 `start_demo.ps1` 的 5173 开发流程：
开发时仍应访问 **5173**（由 Vite 提供 HMR，并代理 `/api` 到 8000）。
`8000` 只作为 production / LAN 入口，以及 API 直连入口。

## 15. 测试

### 15.1 命令与结果

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `backend> python -m pytest` | **758 passed, 30 skipped, 2 warnings** |
| 后端基线（改动前） | 同一命令（stash 后实测） | 722 passed, 30 skipped, 2 warnings |
| 本轮新增测试 | `pytest tests/test_static_hosting.py` | 36 passed |
| 前端回归测试 | `frontend> pnpm test` | **13 passed**（PR #44 review 后新增） |
| 前端构建 | `frontend> pnpm build` | 通过（`tsc` 无错误，66 modules，dist 生成） |

* failed = 0
* skipped = 30（与改动前一致，均为既有 skip）
* warning = 2（与改动前**完全相同**，未新增任何项目级 warning）
* 新增测试 36 例，全部集中在后端；未引入任何前端测试框架。

> 后续（PR #44 review 后）补充了最小前端测试设施，见 15.3。

### 15.2b 前端测试设施（PR #44 review 后新增，最小集）

原 D2 未引入前端测试框架。reviewer 要求为 Public 路由加回归保护，故补充**最小**设施：

| 文件 | 作用 |
| --- | --- |
| `frontend/vitest.config.ts` | 仅设置 `environment: 'jsdom'`；build 仍走 `vite.config.ts`，互不影响 |
| `frontend/src/__tests__/PublicRoutes.test.tsx` | Public 路由 tid 来源回归测试（13 例） |
| `frontend/package.json` | 新增 `test: vitest run` 与 devDependencies |

新增 devDependencies：`vitest@^3.2.7`、`jsdom`、`@testing-library/react`、`@testing-library/dom`。

* 刻意**未**引入 Playwright / Cypress / 任何 E2E 框架；
* `vitest` 固定 `^3.2.7`：vitest 4.1+ / 5.x 的 peer 要求 Vite ≥6，而本仓库仍用 Vite 5.4.11；
* 测试源码不进生产包：除 `__tests__` 外，`src` 中无任何 `vitest` / `@testing-library` 引用（已验证）。

### 15.2 新增测试覆盖（`backend/tests/test_static_hosting.py`）

1. `/api/health` 仍返回 JSON；
2. 未知 `/api/*` 保持 API 语义 404，不被 SPA fallback 吞掉；
3. `/api`、`/api/`、`/openapi.json`、`/docs`、`/redoc` 不被 SPA 覆盖（docs 关闭时保持 JSON 404）；
4. `dist` 存在时 `/` 返回前端入口，且带 `no-cache`；
5. 深链接 `/public/t/1/live`、`/public/t/12/schedule`、`/public/t/12/register`、`/console`、`/orderbook` 返回 SPA；
6. HEAD 深链接同样返回 SPA；
7. `/assets/*` 与 dist 根静态文件可访问且 MIME 正确；缺失资源 404 且不返回 HTML；
8. POST 前端路径返回 405 且不是 HTML；PUT `/api/*` 返回 JSON 4xx；
9. `dist` 不存在时 API-only 模式不 crash、前端路径返回 404；
10. 路径穿越（`../`、`assets/../../secret.txt`、`..\secret.txt`）无法逃出 dist；
11. **回归护栏**：catch-all 对 `/api/*` 的匹配结果必须是 `Match.NONE`。

测试使用 `tmp_path` 构造 dist，不依赖开发者机器的绝对路径，跨平台。

## 16. 手工验收结果

### 16.1 已实际验证

| 项 | 结果 |
| --- | --- |
| 开发模式双服务（FastAPI 8000 + Vite 5173）未被破坏 | ✅ 后端 8000 正常，Vite 配置与 `start_demo.ps1` 未改动 |
| `pnpm build` | ✅ 通过，生成 `frontend/dist` |
| `.\start_pingpong.ps1`（以 `-Port 8123 -NoBrowser` 实测全流程） | ✅ 依赖检查 → dist 检查 → 端口检查 → 启动 → health OK → SPA OK → 打印地址 |
| 端口占用分支 | ✅ 明确报错退出（exit 1），未自动杀进程 |
| PC 访问 `http://127.0.0.1:8000` | ✅ 200，返回 SPA（含 `id="root"`，`Cache-Control: no-cache`） |
| Public 深链接刷新不 404 | ✅ `/public/t/1/live`、`/live`、`/schedule`、`/rankings`、`/bracket`、`/champion`、`/register` 全部 200 返回 SPA |
| `/assets/*.js`、`/assets/*.css` | ✅ 200，`application/javascript` / `text/css` |
| 缺失资源 `/assets/nope.js` | ✅ 404，不返回 HTML |
| `/api/health` | ✅ 200 JSON |
| `/api/does-not-exist`、`/api/nope` | ✅ 404 JSON（未被 SPA 吞掉） |
| 不存在的 API 端点（回归用例）`POST /api/tournaments/1/team-ties/1/score` | ✅ 404 JSON（修复前被错误变成 405） |
| `/openapi.json`、`/docs` | ✅ 200，未被 SPA 覆盖 |
| 旧 V0.2 链接 `/rankings?tid=1`、`/journey?tid=1`、`/team-ties`、`/bigscreen` | ✅ 200 返回 SPA |
| 启动脚本 LAN IP 枚举 | ✅ 正确列出 `192.168.56.1` 与 `192.168.68.150`，排除全部 APIPA `169.254.*` |

### 16.2 当前环境无法验证（不虚报 PASS）

| 项 | 状态 |
| --- | --- |
| **LAN 二机实测（第二台手机/电脑打开 `http://<LAN-IP>:8000`）** | ⛔ **LAN 二机实测待人工现场验证**（本环境无第二台设备） |
| Windows 防火墙是否放行手机入站 | ⛔ 待人工验证（脚本按设计不修改防火墙） |
| React 路由在 360/375/390/430px 的真实触摸与视觉验收 | ⛔ 待人工浏览器验收（已按这些断点实现响应式 CSS，但未做真机截图验证） |
| Public 页面与后端真实赛事数据联调（真实 tid 的实况/排名/签表内容） | ⛔ 本轮只验证了路由与 HTML 交付；业务数据展示依赖真实赛事，待人工用真实 tid 验收 |
| 多手机同时读实况、手机重复点击不双写 | ⛔ 属 Day 3 手机录分范围 |

## 17. 本轮发现与修复的问题

### 17.1 【已修复，重要】SPA catch-all 把 API 404 变成 405

**现象**：加入 `/{full_path:path}` catch-all 后，`tests/test_team_runtime.py::test_runtime_api_end_to_end` 失败——
不存在的 `POST /api/tournaments/{tid}/team-ties/{tie}/score` 从 **404 变成 405**。

**原因**：`/{full_path:path}` 对任何路径都是 `Match.PARTIAL`，而 Starlette 只要看到「路径匹配、方法不匹配」
就返回 **405 Method Not Allowed**。catch-all 因此劫持了 API 命名空间的 404 语义。

该 404 并非无关紧要：测试正是用它证明「不存在直接改对抗比分的接口，避免两个真相源」。

**修复**：新增 `SpaFallbackRoute(APIRoute)`，在**路径匹配阶段**对 `/api` 与 `/api/*` 返回 `Match.NONE`，
让请求继续走到 Starlette 默认 404，与未安装托管时完全一致。并新增回归护栏测试锁定该行为。

> 注意：本版本 FastAPI（0.141.1）的 `api_route()` **不支持** `route_class_override` 参数，
> 因此该路由直接以 `SpaFallbackRoute(...)` 实例追加到 `app.router.routes`。

### 17.2 【已修复】catch-all handler 参数未标注类型导致 422

`spa_fallback(request)` 未标注 `Request` 类型时，FastAPI 会把它当成必填 query 参数，所有 fallback 请求返回 422。
已改为 `spa_fallback(request: Request)`。

### 17.2b 【已修复，PR #44 P1】PublicRoutes 在 `<Routes>` 外读取 descendant `:tid`

**现象**：把 `/public/t/12/live` 这条链接复制到另一台设备/新浏览器打开，页面显示的却是
`localStorage.activeTournamentId` 里那一场赛事，而不是 URL 里的 `12`。

**原因**：`PublicRoutes()` 在自身**顶层**调用了 `useTidFromPath()`（内部是 `useParams()`），
但 `/public/t/:tid` 是它下面 `<Routes>` 声明的 **descendant** Route。
`useParams()` 只能读到**当前组件已经处于的**匹配 Route 及祖先 Route 的参数，读不到后代 Route 的 param。

实测（渲染真实 `App`）该层调用得到：

```text
DEBUG PublicRoutes tid= undefined params= {}
```

于是 `tid` 变成 `undefined` 传给 `BigScreenPage` 等旧页面，旧页面按
`prop > ?tid= > localStorage` 兼容链回退到 `localStorage`。

**修复**：把 tid 解析下沉到 **已匹配的 child route adapter**（`PublicLiveAdapter` 等），
`PublicRoutes()` 顶层不再读取任何 param。非法 `:tid` 时 adapter 只渲染「链接不可用」提示，
**不渲染** legacy 页面，因此不会回退到 `?tid=` 或 localStorage。

**回归保护（两层）**

1. `frontend/src/__tests__/PublicRoutes.test.tsx`（`pnpm test`，13 例）：渲染真实 `App`，
   只替换网络层。断言落在**页面自身发起**的请求（`/dashboard`、`/groups`、`/rankings`、`/knockout`）上。
   > 注意：`PublicLayout` 头部也会请求 `/api/tournaments/:tid`，而它本来就在匹配上下文内、
   > 任何情况下都用正确 tid。若只断言它，即使 Public 路由漏传 tid 也会「通过」——
   > 这个坑在编写测试时真实踩到过，故断言必须针对页面自身的请求。
2. 端到端（真实 headless Chrome + 真实后端 + 用服务端 access log 取证）：
   先用 `localStorage=99` 的持久化 profile 打开 `/`，再打开 `/public/t/12/live`。
   修复前：run2 请求 `tournaments/99` 30 次、`tournaments/12/dashboard` 0 次（FAIL）；
   修复后：run2 只请求 `tournaments/12`（31 次）与 `tournaments/12/dashboard`（5 次），`99` 0 次（PASS）。

### 17.3 【已确认非本项目代码问题】venv uvicorn 出现父/子解释器路径不一致

实测 `backend\.venv\Scripts\python.exe -m uvicorn` 会产生两个进程：父进程为 venv 解释器，
子进程（实际监听端口的那个）`ExecutablePath` 显示为基础解释器
`C:\Users\...\Python310\python.exe`。

已核实**不影响正确性**：该 venv `pyvenv.cfg` 为 `include-system-site-packages = false`，
而线上 `/openapi.json` 返回的 schema 版本特征与 venv 的 fastapi 0.141.1 一致
（系统解释器装的是 fastapi 0.128.0，行为特征不同）。判定为 Windows venv 转发器的 `sys.executable` 显示怪癖。

`start_pingpong.ps1` 沿用与 `start_demo.ps1` 相同的 `& $venvPy -m uvicorn` 形式。
（实测用 `Scripts\uvicorn.exe` 会多一层包装进程，故未采用。）

### 17.4 【已修复】`start_pingpong.ps1` 必须带 UTF-8 BOM

本机 `pwsh` 实为 **Windows PowerShell 5.1**，它把**无 BOM** 的 `.ps1` 按 ANSI 读取，
导致脚本内中文（注释与提示）被破坏并触发伪语法错误。
仓库既有 `start_demo.ps1` 带 UTF-8 BOM 正是为此。新脚本已按同一约定写入 BOM，并在 PS 5.1 下复验解析通过。

## 18. 已知 warning（基线技术债，本 D2 不处理）

以下两条 warning 在 Day 2 开始前即已存在，改动前实测为 2 条，改动后仍为同样的 2 条：

| Warning | 来源 |
| --- | --- |
| `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` | `fastapi/testclient.py` → Starlette TestClient |
| `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated` | `starlette/testclient.py` → AnyIO alias |

**本 D2 不处理**：未升级 FastAPI / Starlette / AnyIO / httpx，未修改 dependency contract。

## 19. 尚未完成事项

| 项 | 归属 |
| --- | --- |
| Public 报名切换到 V0.3 `Registration(pending)` 契约 | 等 A 轨 Registration contract |
| `registration_enabled` 权威字段驱动的报名入口显隐 | 等 A 轨 |
| `AdminLayout` 的「打开 Public 页面」仍指向 `/bigscreen?tid=` | 等 C/A 冻结 route shell 后改为 `/public/t/:tid/live`（本轮未动 C 的文件） |
| MobileScorePage 手机录分 | D Day 3 |
| Public 页面真机视觉验收（360/375/390/430px） | 待人工 / E 轨 |
| LAN 二机实测 | 待人工现场验证 |
| 二维码入口 | P1，Day 5/Day 7 |
| `orderbook` 纳入 Public 主导航 | 本轮按 Day 1 设计不作为 P0 |

## 20. 对 A / C 轨的接口依赖

| 轨道 | 依赖内容 | 本轮处理 |
| --- | --- | --- |
| A 轨 | Registration schema/API、`registration_enabled`、登录态、401/403、EVENT_ADMIN 授权 | **未实现任何认证**；Public 按免登录设计；报名沿用 legacy 复用并显式标记 |
| A 轨 | `/admin/*` route tree 与 AuthGuard | 未提前实现任何 `/admin/*` 登录保护，未重写 A 轨 Auth route tree |
| C 轨 | `AdminLayout`、管理端 IA、桌面视觉体系 | 未创建第二套 AdminLayout，未复制侧栏，未改 C 的文件；PublicLayout 独立命名空间 `.pub-*` |
| C 轨 | 「打开 Public 页面」入口改指向新路由 | 记录为待办，等 C 给 route shell |
| B 轨 | V0.3 ScoreRequest / 异常结果 contract | 未实现任何比分业务；Day 3 才做 |

`App.tsx` 只增加了一个提前返回分支（Public 路由入口），Public 全部路由收敛在 `PublicRoutes.tsx`，
以降低与 A/C 轨的合并冲突面。

## 21. Day 3 前置条件

1. **A 轨 Registration contract**：schema、API、`registration_enabled`、pending → confirmed 流程与错误码；
2. **B 轨 Score contract**：V0.3 `ScoreRequest` 最终字段、同次提交 games 契约、异常结果契约、改分错误码；
3. **C/A 轨 Admin route shell 冻结**：确认 `/admin/t/:tid/matches/:matchId/score` namespace 与 AuthGuard 用法；
4. Day 3 只做手机录分 UI（`MobileScorePage`）+ 固定底部提交 + 防重复提交 + 可读错误展示；
5. Day 3 仍**不得**复制比分合法性、小分一致性、W.O. 计排名等任何业务规则，全部消费后端契约；
6. Day 3 需真机/窄屏验收 360–430px，并补 LAN 二机实测。
