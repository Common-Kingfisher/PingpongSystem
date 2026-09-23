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

---
---

# D 轨 Day 3 实施结果

分支：`feat/d-day3-mobile-score`（**整个 Day 3 只开这一个 PR**）
Day 3 起点基线：`origin/master@c900e71`（含 PR #41 B 轨比分契约、PR #43 C 轨登录骨架、PR #44 D2 Public/LAN/production）

本节只追加 Day 3 实施记录，第 1–21 节（Day 1/Day 2）内容未改动。

## 22. Day 3 交付结论

| 项 | 结果 |
| --- | --- |
| 手机录分页面 | ✅ `/admin/t/:tid/matches/:matchId/score` |
| 正常比分（大比分必填） | ✅ 复用既有 score API，无第二套写入通道 |
| 逐局小比分（可选） | ✅ 默认收起；不录时请求**不含** `games` 字段 |
| 异常结果 | ✅ 复用当前 `ResultType`，页内二次确认，不伪造逐局小比分 |
| 小屏/触控适配 | ✅ 360 / 375 / 390 / 430px 真实 Chrome 实测（见 28） |
| 防重复提交 | ✅ 按钮 disabled + ref 同步锁；连点 3 次服务端只落 1 条 RECORD |
| 错误展示 | ✅ 422 / 409 / 401 / 403 / 404 / 网络分别给可读文案，输入不清空 |
| Auth 最终接线 | ⛔ **未接线**：A 轨认证契约仍未进入 master（见 27） |

**结论：PASS WITH BLOCKER**（唯一 blocker = Auth 最终接线，其余全部完成并实测）。

## 23. 本轮实际修改文件

### 23.1 新增

| 文件 | 目的 |
| --- | --- |
| `frontend/src/pages/MobileScorePage.tsx` | 手机录分页主体：大比分录入、可选逐局小比分、异常结果、错误展示、防重复提交、完成态 |
| `frontend/src/pages/MobileScorePage.css` | 手机优先样式（`.ms-*` 独立命名空间），360–430px 无横向滚动，底部 sticky 提交 |
| `frontend/src/MobileScoreRoutes.tsx` | 路由表 + route adapter + **Auth 接线边界**（未来 AuthGuard 唯一挂载点） |
| `frontend/src/mobileScore.ts` | 载荷构造与展示 helper（严格按 OpenAPI contract，**不含任何比分业务算法**） |
| `frontend/src/routeParams.ts` | 路由参数解析（纯函数，不读 localStorage / `?tid=`） |
| `frontend/src/__tests__/MobileScorePage.test.tsx` | 前端自动化测试 28 例 |
| `backend/day3_mobile_score_acceptance.ps1` | 后端契约层验收：A–F 六场景，22 项断言 |
| `backend/scripts_mobile_viewport_check.mjs` | 360/375/390/430 布局事实测量（真实 Chrome CDP） |
| `backend/day3_mobile_e2e.mjs` | 真机视口端到端：输入 → 提交 → 服务端核对 |
| `backend/day3_e2e_fixture.py` | 造干净的 A/C/D 三场景赛事 |
| `backend/day3_longname_fixture.py` | 造“超长中文名 + 超长 ASCII 名”赛事（小屏破版验收数据） |

### 23.2 修改

| 文件 | 目的 | 改动性质 |
| --- | --- | --- |
| `frontend/src/App.tsx` | `/admin/*` 提前返回 `MobileScoreRoutes`，不渲染管理端 App Shell | +8 行，未动现有路由 |
| `frontend/src/pages/ConsolePage.tsx` | 待进行比赛卡片增加「手机录分」入口（仅双方就绪时） | +11 行 |
| `frontend/src/index.css` | `.waiting-match-card > .waiting-match-mobile` 让入口独占一行 | +2 行 |

**未修改**：`api.ts`、`ScoreSheet.tsx`、`generated/openapi.d.ts`、`docs/openapi-v0.2.json`、
后端任何业务代码、排名/晋级算法、`AdminLayout`、`PublicLayout`、`start_pingpong.ps1`、CORS。

## 24. 路由与赛事上下文

```text
/admin/t/:tid/matches/:matchId/score      ← 单场比赛的手机录分页（canonical）
```

> **路径变更记录**：Day 3 初版实现的是 `/admin/t/:tid/score/:matchId`。
> Reviewer 指出 route ownership / namespace 问题后，最终统一为
> `/admin/t/:tid/matches/:matchId/score`（与 Day 1 冻结稿一致，`matches/:matchId/score`
> 的资源层级也更清楚）。PR 未合并，因此**没有**为了兼容 PR 内旧实现保留两套路由。

### 24.1 Route ownership：D 轨只拥有这一条精确 path

`/admin` 命名空间的**总体所有权属于 A/C 轨**（AdminLayout / Login / AccessState /
AuthGuard / RequireTournamentAccess 及其他管理端 route）。因此：

* `App.tsx` **不再**使用 `pathname.startsWith('/admin/')`，改用与 D 轨 route 表共用的
  `isMobileScoreRoutePath()`（内部为 react-router 的 `matchPath(…, { end: true })` 完整匹配）；
* `MobileScoreRoutes` **只**声明 canonical 一条 route，**没有** `/admin/*` catch-all，
  未知 `/admin/...` 一律交还 A/C 的管理端 route tree。

`tid` 与 `matchId` **只来自路由 path**，由 `MobileScoreRoutes.tsx` 中已匹配的 route adapter
解析后作为 props 传给页面。因此：

* 页面不读 `localStorage.activeTournamentId`，也不读 `?tid=`；
* 非法 / 缺失 param 时只渲染「链接不可用」，**不回退**到任何别的赛事或比赛（Day 2 的 PR #44 P1 同款约束）；
* 比赛通过 `GET /api/tournaments/:tid/matches` 后在结果里按 `matchId` 定位，
  因此“打开的比赛必然属于 URL 里的赛事”，不存在跨赛事错读。

`App.tsx` 中的接线只有一条入口分支，与 Public 分支同级；具体路由收敛在 `MobileScoreRoutes.tsx`，
以降低与 A/C 轨的合并冲突面。

## 25. 后端契约（实际使用面）

页面**只**调用既有 API，没有新增任何写入通道：

| 用途 | 调用 | 契约来源 |
| --- | --- | --- |
| 赛事规则（局制/每局分） | `GET /api/tournaments/{tid}` | `TournamentOut.games_to_win` / `points_to_win` |
| 定位比赛 | `GET /api/tournaments/{tid}/matches` | `MatchOut` |
| 选手名回退 | `GET /api/tournaments/{tid}/players` | `PlayerOut.name` |
| 分组名（阶段展示） | `GET /api/tournaments/{tid}/groups` | `GroupOut.name` |
| 球台名 | `GET /api/tournaments/{tid}/dashboard` | `TableWithMatch.name`（仅当比赛已排台时才请求） |
| **写入比分** | `POST /api/matches/{matchId}/score` | `ScoreRequest` → `MatchOut` |

请求体严格使用 `ScoreRequest` 的真实字段：

```jsonc
{
  "player_a_score": 2, "player_b_score": 1,          // 正常比赛必填
  "games": [{"side_a_score": 11, "side_b_score": 7}], // 可选；不录时整体省略（不是 []）
  "result_type": "NORMAL",                            // 或 FORFEIT / WALKOVER / NO_SHOW / DISQUALIFIED
  "forfeit_entry_id": 102,                            // 异常结果必填
  "note": "…", "operator_name": "…", "request_id": "<uuid>"
}
```

**没有**发明 `gameScores` / `roundScores` / `abnormal` 之类的字段；前端测试对这点有显式断言。

异常结果只使用当前 `ResultType` 枚举（`backend/app/models.py::ResultType`）：
`NORMAL / FORFEIT / WALKOVER / NO_SHOW / DISQUALIFIED`。
**没有**新增或删除任何后端枚举值，也没有替服务端决定行政比分 ——
小组赛弃权时服务端会写入排名用行政比分（`games_to_win:0`），页面把它单独标注为
「排名用行政比分」，与现场逐局比分明确区分。

`request_id` 复用 `api.ts::submitScore()` 既有机制：同一次提交的重试复用同一个 UUID，
因此网络中断后的重试不会双写（后端返回同一结果）。

## 26. 前端**不**实现的业务规则

按 Day 1 冻结的边界，页面只做交互级提示，以下全部交给后端：

* 合法比分判定（每局分制、平分延长、胜局数上限）→ 后端 `_validate_game` / `_validate_scores`；
* 逐局小比分与大比分一致性 → 后端 `_validate_normal_score_payload`；
* winner 计算与淘汰赛推进 → 后端 `knockout_service`；
* 改分下游影响保护 → 后端 `revise_score`（Day 3 **不使用**改分接口，见 30）。

前端**保留**的检查只有肉眼可见的四类，且都只用于“省掉一次必然失败的往返”：
空值、非整数、两边相同、小比分半局。任何被后端拒绝的载荷，页面都原样展示服务端文案。

> **review 返工（见 33）**：初版还额外做了两处“按本赛事局制”的判定，已删除 ——
> `buildNormalScorePayload()` 不再比较 `Math.max(a, b)` 与 `games_to_win`；
> `bumpScore()` 不再用 `games_to_win` 当步进上限、也不再自动改写另一方比分。
> 因此三局两胜里填 `1:0` 会真的发出请求，由后端返回 422。

## 27. Auth 集成状态（明确边界，不含“later”）

> ⚠️ **本节记录的是 Day 3 当时（`master@c900e71`）的状态，已被后面的合入取代。**
> A 轨认证与赛事授权契约**已经合入 master**（`master@81827b3`），
> `POST /api/matches/{id}/score` 现在由 `require_tournament_write` 保护。
> 当前状态请看 **第 48 节（第四轮：同步 master + Auth/赛事授权真实集成验收）**。

**当时状态：未接线。**

截至 Day 3 基线 `master@c900e71`：

* 后端**没有**任何 auth router / session / `/auth/me` / 权限依赖：
  `backend/app/main.py` 只注册业务 routers，没有 auth 相关模块；
* C 轨的 `AdminLayout` / `LoginPage` / `AccessStatePage` 等**展示层**已合入 master，
  但当时的认证工作包与 C 轨 Guard 分支**都还没有进入 master**。

因此在 Day 3 内**没有**实现：token、localStorage 登录态、临时用户系统、第二套权限判断。
这些都属 A 轨契约，自己造会与正式认证直接冲突。

接线点已经按最终形态固定，且**唯一**：`MobileScoreRoutes.tsx::AdminScoreGuardBoundary`。
契约合入后只需就地替换为：

```tsx
<RequireAuth>
  <RequireTournamentAccess tid={tid}>
    <MobileScorePage tid={tid} matchId={matchId} />
  </RequireTournamentAccess>
</RequireAuth>
```

接线前必须同时满足三个条件（缺一不可）：

1. `GET /auth/me` 与 401/403/404 错误 DTO 已在 master；
2. `RequireAuth` / `RequireTournamentAccess` 已在 master（C 轨）；
3. **服务端本身拒绝未授权调用** —— 前端 Guard 只改善 UX，服务端才是唯一安全边界。

页面侧已经能正确处理 401/403/404 的展示（见 29），因此接线后不需要改页面。

## 28. 测试与验收结果（真实执行）

### 28.1 自动化回归

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `backend> python -m pytest` | **758 passed, 30 skipped, 2 warnings** |
| 后端基线（Day 3 前） | 同一命令 | 722 → D2 后 758；本轮**未新增后端测试**，数量与 D2 基线一致 |
| 前端全量 | `frontend> pnpm test` | **41 passed**（28 新增 + 13 既有 Public 路由回归） |
| 前端类型 | `frontend> pnpm exec tsc --noEmit` | 通过（exit 0） |
| 生产构建 | `frontend> pnpm build` | 通过（71 modules，dist 生成） |
| 契约一致性 | `frontend> pnpm contract:check` | 通过（`generated/openapi.d.ts` 无 diff） |

warning 数（2）与改动前完全一致，均为既有基线技术债（见 18）。

### 28.2 前端自动化测试覆盖（`MobileScorePage.test.tsx`，28 例）

* **路由（5 例）**：请求全部命中 URL 里的 tid；URL 与 `localStorage` 冲突时 URL 胜；
  比赛不属于该赛事时明确报错且不去别的赛事找；非法 param 不发任何赛事请求；
  不渲染管理端 11 个导航入口。
* **正常比分（5 例）**：只录大比分时 payload **不含 `games`**；提交后重新拉取真实 Match；
  空值 / 平局时前端提示且不发请求；**胜方局数不符合本赛事局制时不阻断，请求照样发给后端
  并展示服务端 detail**；**步进按钮只做 ±1 与下限 0，不受 `gamesToWin` 限制、也不改动另一方**。
* **可选小比分（3 例）**：大比分 + 完整小比分同次提交且使用 contract 字段；
  半局被拦下；删除局后重新提交不携带被删除的局。
* **异常结果（6 例）**：`FORFEIT` / `NO_SHOW` / `WALKOVER` / `DISQUALIFIED` 四种类型
  各自断言 `result_type` + `forfeit_entry_id` 正确且**不带 games**；未选异常方不提交；
  完成态显示「李四弃权」而不是 `2:1`。
* **错误与防重复（6 例）**：422 业务文案原样展示且**不清空**输入；409 冲突文案；
  网络失败提示检查局域网且不清空输入；**POST 成功但刷新失败时必须报“比分已保存 + 刷新失败”，
  不得报“本次未保存”，且 score POST 只有一次**；连点 3 次只发 1 次请求且按钮 disabled / 显示“提交中…”；
  被拒绝后可再次提交（锁正确释放）。
* **操作人（2 例）**：填写后随请求提交并记忆；不填时不发送 `operator_name`。
* **已结束比赛（1 例）**：只展示结果并指向赛事管理端，不重开改分流程。

### 28.3 真机尺寸验收（真实 Chrome 153 + 真实后端，`scripts_mobile_viewport_check.mjs`）

对 **正常名字**与**超长名字**两套真实数据各跑一遍，**60 项检查全部 PASS**（每断点 15 项 × 4 断点）：

| 断点 | 无横向滚动 | 大比分输入 | 步进按钮 | 提交按钮 | 小比分输入 | 删除按钮 | 名字不破版 | 错误文字可见 | 步进不动另一方 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 360px | ✅ scrollWidth=360 | ✅ 64px | ✅ 64px | ✅ 58px | ✅ 52px | ✅ 44px | ✅ | ✅ | ✅ |
| 375px | ✅ scrollWidth=375 | ✅ 64px | ✅ 64px | ✅ 58px | ✅ 52px | ✅ 44px | ✅ | ✅ | ✅ |
| 390px | ✅ scrollWidth=390 | ✅ 64px | ✅ 64px | ✅ 58px | ✅ 52px | ✅ 44px | ✅ | ✅ | ✅ |
| 430px | ✅ scrollWidth=430 | ✅ 64px | ✅ 64px | ✅ 58px | ✅ 52px | ✅ 44px | ✅ | ✅ | ✅ |

超长数据：赛事名 32 字、姓名 `张三丰·欧阳锋·令狐冲·东方不败` 与
`AlexandertheGreatWangXiaoming`。

### 28.4 端到端验收（真实 Chrome 390×844 + 真实后端，`day3_mobile_e2e.mjs`）

在手机视口里真的用键盘输入、真的点按钮，然后回服务端核对事实，**21 项全部 PASS**：

| 场景 | 断言 |
| --- | --- |
| A 只录大比分 | 页面显示「比分已保存」；服务端 `FINISHED`、`2:1`、`games=[]`（无伪造逐局） |
| A 连点 3 次 | 服务端**只有 1 条 RECORD 审计** |
| C 非法小比分（汇总 0:2 vs 大比分 2:1） | 页面显示 `服务端未接受本次比分：逐局小比分与大比分不一致`；服务端状态未变；输入未清空 |
| B 局制不符（2 局制填 1:0） | 前端无本地赛制提示；请求到达后端；展示 `服务端未接受本次比分：大比分胜局数必须为 2`；服务端状态未变 |
| D 异常结果（B 方弃权） | 提交前出现确认条；服务端 `result_type=FORFEIT`、`forfeit_entry_id` 正确、`games=[]`；页面显示「弃权」并标注「排名用行政比分」 |

### 28.5 后端契约层验收（`day3_mobile_score_acceptance.ps1`，22 项 PASS）

`[PASS] A accepted`、`A match FINISHED`、`A big score stored`、`A no fabricated per-game scores`、
`E same request_id returns 200 (idempotent replay)`、`E only one RECORD audit row`、
`E same request_id with different payload rejected (409)`、`B per-game scores stored correctly`、
`C rejected by server (422 逐局小比分与大比分不一致)`、`C match untouched after rejection`、
`C draw rejected 422`、`C inconsistent games rejected 422`、`D result_type=FORFEIT`、
`D forfeit_entry_id stored`、`D no per-game scores created`、`D bad forfeit side rejected 422`、
`F rejected 409` 等。

### 28.6 LAN / production 兼容（PR #44 能力未被破坏）

| 项 | 结果 |
| --- | --- |
| `http://127.0.0.1:8000`（等价 8099）深链接 `/admin/t/:tid/matches/:matchId/score` | ✅ 200 返回 SPA |
| `http://192.168.3.32:8099/api/health` | ✅ `{"status":"ok"}` |
| 局域网地址打开录分页并渲染 | ✅ 四个断点全部 PASS（页面请求发向当前服务器，非 localhost） |
| 相对 API 路径 | ✅ 页面与 `api.ts` 全部使用 `/api/...`，未写死 host / 端口 |
| CORS | ✅ **未改动**（仍只有 5173 两个来源），未为 LAN 放宽成 `*` |
| `start_pingpong.ps1` | ✅ 未修改 |

> 说明：本轮用本机私网地址 `192.168.3.32` 验证「非 localhost 来源可正常打开并录分」，
> 满足“请求发向当前服务器”这一条。**真机二机实测仍需人工**（本环境无第二台设备），见 31。

## 29. 错误处理矩阵（页面实际行为）

| 后端结果 | 页面文案 |
| --- | --- |
| 422 | `服务端未接受本次比分：<后端 detail>`（如「逐局小比分与大比分不一致」「比赛不允许平局」） |
| 409 | `当前比赛状态不允许这样操作：<后端 detail>` |
| 404 | `比赛不存在或已不属于本赛事：<后端 detail>` |
| 401 | `登录状态已失效，请重新登录后再提交。（<后端 detail>）` |
| 403 | `当前账号没有本赛事的录分权限：<后端 detail>` |
| 5xx | `服务端出错，本次比分未保存：<后端 detail>` |
| 网络失败 / 断网 | `网络连接失败，请检查局域网连接后重试`，且**不清空**已输入数据 |

所有业务错误都显示服务端真实 `detail`，不存在统一显示“提交失败”的兜底。

## 30. 改分边界（Day 3 不做）

Day 3 的核心是**现场首次录分**。页面在比赛已 FINISHED 时：

* 只展示真实结果（正常比分 + 逐局小比分，或异常结果 + 行政比分标注）；
* 明确提示「如需修改结果，请前往赛事管理端」；
* **不提供**任何第二次录分 / 改分入口，也不调用 `POST /api/matches/{id}/revise-score`；
* 现有的改分能力仍在 `ConsolePage` + `ScoreSheet`（桌面端）中，未被改动。

因此 Day 3 没有扩大范围，也没有与 B 轨的改分影响保护产生第二套实现。

## 31. 已知边界（只列真实未完成项）

| 项 | 状态 |
| --- | --- |
| **Auth 最终接线** | 后端已完成并实测（第 48 节）；**前端 shell 仍等 C 轨** `RequireAuth` / `RequireTournamentAccess`。接线点已在 `MobileScoreRoutes.tsx::AdminScoreGuardBoundary` 固定。D 轨未引入任何临时认证 |
| **LAN 真机二机实测** | ⛔ 未做：本环境无第二台设备。已用本机私网地址 `192.168.3.32` 验证非 localhost 来源可正常打开并录分 |
| **iOS Safari / Android Chrome 真机触摸** | ⛔ 未做：本轮为 Chrome 153 headless + CDP 视口测量与真实输入，非真机。视口尺寸、触摸目标高度、无横向滚动均已实测 |
| **键盘弹出后的可视区域** | ⛔ 未在真机验证：提交按钮为 sticky bottom + `env(safe-area-inset-bottom)`，headless 无法模拟软键盘遮挡 |
| **逐局小比分“局数自动跟随大比分”** | 已知交互简化：展开时按当前大比分推导行数（`a+b` 行，上限 `2×games_to_win-1`），之后改大比分不会自动重排行数，由裁判手点「再加一局」 |
| **团体赛（TEAM）录分** | 不在 Day 3 范围：本页只处理普通 `Match`，团体盘比分仍走既有 `TeamTiePage` |
| **`pnpm test` 的 `cleanup()`** | 既有 `PublicRoutes.test.tsx` 未显式 cleanup（vitest 未开 globals，自动 cleanup 不注册）。它每个用例只渲染一次因而未暴露问题；新测试文件已显式 `cleanup()`。未顺手改既有测试文件以免扩大 diff |

## 32. 本地复现验收的完整步骤

```powershell
# 1. 后端（独立验收库，避免污染 demo.db）
cd backend
$env:DEMO_DB_PATH='data\d3_acceptance.db'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8099

# 2. 契约层验收（另开一个终端）
powershell -File .\day3_mobile_score_acceptance.ps1

# 3. 前端构建产物 + 起一个开了 CDP 的 Chrome
cd ..\frontend; pnpm build
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
    --remote-debugging-port=9333 --user-data-dir=$env:TEMP\d3chrome about:blank

# 4. 端到端 + 小屏测量
cd ..\backend
.\.venv\Scripts\python.exe .\day3_e2e_fixture.py          # 打印 TID / MATCH_A / MATCH_C / MATCH_D / MATCH_B
node .\day3_mobile_e2e.mjs http://127.0.0.1:8099 <TID> <MATCH_A> <MATCH_C> <MATCH_D> <MATCH_B>
.\.venv\Scripts\python.exe .\day3_longname_fixture.py     # 打印超长名字赛事路径
node .\scripts_mobile_viewport_check.mjs http://127.0.0.1:8099 /admin/t/<tid>/matches/<mid>/score
```

---
---

# D 轨 Day 3 Review 返工记录

分支与 PR 未变：`feat/d-day3-mobile-score` / **PR #45**（review 返工继续追加在同一个 PR，未开新 PR、未合并）。
本节只记录本轮两处 review 问题的修复，不改变 22–32 节的交付范围。

## 33. 修复：POST 成功但刷新失败被报成“提交失败”

### 33.1 问题

`MobileScorePage.tsx::runSubmit()` 初版把 `await api.recordScore(...)` 与 `await load()`
放在**同一个 try/catch**：

```text
POST /score 成功落库 → 重新 GET Match 时网络失败 → catch → 显示“网络连接失败…”
```

此时比分**事实上已经保存**，却告诉裁判“没保存”，会诱导重复提交。这是错误状态。

### 33.2 修复

拆成两段，并在 POST 成功后立即记录服务端返回的真实 `MatchOut`：

```ts
let savedMatch: Match
try {
  savedMatch = await api.recordScore(match.id, payload)   // ① 只有这里失败才算“未保存”
  setSavedMatch(savedMatch)
} catch (error) {
  setFormError(/* 422/409/401/403/404/网络 文案，输入不清空 */)
  return
}

try {
  await load()                                            // ② 刷新失败 ≠ 提交失败
} catch {
  setRefreshWarning('比分已保存，但最新状态刷新失败，请重新加载页面确认。')
}
```

* **A. score POST 失败**：仍按 `describeSubmitError` 展示，覆盖 422 / 409 / 401 / 403 / 404 / 网络错误，输入不清空。
* **B. POST 成功但刷新失败**：新增 `savedMatch` / `refreshWarning` 两个状态，用 POST 返回的真实
  `MatchOut` 作为已保存结果兜底展示完成态，并给出醒目的 `.ms-refresh-warning` 提示条：
  「**比分已保存** …… 请重新加载页面，核对最新比赛状态；不要重复提交。」
  该提示条刻意**不是**红色错误样式，避免诱导重复提交。
* 成功刷新时页面仍以刷新后的 match 为准（不拿旧响应覆盖真实状态）：兜底仅在
  `refreshWarning !== null && savedMatch.status === 'FINISHED'` 时启用。
* 未改后端、未新增第二条 API。

### 33.3 回归测试

新增 1 例（`MobileScorePage.test.tsx`）：`POST /score → 200` 成功，随后所有 `/api/*` GET 网络失败。断言：

* `scorePosts.length === 1`（score POST 只有一次）
* 页面出现「比分已保存」
* 页面出现「最新状态刷新失败」与「请重新加载」
* 存在 `.ms-refresh-warning` 提示条，且**不存在** `.ms-error`
* `document.body.textContent` **不包含**「网络连接失败」「本次比分未保存」「服务端出错」
* 完成态下不存在「确认提交大比分」按钮（不可能再触发第二次提交）

## 34. 修复：删除前端对 `gamesToWin` 的业务合法性裁决

### 34.1 删除的内容

| 位置 | 删除的行为 |
| --- | --- |
| `mobileScore.ts::buildNormalScorePayload` | `if (Math.max(big.a, big.b) !== gamesToWin)` 阻断提交（连同该入参一起移除） |
| `MobileScorePage.tsx::bumpScore` | 用 `gamesToWin` 当步进上限（`Math.min(gamesToWin, base + delta)`） |
| `MobileScorePage.tsx::bumpScore` | 一方达到 `gamesToWin` 时**自动改写另一方**比分（`otherApply(String(gamesToWin - 1))`） |
| `MobileScorePage.tsx::describeNormalHint` | 提示「本赛事 N 局制：胜方大比分应为 N」这条按赛制推导的结论 |

这些都属于「本场比分是否合法」的业务判断，等于在手机端建立第二套合法比分算法；
Day3D 的冻结边界是「移动端负责交互，后端负责规则」，且 Day4 调整赛制/规则时前端不应同步复制规则。

### 34.2 保留的交互检查

必填、必须为非负整数、双方大比分明显相同的提示、小比分“只填一边”的半局提示、
防重复提交、数字键盘 / `inputMode` / 可点区域等纯交互约束 —— 全部保留。

步进按钮仍为 `+1 / −1` 且下限 `0`，但不再受 `gamesToWin` 限制，也不改动另一方。

### 34.3 现在的行为

三局两胜里填 `1:0`（业务上非法）会**真的发出请求**：

```text
POST /api/matches/{id}/score  →  backend scores.py  →  422「大比分胜局数必须为 2」
  →  手机端展示服务端真实 detail
```

### 34.4 回归测试

* 新增 1 例：胜方局数不符合本赛事局制时**不阻断**，断言请求确实发出（`scorePosts.length === 1`）且展示服务端 detail。
* 新增 1 例：步进按钮连点 4 次得到 `4`（不被 2 局制截断），另一方仍为空（不被自动改写），下限仍为 `0`。
* 定向 E2E 新增 scenario B：真实 Chrome 里填 `1:0` 提交 → 前端无本地赛制提示 → 服务端 422 文案上屏 → 服务端状态未变。

## 35. 本轮验证结果

| 项目 | 结果 |
| --- | --- |
| `frontend> pnpm test` | **41 passed**（原 39 + 本轮净增 2） |
| `frontend> pnpm exec tsc --noEmit` | 通过（exit 0） |
| `frontend> pnpm build` | 通过 |
| `frontend> pnpm contract:check` | 通过（未改 OpenAPI，无 diff） |
| `backend> python -m pytest` | 本轮未改后端，沿用 **758 passed, 30 skipped, 2 warnings** |
| `day3_mobile_score_acceptance.ps1` | **22 PASS / 0 FAIL** |
| `day3_mobile_e2e.mjs`（真实 Chrome 390×844） | **21 PASS / 0 FAIL**（新增 scenario B 三例） |
| `scripts_mobile_viewport_check.mjs`（360/375/390/430，含超长名字） | **60 PASS / 0 FAIL**（每断点 15 项，其中新增“步进不动另一方”1 项） |

## 36. Auth 边界未变

本轮**没有**触碰 token、Session、AuthContext、localStorage 登录、backend auth 或临时 Guard。
`MobileScoreRoutes.tsx::AdminScoreGuardBoundary` 仍是唯一接线点，PR #45 描述中的
`Auth final wiring blocked by A track contract` 状态不变。

---
---

# D 轨 Day 3 Reviewer 第二轮返工：路由切换的陈旧响应竞态

分支与 PR 未变：`feat/d-day3-mobile-score` / **PR #45**。本轮只处理 Reviewer 指出的 **1 个 P1**，
未扩大 Day3D 范围，未触碰 backend / OpenAPI / Auth。

## 37. 缺陷

React Router 在同一路由 pattern 下切换 `:tid` / `:matchId` 时，`MobileScorePage`
**不会 remount**（`MobileScoreRoutes` 里没有 `key`），只有 props 变化。此时 `load()` 内部自己
`setData(...)`，于是：

```text
打开 /admin/t/A/matches/X/score（关键 GET 悬挂）
  → 同 SPA 导航到 /admin/t/B/matches/Y/score，B/Y 先完成并正确显示
  → 释放 A/X 旧请求，旧响应晚返回 → setData(A/X) 覆盖页面
```

最危险的后果是「页面显示 A/X，但 `match.id` 已经是 Y」→ **录的分可能写到别的比赛上**。
原实现的 `let active = true` 只保护 `load().catch(...)`，管不到成功路径的 `setData`。

## 38. 修复

### 38.1 `load()` 变成纯取数函数

```ts
type LoadResult =
  | { ok: true; data: LoadedData }
  | { ok: false; failure: LoadFailure }

const load = useCallback(async (): Promise<LoadResult> => { /* 只调 API + 组装结果 */ }, [tid, matchId])
```

`load()` 内**不再出现任何** `setData` / `setFailure` / `setSavedMatch` / `setRefreshWarning`。
`match` 不存在时也改为 `return { ok: false, failure: { kind: 'match-missing', ... } }`，
由调用方在确认 generation 有效后才写 `setFailure`。

### 38.2 generation 是新鲜度的唯一依据

新增 `loadGenerationRef`，并把它作为**唯一**的陈旧响应判据：

* 每次进入新的加载上下文 `++loadGenerationRef.current`；
* effect cleanup 里作废当前 generation（只作废一次）；
* 所有异步写入统一经过 `applyLoadResult(generation, result)`，或显式比较
  `generation !== loadGenerationRef.current`。

⚠️ 同时**移除了 effect 里的 `let cancelled` 闭包标志**。原因是它会让 generation 判断永远
短路、测试也跟着变成空测试：作者实测把 generation 机制整体禁用后全部用例仍然通过
（见 39.2）。现在只保留一套判断，任何一套被改坏都会被测试抓到。

### 38.3 提交后的 refresh 复用同一套防护

`runSubmit()` 在开头捕获 `const generation = loadGenerationRef.current`，并在每个写 state 的
分支前检查 `isStale()`：

| 位置 | 陈旧时行为 |
| --- | --- |
| POST 成功树 | 不写 `savedMatch`（只释放 `inFlight`） |
| POST 失败 catch | 不写 `formError` |
| refresh 结果 | 经 `applyLoadResult(generation, …)`，不写 `data` / `failure` |
| refresh 失败 catch | 不写 `refreshWarning` |
| finally | 不写 `submitting` / `inFlight` |

因此「旧比赛 POST 成功但刷新失败」**不会**在新比赛页面上显示“已保存 / 刷新失败”提示。

### 38.4 路由切换时重置表单与提交状态

因为是同组件 props 变化（不 remount），切换比赛时会清空上一场的输入与提示
（`scoreA/B`、`games`、`note`、`mode`、`confirmAbnormal`、`formError`、`savedMatch`、
`refreshWarning`、`submitting`），并重置 `inFlight` 锁 —— 否则上一场未归零的锁会卡死
新页面的首次提交。`operatorName` 刻意保留（它是裁判身份，已持久化在 localStorage）。

### 38.5 上一轮语义保持

* POST 失败才算“本次比分没有保存”（422/409/401/403/404/网络，输入不清空）；
* POST 成功 + refresh 失败 = **已保存**，显示“比分已保存，但最新状态刷新失败，请重新加载页面确认”；
* 该提示条仍不是红色错误样式，不诱导重复提交。

## 39. 回归测试

新增 `frontend/src/__tests__/MobileScoreRouteRace.test.tsx`（3 例），使用 deferred promise
真实制造竞态，并且**在同一次 render / 同一个 `MemoryRouter` 内**导航（不重新 mount 测试 App）：

1. **A/X 请求晚返回时页面仍显示 B/Y，且提交只命中 Y**
   悬挂 A 的 `GET /api/tournaments/A/matches` → 同 SPA 导航到 B/Y → B/Y 正常显示 →
   释放 A 的旧请求 → 断言页面仍是 B/Y、`TOURNAMENT_A.name` / `AAA选手一` / `AAA选手二`
   都不出现、且没有变成“比赛不存在” → 填分提交 →
   `expect(scorePostPaths).toEqual([`/api/matches/${MATCH_Y}/score`])`
   并断言绝不含 `/api/matches/${MATCH_X}/score`。
2. **A/X 旧请求晚返回时不得把已显示 B/Y 的页面改成“比赛不存在”**
   A 的悬挂请求释放后返回**不含 X** 的列表，覆盖 `match-missing` 也必须在 generation 保护内。
3. **B/Y 显示期间不出现上一场的错误态或“已保存/刷新失败”提示**
   覆盖 `failure` / `savedMatch` / `refreshWarning` 的跨路由污染，并断言全程零提交。

路由使用**生产环境的真实 adapter**（`MobileScoreRoutes.tsx::AdminScoreAdapter`，本轮为测试
导出），测试只在外层注入一个导航探针（录分页本身刻意不含任何跳转链接）。

### 39.2 非空测试验证（避免“测试永远通过”）

把 generation 机制临时整体禁用（effect 不递增 + cleanup 不作废）后重跑：

```text
× A/X 请求晚返回时页面仍显示 B/Y，且提交只命中 Y   → Unable to find "TID-B-THIRTY-TWO 赛事"
× A/X 旧请求晚返回时不得把已显示 B/Y 的页面改成“比赛不存在” → expected <h1></h1> to be null
× B/Y 显示期间不出现上一场的错误态或“已保存/刷新失败”提示 → Unable to find "TID-B-THIRTY-TWO 赛事"
Tests  3 failed | 41 passed (44)
```

恢复修复后 44 例全绿 —— 说明这 3 例确实在守护该竞态，而不是恒真断言。

## 40. 本轮验证结果

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 前端全量 | `frontend> pnpm test` | **44 passed**（3 files：41 + 本轮新增 3） |
| 前端类型 | `frontend> pnpm exec tsc --noEmit` | 通过（exit 0） |
| 生产构建 | `frontend> pnpm build` | 通过 |
| 契约检查 | `frontend> pnpm contract:check` | 通过（未改 OpenAPI，无 diff） |
| 后端全量 | `backend> python -m pytest` | 本轮未改后端，沿用 **758 passed, 30 skipped, 2 warnings** |
| 契约层验收 | `day3_mobile_score_acceptance.ps1` | **22 PASS / 0 FAIL** |
| 端到端 | `day3_mobile_e2e.mjs`（真实 Chrome 390×844） | **21 PASS / 0 FAIL** |
| 小屏 | `scripts_mobile_viewport_check.mjs`（360/375/390/430，含超长名字） | **60 PASS / 0 FAIL** |

---
---

# D 轨 Day 3 Reviewer 第三轮返工：Route ownership 与 canonical URL

分支与 PR 未变：`feat/d-day3-mobile-score` / **PR #45**。本轮只处理 Reviewer 的 1 个 P1，
未改 backend / OpenAPI / Auth，未扩大 Day3D 范围。

## 41. 缺陷：D 轨抢占整个 `/admin/*`

```tsx
// App.tsx（错误实现）
if (pathname.startsWith('/admin/')) return <MobileScoreRoutes />
// MobileScoreRoutes 内还声明了
<Route path="/admin/*" element={<AdminScoreInvalidLink />} />
```

任何 `/admin/...` 都先被 D 轨接管；A/C 后续接入 `AdminLayout` / `Login` / `AccessState` /
`AuthGuard` / `RequireTournamentAccess` 及其他管理端 route 时会被这里截断。

## 42. 修复

### 42.1 canonical URL 统一

```text
/admin/t/:tid/matches/:matchId/score        （最终，canonical）
```

与 Day 1 冻结稿一致，`matches/:matchId/score` 的资源层级更清楚。PR 未合并且**没有**保留第二套路由。

### 42.2 `App.tsx`：精确匹配入口

```tsx
// 与 D 轨 route 表共用同一个判断，避免两处字符串漂移
if (isMobileScoreRoutePath(pathname)) return <MobileScoreRoutes />
```

`isMobileScoreRoutePath()`（在 `MobileScoreRoutes.tsx` 内导出）内部是 react-router 的
`matchPath({ path: MOBILE_SCORE_ROUTE_PATH, end: true }, pathname) !== null` ——
**完整匹配**，不自写字符串解析，也**不再**出现 `startsWith('/admin/')`。

### 42.3 `MobileScoreRoutes.tsx`：只声明自己拥有的 route

```tsx
export const MOBILE_SCORE_ROUTE_PATH = '/admin/t/:tid/matches/:matchId/score'
// 路由表只声明这一条；没有 /admin/* catch-all
<Route element={<AdminScoreAdapter />} path={MOBILE_SCORE_ROUTE_PATH} />
```

未知 `/admin/...` 一律交还 A/C 的管理端 route tree；D 轨不再替管理端决定“未知 admin 路径显示什么”。

### 42.4 非法 param 仍走 adapter 错误页

`/admin/t/abc/matches/345/score`、`/admin/t/12/matches/xyz/score` 的 route pattern 本身正确，
仍进入 `AdminScoreAdapter`，由 `parseRouteTournamentId()` / `parseRouteMatchId()` 判为非法 →
显示「链接不可用」，不回退 query / localStorage，也不发任何 API 请求。
错误页示例地址已更新为 `/admin/t/12/matches/345/score`。

### 42.5 `ConsolePage` 入口

```tsx
to={`/admin/t/${tid}/matches/${m.id}/score`}
```

只改 URL，未动比赛筛选、排台、桌面端录分、改分与 Match 状态。

## 43. Route ownership 回归测试（`MobileScoreRouteOwnership.test.tsx`，36 例）

### 43.1 为什么不用“外层 `/admin/*` 哨兵”

两种写法都实测为**假测试**，记录在此避免重犯：

1. 在外层 `<Routes>` 放 `/admin/*` 哨兵“证明交给外层”：react-router 按 route 打分而不是声明顺序，
   `/admin/*` 比 `*` 更具体，会**先于 `App`** 命中 → `App` 根本不被挂载，测试测不到它的分支；
2. 只断言“页面里没有 D 的内容”：D 若被误挂载但自身 route 表已收窄，它会渲染一棵**空**树，
   同样“什么都没出现”，断言恒真。

### 43.2 实际使用的两个可观测判据

* **入口判定**：对 `App.tsx` **实际调用**的 `isMobileScoreRoutePath()` 做决策表断言
  （命中 2 条 / 不命中 15 条，含 `/admin/events`、`/admin/login`、`/admin/t/12/settings`、
  `/admin/t/12/matches`、`/admin/t/12/matches/345/score/extra`、`/admin/t/12/score/345`、
  `/admin`、`/admin/` 等），并额外做**源码级护栏**：`App.tsx` 必须包含
  `isMobileScoreRoutePath(pathname)`、且（剥掉注释后）不含 `startsWith('/admin/')` 与 `/admin/*`。
* **D 轨 route 表**：单独渲染 `MobileScoreRoutes`，断言
  canonical 路径渲染录分页、而 7 条非 canonical `/admin/...` 路径下**渲染结果为空**
  （既不显示录分页、也不显示 D 的「链接不可用」）且**零 API 请求**。

### 43.3 校准（两种回归都实测会失败）

```text
回归 1：入口改回 pathname.startsWith('/admin/')
  → 1 failed（App.tsx 源码级护栏拦下）          79 passed

回归 2：D 轨 route 表加回 /admin/* catch-all
  → 7 failed（7 条非 canonical 路径都渲染出了 D 的页面/错误页） 73 passed

恢复修复后：80 passed
```

## 44. RouteRace 测试保持有效

`MobileScoreRouteRace.test.tsx` 未删除、未弱化，只把 URL 迁移到 canonical 形式
（`/admin/t/A/matches/X/score` → `/admin/t/B/matches/Y/score`），竞态手法不变：
deferred promise 悬挂 A/X → 同 SPA 导航 B/Y → B/Y 显示 → 释放 A/X → 页面仍是 B/Y →
提交只命中 `Y`。前一轮的“非空测试验证”结论同样保持有效。

## 45. P-01 核验（LAN 只是 Deployment）

* production 业务代码仍然只使用相对 `/api/...`：`frontend/src` 下**没有** `http://localhost`、
  `http://127.0.0.1`、`http://192.168`、固定 backend hostname 或 `:5173`（本轮复核，见 46 报告）；
* 测试/验收脚本中的 `http://127.0.0.1:8099` 属允许范围；
* 未开发公网 / Tunnel / Caddy / 域名 / QR / LAN IP 自动发现。

## 46. 依赖

`pnpm install --frozen-lockfile` 通过，`package.json` 与 `pnpm-lock.yaml` **未改动**
（本 PR 未新增任何依赖）。

## 47. 本轮验证结果

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 前端全量 | `frontend> pnpm test` | **80 passed**（4 files） |
| 前端类型 | `frontend> pnpm exec tsc --noEmit` | 通过（exit 0） |
| 生产构建 | `frontend> pnpm build` | 通过 |
| 契约检查 | `frontend> pnpm contract:check` | 通过（未改 OpenAPI，无 diff） |
| 依赖锁定 | `frontend> pnpm install --frozen-lockfile` | 通过，无 lockfile 变更 |
| 后端全量 | `backend> python -m pytest` | 本轮未改后端，沿用 **758 passed, 30 skipped, 2 warnings** |
| 契约层验收 | `day3_mobile_score_acceptance.ps1` | **22 PASS / 0 FAIL** |
| 端到端 | `day3_mobile_e2e.mjs`（真实 Chrome 390×844，canonical URL） | **21 PASS / 0 FAIL** |
| 小屏 | `scripts_mobile_viewport_check.mjs`（canonical URL） | **60 PASS / 0 FAIL** |

---
---

# D 轨 Day 3 第四轮返工：同步最新 master + Auth/赛事授权真实集成验收

分支与 PR 未变：`feat/d-day3-mobile-score` / **PR #45**。本轮把 PR45 的开发基线从
`master@c900e71` 前移到最新 master，并让全部 Day3 验收走**真实认证**。

## 48. 同步 master

| 项 | 值 |
| --- | --- |
| merge 前 PR head | `7c5b23b6ec19e4fee88d1192e73db16c939b2ff8` |
| 合入的 master | `81827b3ea9c81b3c4c54078f5c45c95d0faac19b`（PR #46 D3A 协作管理员与异常结果接口） |
| merge commit | `52190f6` |
| 冲突 | **无**（`git merge origin/master --no-edit` 一次通过） |

为什么没冲突：master 自 `c900e71` 以来**完全没有改 `frontend/src/`**（`git diff --name-only c900e71 origin/master -- frontend/src` 为空），
A 轨改动全部落在 `backend/`、`docs/`、`docs/openapi-v0.2.json`。D 轨的全部产物
（MobileScorePage / MobileScoreRoutes / mobileScore.ts / routeParams.ts / 测试 / 验收脚本）
在 merge 后逐项复核仍在位，`isMobileScoreRoutePath`、`loadGenerationRef` 等不变量未回退。

## 49. 当前 Auth 契约（合并后实际状态）

来源：`docs/A2.7_AUTH_CONTRACT_DELIVERY.md`、`backend/app/routers/auth.py`、
`backend/app/auth_dependencies.py`、`backend/app/dependencies.py`、
`backend/app/routers/scores.py`、`docs/openapi-v0.2.json`。

### 49.1 认证入口与凭据

| 项 | 契约 |
| --- | --- |
| 登录 | `POST /api/v1/auth/login`（`mode: "browser" \| "bearer"`） |
| 退出 | `POST /api/v1/auth/logout`（幂等，成功删除 Cookie） |
| 当前用户 | `GET /api/v1/auth/me` |
| 改密 | `POST /api/v1/auth/change-password` |
| 浏览器凭据 | `pp_session` Cookie：`HttpOnly` / `SameSite=Lax` / `Path=/`，HTTPS 追加 `Secure`；**browser 模式不返回 `access_token`** |
| 脚本凭据 | `Authorization: Bearer <opaque token>`（bearer 模式返回 `access_token`） |
| 凭据冲突 | 同一请求同时带 Cookie 与 Bearer 且指向不同会话 → 401 `AUTH_REQUIRED` |

### 49.2 赛事写权限

```text
POST /api/matches/{match_id}/score
    ↓ Depends(require_tournament_write)     # WRITE_TOURNAMENT_ROLES = OWNER/ADMIN/OPERATOR
    ↓ 赛事归属来自 tournaments.owner_user_id 或有效的 tournament_admins 授权
```

### 49.3 错误语义（页面必须尊重）

| 场景 | 状态 | `detail.code` | `detail.message` |
| --- | --- | --- | --- |
| 未登录 | 401 | `AUTH_REQUIRED` | 请先登录 / 登录状态已失效，请重新登录 |
| 无该赛事授权 / 跨赛事资源 | 404 | `RESOURCE_NOT_FOUND` | 资源不存在 |
| 系统角色不足 | 403 | `FORBIDDEN` | 需要…权限 |

跨赛事统一 404 是**防资源枚举**设计：不得改写成“你没有某赛事权限”。

## 50. MobileScoreRoutes 的 Auth 状态更新

`AdminScoreGuardBoundary` **保持为唯一接线点**，未新增任何临时认证。

判断依据（实测）：`RequireAuth` / `RequireTournamentAccess` / `AuthContext` 在
`origin/master` 上**不存在**，在 C 轨自己的 `feat/v03-c-d3-settings` 分支上也还没有
（`frontend/src/pages/LoginPage.tsx` 仍是展示层）。因此属于"情况 B"：
后端契约已完成，前端 shell 依赖 C 轨。

代码注释已改写为当前事实（后端已落地、录分写入已受保护、前端仍等 C 轨、接线只剩一个前置条件）。

## 51. 共享 `api.ts` 错误解析修复

### 51.1 问题

后端错误体现在有两种形态：

```jsonc
{ "detail": "逐局小比分与大比分不一致" }                              // 旧式业务错误
{ "detail": { "code": "AUTH_REQUIRED", "message": "请先登录" } }     // A 轨结构化错误
```

`api.ts::request()` 只认字符串 detail，因此 401 在页面上退化成 `请求失败 (401)`，
裁判看不到真实原因。

### 51.2 修改（transport 层一次解析，页面复用）

* `parseErrorBody()` 同时兼容字符串 detail 与结构化 `{code,message}`；
* `ApiError` 扩展为 `status / message / code?`（可选字段，未改造整个前端异常体系）；
* 页面**不**自己解析 response、**不**自己判断 `detail.code`。

`MobileScorePage` 只在必要时加前缀，message 一律用服务端原文：

| 后端 | 页面显示 |
| --- | --- |
| 401 `AUTH_REQUIRED`「请先登录」 | `请先登录后再提交：请先登录` |
| 404 `RESOURCE_NOT_FOUND`「资源不存在」 | `服务端拒绝了本次录分：资源不存在`（**不**翻译成权限推断） |
| 403 `FORBIDDEN` | `当前账号没有该操作的权限：…` |
| 422 业务错误 | 前缀 + 服务端原文（不变） |

新增 `frontend/src/__tests__/ApiErrorParsing.test.tsx`（6 例）直接测 transport 层。

## 52. 验收脚本如何认证化

| 脚本 | 变化 |
| --- | --- |
| `day3_auth_client.py`（新增） | 真实 Bootstrap → 真实建 EVENT_ADMIN → 真实登录（Bearer / Cookie 两种模式）；**不含任何绕过** |
| `day3_auth_acceptance.py`（新增，替代 `.ps1`） | 30 项断言，全部经真实认证的 HTTP |
| `day3_e2e_fixture.py` / `day3_longname_fixture.py` | 先真实登录再建赛事（创建赛事本身需要 `require_event_admin`），并打印浏览器 E2E 用的账号密码 |
| `day3_cdp_auth.mjs`（新增） | Node 侧共享 CDP 客户端；让**浏览器自己**登录建立 `pp_session` |
| `day3_mobile_e2e.mjs` | 先匿名验证后端拒绝，再真实浏览器登录后跑完整流程 |
| `scripts_mobile_viewport_check.mjs` | 测量前先建立真实会话，避免只测到 401 页面尺寸 |

明确**没有**做：关闭鉴权、dependency override、`TEST_MODE`、"本机/局域网就放行"、
直接调 service 层代替 HTTP 写操作、把 bearer token 塞 localStorage 冒充浏览器登录。

## 53. 真实 Auth 场景验收结果

`day3_auth_acceptance.py`：**30 PASS / 0 FAIL**

| 场景 | 结果 |
| --- | --- |
| A 已登录 + 有写权限（OWNER） | 200，`FINISHED`，`2:1` 落库，`games=[]` |
| B 匿名 POST score | **401 `AUTH_REQUIRED`**「请先登录」，比赛仍 `WAITING` 且比分未写入 |
| B4 匿名写操作（新增选手） | 401 `AUTH_REQUIRED` |
| B2/B3 匿名只读（比赛列表 / 排名） | 200 —— 这是 master 冻结的 Public 只读契约，不是漏洞 |
| C 已登录但无该赛事授权 | **404 `RESOURCE_NOT_FOUND`**「资源不存在」，比赛状态不变，响应不泄露资源存在性 |
| D 只录大比分 | 200，`games=[]` |
| E 大比分 + 完整小分 | 200，逐局 `11-7 / 9-11 / 11-8` 正确 |
| F 非法比分 | 422 三次（一致性 / 平局 / 局制），被拒后状态未变 |
| G 异常结果（弃权） | 200，`result_type` / `forfeit_entry_id` 落库，无逐局小分 |
| H 同一 request_id 重放 | 200 幂等，只有 1 条 RECORD；换载荷 409 |
| I 已结束比赛再次录分 | 409 |
| J `GET /api/v1/auth/me` | 200，返回当前用户 |

## 54. C/D 文件所有权

保持：D 轨本轮只改自己的文件（`MobileScorePage.tsx` 的错误文案映射、
`MobileScoreRoutes.tsx` 的 Auth 注释），以及共享 `api.ts` 的 transport 解析（第 51 节，属
"一次解析、所有页面复用"，不是页面级 Auth 逻辑）。

`ConsolePage.tsx` 本轮**未改动**。C 轨拥有的桌面端错误分层 / `pageError` / `actionError` /
`scoreError` / 桌面改分二次确认 / `ScoreSheet` 桌面体验 / 赛事设置，D 轨一律未碰。

## 55. P-01 核验

* `frontend/src` 生产代码仍只使用相对 `/api/...`；grep `http://|localhost|127.0.0.1|192.168|:5173|:8000|:8099` **无命中**；
* 认证与授权**不依赖任何 IP 网段**：身份 = Cookie/Bearer → User → Owner/TournamentAdmin；
  代码中不存在 `if private_ip: allow` / `if LAN: skip auth` 之类分支（A 轨契约第 6 节同款约束）；
* 未开发公网 / Tunnel / Caddy / 域名 / QR / LAN 自动发现。

## 56. 本轮验证结果（重新执行，不沿用历史常数）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `backend> python -m pytest` | **860 passed, 30 skipped, 4 warnings** |
| OpenAPI 快照 | `backend> python export_openapi.py --check` | `OpenAPI snapshot is up to date` |
| 依赖锁定 | `frontend> pnpm install --frozen-lockfile` | 通过，`package.json` / `pnpm-lock.yaml` 无 diff |
| 前端全量 | `frontend> pnpm test` | **89 passed**（5 files） |
| 前端类型 | `frontend> pnpm exec tsc --noEmit` | 通过（exit 0） |
| 生产构建 | `frontend> pnpm build` | 通过 |
| 契约检查 | `frontend> pnpm contract:check` | 通过（generated 已按 master 的 OpenAPI 重新生成，见第 57 节） |
| 后端授权验收 | `day3_auth_acceptance.py` | **30 PASS / 0 FAIL** |
| 浏览器端到端 | `day3_mobile_e2e.mjs`（真实 Chrome 390×844 + 真实会话） | **31 PASS / 0 FAIL** |
| 小屏 | `scripts_mobile_viewport_check.mjs`（canonical URL + 真实会话） | **62 PASS / 0 FAIL** |

> 历史记录的 `758 passed` 是 Day3 初版基线，本轮已按实际结果更新为 **860 passed**；
> A2.7 报告中的 `835 passed` 也不是验收常数。

## 57. OpenAPI generated 漂移（机械重新生成）

master 更新了 `docs/openapi-v0.2.json`（新增认证 / 系统 / 赛事协作管理员接口），
但**没有**同步 `frontend/src/generated/openapi.d.ts`，因此 `pnpm contract:check` 在 master 上本身就是失败的。

D 轨用 `pnpm contract:generate` 机械重新生成，并**机械校验**（不是肉眼看）：

```text
contract schemas : 126     contract paths : 66
generated types  : 111     generated paths: 66
types NOT in contract (会表明是发明的): ['parameters', 'requestBody', 'responses']  ← 生成器自身的辅助键
contract paths missing from generated : []
generated paths not in contract       : []
```

即：`generated/openapi.d.ts` 完全来自已提交的 `docs/openapi-v0.2.json`，
**D 轨没有发明或手工编辑任何契约**（`contract:check` 现已通过）。

## 58. 本轮 commit

```text
52190f6  Merge remote-tracking branch 'origin/master' into feat/d-day3-mobile-score
593c118  fix(frontend): parse structured API error details
5f1eedb  fix(D-Day3): integrate mobile scoring with the landed auth contract
2cc2c49  chore(frontend): regenerate OpenAPI types from the committed contract
```

## 59. 剩余依赖

```text
Backend Auth and tournament authorization are integrated and verified.
The remaining frontend-shell dependency is C-track
RequireAuth / RequireTournamentAccess integration.
No temporary D-track authentication layer was introduced.
```

---

# D 轨 Day 4D 实施结果

> 本轮命令基线：`origin/master` = `2e57895985be8627f7531fee098afaeda8399d4d`
> （`feat(C轨-D3): 建立赛事规则设置骨架并收口Public入口 (#49)`）
> 分支：`feat/d-day4-public-format-lan`（Day4D 唯一 PR）
> 文档修订时间：2026-09-22

## 22. 本轮硬 Gate 与真实基线（先读这一节）

Day4D 的原始目标是「Public 排名 / 签表 / 实况适配多赛制」。开工前按冻结要求核查真实仓库，
结果为**前置 PR 未进入 master**，因此本轮按冻结规则执行「独立工作 + 不发明临时契约」。

| 检查项 | 真实结果 | 对 Day4D 的影响 |
| --- | --- | --- |
| PR #45（D 轨 Day3 手机录分，`feat/d-day3-mobile-score`） | **未进入 master**（branch tip `65c1034`，diff 29 files / +7616） | 按冻结要求**不**从 #45 分支续做 Day4D；Day4D 从 `origin/master` 新开分支，避免 Day3 / Day4 混成一个 PR。未自行 cherry-pick #45。 |
| PR #47（A 轨 D4 赛制配置落库，`feat/D4A赛制配置落库`） | **未进入 master**（branch tip `967ec15`，diff 13 files / +1270） | `TournamentOut.format_code` / `rule_config` / `rule_version` 在 master 上**不存在**，因此本轮不接线赛制判定。 |
| PR #48（B 轨 D4 Format Handler，`feat/d4b-format-handlers-and-draw-rules`） | **未进入 master**（branch tip `3443951`，diff 15 files / +983） | 同上：ROUND_ROBIN / SINGLE_ELIMINATION / GROUP_KNOCKOUT Handler 尚未落地。 |
| `frontend/src/PublicRoutes.tsx`、`PublicLayout.tsx`、`publicTournament.ts`、`pages/RankingsPage.tsx`、`pages/KnockoutPage.tsx`、`pages/BigScreenPage.tsx`、`api.ts`、`generated/openapi.d.ts` | 全部存在且结构与 Day 2 一致 | 复用而非重写。 |
| `start_pingpong.ps1`、`backend/app/static_hosting.py` | 均存在 | 只做缺口加固，未重写。 |
| master 上 `format_code` 的唯一出现位置 | `team_ties` / `TeamTieOut` / `RubberSkeletonRequest`（团体赛对抗赛制） | **不是**赛事级赛制字段，不能拿来当 `TournamentOut.format_code` 用（否则等于伪造契约）。 |

因此本轮**不做**、也不允许做的（明确留到 #47 / #48 进入 master 之后）：

* 不手写临时 `format_code` 字面量，不新建第二套 TS enum；
* 不用 `as any` 读取尚不存在的字段，不按 `stage` 名称或“有没有 group / knockout tree”反推赛制；
* 不复制 B 轨赛制判断，不写临时 API；
* 不把 `#47` / `#48` 分支 merge 进 Day4D 分支。

## 23. 本轮实际交付范围

在 Gate 允许的四项内完成：

1. **LAN / production 启动加固**（`start_pingpong.ps1`，见第 25 节）；
2. **Public 页面展示结构整理**：Public 只读视图不再把“返回首页”指向管理端 `/`；
   排名页在 Public 下改用中性标题「赛事排名」；
3. **「不适用 / 空态 / readOnly」组件逻辑**：新增 `PublicEmptyState` 组件，
   Public 排名页 / 签表页在“什么都还没有”时给出可读空态 + 回到本赛事可用视图的 CTA，
   且空态文案对三种赛制都成立（不推断赛制）；
4. **与现有契约无关的测试**：Public 空态 / 深链接 / 无管理入口回归测试（前端），
   以及“production frontend runtime 不得依赖固定地址”的部署策略测试（后端）。

## 24. 修改文件

### 24.1 新增

| 文件 | 作用 |
| --- | --- |
| `frontend/src/components/PublicEmptyState.tsx` | Public 只读空态卡：标题 + 说明 + 0..n 个 CTA。**不读取任何赛事字段**，不推断赛制。 |
| `frontend/src/components/PublicEmptyState.css` | 空态卡样式，手机优先（CTA ≥ 44px，≤430px 占满整行）。 |
| `frontend/src/__tests__/PublicViewStates.test.tsx` | 12 条回归：深链接空态、既有主链不退化、Public 无管理入口、未知子路径回实况、大屏 ENDED 展示。 |
| `backend/tests/test_deployment_address_policy.py` | 3 条部署策略测试：前端运行时无固定地址 / API 客户端只用 `/api/...` 同源相对路径 / 源码不引用带 hash 的构建产物名。 |

### 24.2 修改

| 文件 | 改动与理由 |
| --- | --- |
| `frontend/src/pages/RankingsPage.tsx` | ① 新增 `pageTitle`：`readOnly` 时用「赛事排名」，管理端仍是「小组排名」（不改 C 轨界面）；② 后端返回空排名时渲染 `PublicEmptyState` + 「查看签表」CTA，不再是一片空白；③ Public 只读时「返回首页」改为「返回实况」并指向 `/public/t/:tid/live`，不再把观众带进管理端 `/`。 |
| `frontend/src/pages/KnockoutPage.tsx` | ① 同上②③；② 把“本页什么都没有”时的旧文案「小组赛对阵尚未发布」（只对小组+淘汰赛成立）替换为中性空态 + 「查看排名」CTA；③ 小组赛未完成（`remaining > 0`）等既有分支保持原样，保证 V0.2 主链不退化。 |
| `frontend/src/pages/BigScreenPage.tsx` | 已结束、且本赛事**没有**淘汰赛签表时（例如循环赛：没有决赛，名次即最终成绩），展示后端发布的「赛事排名」；有签表的赛事仍走原有冠军 / 签表分支，行为不变。不计算名次、不补造冠军。 |
| `start_pingpong.ps1` | 见第 25 节。 |
| `docs/WORKSTREAM_D.md` | 本节。 |

**未改动**：`backend/app/static_hosting.py`（Day 2 实现已满足三条硬约束，深链接 / `/api` 语义 / dist 缺失降级均有既有测试覆盖）；
`ConsolePage` / `MobileScorePage` / `ScoreSheet` / `AdminLayout` 等管理端与录分文件（Day3 / C 轨边界）。

## 25. `start_pingpong.ps1` Day 4D 加固明细

| 现场问题 | 加固内容 |
| --- | --- |
| 多网卡（Wi-Fi + Ethernet + WSL + VPN + Hyper-V + VMware + Docker） | 新增 `Get-NetAdapterMap`：读取 `Get-NetAdapter` 的 `Virtual` / `Status` 元数据，但**只用于排序与标注，绝不删除候选地址**；`Get-NetAdapter` 不可用时退化为 `Test-VirtualAdapterName` 关键字降权。权重：1 = 物理且 `Up`，2 = 状态未知，3 = 虚拟/隧道或明确未连接。 |
| 多个私网地址 | 超过 1 个时明确提示「检测到多个局域网地址。请选择与比赛手机所在路由器同网段的地址。」；每个地址附带网卡名与连接状态，虚拟网卡附「（虚拟 / 隧道网卡）」。 |
| 网段 | 仍只保留 RFC1918：`192.168.x.x` / `10.x.x.x` / `172.16-31.x.x`，排除回环与 APIPA `169.254.x.x`。脚本只**发现并展示**真实地址，不假定 `192.168.50.10`。 |
| Public 示例里的赛事 id | 新增只读探测：优先 `-TournamentId` 参数；否则用 venv Python 以 `mode=ro` 只读打开本机 SQLite（尊重 `PINGPONG_DB_PATH` / `DEMO_DB_PATH`，默认 `backend/data/demo.db`）取最小真实赛事 id；**读不到就只展示 base URL**。绝不假定「赛事 id 永远是 12」，也不匿名调用需要登录态的 `GET /api/tournaments`。 |
| 启动输出 | 收口为「本机 / 局域网 / 手机使用（1-2-3 步）/ Public 示例」四段；Public 示例同时提示 `/live` 可换成 `/schedule`、`/rankings`、`/bracket`、`/champion`。 |
| 深链接 | 除 `/` 之外，新增 `/public/t/<tid>/live` 探测：必须 200 且返回 SPA（`id="root"`），证明刷新 / 直接粘贴链接不 404。 |
| 防火墙 | 只读提示：`Get-NetFirewallProfile` 在 `try/catch` 中读取，命中「启用且入站默认阻止」时打印配置文件名单；**不申请管理员权限、不新增/修改/删除规则、不关闭防火墙、不改网卡 IP / 路由器 / DNS**。 |
| 误判风险 | 明确写出「同一台电脑访问本机 LAN 地址不代表手机能访问（不经过防火墙入站路径），必须用真实手机验证」。 |

⚠️ **文件编码约束（Day 2 §17.4 的延续）**：本机 `pwsh` 实为 Windows PowerShell 5.1，会把**无 BOM** 的 `.ps1` 按 ANSI 读取。
修改 `start_pingpong.ps1` 后**必须**回写 UTF-8 BOM，否则中文提示会乱码甚至触发伪语法错误。
本轮已用 `[System.Management.Automation.Language.Parser]::ParseFile` 复验解析错误数 = 0，并确认首字节为 `EF BB BF`。

## 26. 部署灵活性（为切云服务器 / 公网域名预留）

* `frontend/src` 全量扫描结果：**0 处** `127.0.0.1` / `localhost` / `192.168.*` / `10.*` / `172.16-31.*` / `:8000` / `http(s)://`；
* `api.ts` 的每个请求路径都是同源相对路径 `/api/...`，因此同一份 production build：
  * 现场：`http://192.168.50.10:8000` → `/api/health` 同源；
  * 云服务器：`http://<云 IP>:8000` → 无需改代码；
  * 正式域名：`https://pingpong.example.com` → 天然变成 `https://pingpong.example.com/api/...`；
* 新增 `backend/tests/test_deployment_address_policy.py` 把这条约束变成**持续回归**：
  一旦有人把部署环境写进前端运行时源码，测试立即失败；
* 未实现（且本轮明确不做）：云服务器部署、公网穿透、DDNS、TLS 自动签发、mDNS / 自建 DNS、路由器配置程序。

## 27. LAN 验收（真实执行）

真实运行 `.\start_pingpong.ps1 -SkipBuild -NoBrowser`（先 `pnpm build`），实测结果：

| 项 | 结果 |
| --- | --- |
| production 单服务 | FastAPI 单进程同时提供 `/api/*` 与 `frontend/dist` SPA（`/api/health` OK，`/` 返回 SPA） |
| 本机 | `http://127.0.0.1:8000` → `/` 200 SPA、`/api/health` 200、`/public/t/1/live` 200 SPA |
| LAN IP | `http://192.168.68.150:8000`（WLAN · Up）→ `/api/health` 200、`/public/t/1/live` 200 SPA |
| 多网卡 | 同时检测到 `192.168.68.150 [WLAN · Up]` 与 `192.168.56.1 [以太网 2 · Up]（虚拟 / 隧道网卡）`，已提示选择同网段地址 |
| 真实 tid | 脚本从本机库读到赛事 id = 1（**不是** 12），并打印 `http://192.168.68.150:8000/public/t/1/live` |
| SPA 深链接 | `/public/t/1/live`、`/public/t/1/rankings`、`/public/t/1/bracket` 均 200 + SPA，刷新不 404 |
| 相对 `/api` | 前端全部请求落在同源 `/api/...`（无跨主机、无 CORS 需求） |
| 防火墙行为 | 只读检测 + 人工提示；未申请管理员权限、未改动任何规则 |
| 未验收 | **无第二台真实手机**，因此本机 LAN 地址 HTTP 验证通过 ≠ 跨设备验收通过；真机跨设备验收留 Day6 |

## 28. 测试

| 命令 | 结果 |
| --- | --- |
| `cd backend && pytest` | **863 passed, 30 skipped, 4 warnings**（master baseline 为 860 passed / 30 skipped，本 PR 新增 3 条全绿） |
| `cd frontend && pnpm install --frozen-lockfile` | 退出码 0 |
| `cd frontend && pnpm exec tsc --noEmit` | 退出码 0 |
| `cd frontend && pnpm test` | 3 个文件 / **29 passed**（master baseline 17 条 + 本 PR 新增 12 条） |
| `cd frontend && pnpm build` | 退出码 0（`dist/assets/index-Xa3elwSW.css` + `index-C55edmh9.js`） |
| `pnpm contract:check` | **失败，但为 master baseline 漂移，与本 PR 无关**：已用 `git stash push -u` 把本 PR 全部改动移出工作区后在**纯 master 状态**复跑，得到同样的退出码 1；本 PR 未触碰 `docs/openapi-v0.2.json` 与 `frontend/src/generated/openapi.d.ts`（`git diff --name-only` 两者均为空），也未升级 `openapi-typescript`。真实原因：master 上 `docs/openapi-v0.2.json` 已更新，但 `frontend/src/generated/openapi.d.ts` 长期未重新生成（漂移约 +965 行）。**本轮未重新生成、未修改 snapshot 掩盖问题**，交由 A 轨 / 维护者决定何时统一刷新。 |

前端测试用例矩阵（`PublicViewStates.test.tsx`）：

| 场景 | 断言 |
| --- | --- |
| 排名页无排名行 | 出现「暂无赛事排名」+「查看签表」指向 `/public/t/12/bracket` |
| 排名页 Public 标题 | h2 含「赛事排名」、不含「小组排名」 |
| 签表页无签表无小组 | 出现「暂无淘汰赛签表」+「查看排名」指向 `/public/t/12/rankings`；旧文案不再出现 |
| 空态副作用 | 不调用 `generate-knockout` / `/score` / `finish-group-stage` |
| 空态 + localStorage 陷阱 | 不出现另一场赛事的链接或请求 |
| 有排名数据 | 正常渲染名次表，空态不出现 |
| 有签表数据 | 正常渲染签表，空态不出现，且无「录入大比分」/「生成淘汰赛签表」按钮 |
| Public 排名页 | 无 `/console`、`/players`… 管理端链接，无指向 `/` 的返回，有「返回实况」 |
| Public 签表页 | 无管理端链接、无「冠军之路」/「打印秩序册」 |
| 未知 Public 子路径 | 落到本赛事实况页（发 `/dashboard` 请求） |
| 大屏 FINISHED 且无签表 | 出现「赛事排名」+ 后端名次行 + 「比赛进度」 |
| 大屏 FINISHED 且有冠军 | 渲染冠军，且不叠加「赛事排名」 |

## 29. 尚未完成 / 外部阻塞（必须显式记录，不得虚报）

| 项 | 状态 | 归属 |
| --- | --- | --- |
| Public 多赛制接线（`format_code` → 导航可见性 / 空态 / 不适用页） | **未做**：等 #47 / #48 进入 master | D（下一轮） |
| Public 导航按赛制隐藏「签表 / 排名 / 冠军」入口 | **未做**：同上 | D |
| 扫码/深链接进入 `bracket` 时针对 SINGLE_ELIMINATION 的「不设循环赛排名」专用文案 | 目前用**中性空态**覆盖（对三种赛制都成立），专项文案等契约 | D |
| ROUND_ROBIN 大屏「不展示淘汰赛区域」的显式判定 | 目前只在「已结束且无签表」时展示赛事排名；显式判定等契约 | D |
| PR #45（手机录分）未合并 | 外部阻塞，本 D 轮无法推进 | A/C/维护者 |
| PublicLayout 的「赛事首页」仍指向 `/?tid=<tid>`（= 管理端首页，且当前无 AuthGuard） | **本轮未改**：这是 Day 2 的既定设计（记为“普通导航”），但观众点进去会看到管理界面。已在本轮新增测试中**只**断言“不出现 `/console`、`/players` 等管理页面链接”，未对该链接下断言。建议与 A 轨 AuthGuard / C 轨 IA 一并决策：要么隐藏，要么在未登录时改指向 `/public/t/:tid/live`。 | D + A + C（需产品决策） |
| LAN 跨设备验收（真实手机） | 无第二台设备，未验收 | 现场 / Day6 |
| Day5 报名确认 / 二维码 / Organization / Venue | 本轮冻结范围内**不做** | Day5+ |

## 30. 多赛制接线接入点（给下一轮的确切位置）

#47 / #48 进入 master 后，只需在**一个**位置接线，其余全部复用本轮成果：

1. `git fetch origin && git merge origin/master`；
2. `pnpm contract:generate` 重新生成 `frontend/src/generated/openapi.d.ts`，
   确认 `TournamentOut.format_code`（及 `rule_config` / `rule_version`）已出现；
3. 新增 `frontend/src/publicCapabilities.ts`：`getPublicCapabilities(formatCode)` 返回
   `{ showRankings, showBracket, showChampion }`。**只返回 UI capability**，
   不计算参赛者 / 晋级者 / BYE / 排名 / 对阵 / 完赛状态；枚举值必须取自 generated DTO，
   不新建第二套 enum；
4. `PublicLayout.tsx` 的 `NAV_ITEMS` 用该 helper 过滤（实况 / 赛程恒显示；
   GROUP_KNOCKOUT 增排名+签表+冠军；ROUND_ROBIN 增排名；SINGLE_ELIMINATION 增签表+冠军）；
5. `PublicRoutes.tsx` 的三个 adapter 把对应 capability 作为 prop 传入
   `RankingsPage` / `KnockoutPage`，页面在「不适用」时渲染**已有的** `PublicEmptyState`
   （文案按赛制专项化：循环赛 → 不设淘汰签表；单淘汰 → 不设循环赛排名）；
6. `BigScreenPage.tsx` 用同一 helper 决定是否渲染「小组排名（出线区）」与签表区域。

这样 Public 页面不需要新增第二套“前端赛制引擎”，也不会与 B 轨 Handler 出现两个真相源。

## 31. 多赛制行为矩阵：现状（本轮）vs 目标（#47 / #48 之后）

**现状（本轮真实行为，与赛制无关）**：因为 master 上没有 `TournamentOut.format_code`，
Public 端**不做任何赛制判定**，一律“有数据就展示、没数据就空态”，因此三种赛制下表内结果相同。
这也是本轮唯一诚实可行的口径 —— 任何按赛制隐藏入口的实现都必须先有权威字段。

| 视图 | 现状（本轮 Day4D） | 目标（GROUP_KNOCKOUT） | 目标（ROUND_ROBIN） | 目标（SINGLE_ELIMINATION） |
| --- | --- | --- | --- | --- |
| 实况 `/live` | 恒显示；FINAL 且无签表时展示后端「赛事排名」 | 同现状（签表 + 冠军 + 出线区） | 展示当前比赛 / 进度 / 赛事排名，不展示淘汰赛区域 | 展示当前比赛 / 进度 / 签表（BYE 按后端签表渲染）/ 冠军 |
| 赛程 `/schedule` | 恒显示（复用 SchedulePage） | 恒显示 | 恒显示 | 恒显示 |
| 排名 `/rankings` | 导航恒显示；无排名行 → 中性空态「暂无赛事排名」+ 查看签表 | 小组排名 | 赛事排名（后端 RR 名次） | 导航隐藏；直链 → 空态「本赛事不设置循环赛排名」+ 查看签表 |
| 签表 `/bracket` | 导航恒显示；无签表 → 中性空态「暂无淘汰赛签表」+ 查看排名 | 淘汰签表 | 导航隐藏；直链 → 空态「本赛事不设淘汰赛签表」+ 查看排名 | 签表（非 2 次幂 / BYE / 待定 slot 全部按后端数据渲染） |
| 冠军 `/champion` | 导航恒显示（复用 ChampionJourneyPage） | 冠军之路 | 视后端是否有可展示结果（否则隐藏） | 冠军之路 |
| 报名 `/register` | legacy 兼容页（V0.2 行为，已显式标注） | 待 Day5 Registration contract | 待 Day5 | 待 Day5 |

上表的「目标」列**本轮未实现**，已按第 30 节写成可直接落地的接入点。

---

# D 轨 Day4D · PR #50 Review Rework

> Review 结论：`REQUEST CHANGES`，唯一合并阻断 = **P1 相对数据库路径的解析基准不一致**
> 修复前 Head：`02891ef895977ee47bb2059f41ac90306ae40e05`
> 目标：只关闭该 P1 + 处理一项非阻断测试边界问题，**不扩大 Day4D 范围**。

## 32. P1 根因：探测器解析 DB 的基准 ≠ 真实后端解析 DB 的基准

`start_pingpong.ps1::Get-PublicTournamentId` 用只读 SQLite 取一个真实赛事 id，用于打印
`http://<LAN-IP>:<port>/public/t/<真实赛事ID>/live`。修复前它把路径**原样交给 Python probe**，
而 probe 又自己读了一遍环境变量：

```python
db = os.environ.get("PINGPONG_DB_PATH") or os.environ.get("DEMO_DB_PATH") or sys.argv[1]
```

于是相对路径按 **probe 进程的 CWD**（= 调用脚本时的目录）解析；但真实后端是
`Set-Location $backend; python -m uvicorn app.main:app ...`，而
`backend/app/db.py::_db_path()` 对覆盖值直接 `Path(override)`，
所以 `PINGPONG_DB_PATH=data\demo.db` 的真实含义是 **`<repo>\backend\data\demo.db`**。

两类后果（reviewer 指出的 B 类是阻断原因）：

| 类别 | 现象 | 严重度 |
| --- | --- | --- |
| A | 解析出的文件不存在 → probe 静默失败 → 只打印 base URL | 启动信息退化 |
| B | 解析出的路径恰好存在另一份 SQLite → 打印**指向错误赛事**的链接（例如打印 `/public/t/77/live`，而真实 FastAPI 服务的是赛事 41） | **P1 阻断** |

## 33. 修复内容

`start_pingpong.ps1`（唯一生产代码改动，其余都是测试与文档）：

1. **PowerShell 侧解析出唯一绝对路径**（与 `db.py::_db_path()` 同序）：
   `PINGPONG_DB_PATH` → `DEMO_DB_PATH` → `$backend\data\demo.db`；
2. 相对 override 用 **`Join-Path $backend`** 拼接（不是 `$root`、不是调用方 CWD），
   再 `[System.IO.Path]::GetFullPath()` 规范化；
3. 只把**绝对路径**作为 argv 传给 probe；
4. **probe 不再读任何环境变量**，只用 `db = sys.argv[1]`
   （否则进程里的原始相对 env 会覆盖已规范化的 argv，修复失效）；
5. probe 仍是 `mode=ro`：不建库、不迁移、不写库、不需要管理员权限；
6. 临时 probe 文件仍在 `finally` 中删除，探测失败一律静默降级为 base URL。

**路径解析规则（最终语义）**

| 场景 | effective DB |
| --- | --- |
| 未设置覆盖变量 | `<repo>\backend\data\demo.db` |
| `PINGPONG_DB_PATH=data\x.db`（相对） | `<repo>\backend\data\x.db` |
| `DEMO_DB_PATH=data\x.db`（相对，legacy） | `<repo>\backend\data\x.db` |
| `PINGPONG_DB_PATH=C:\y\z.db`（绝对） | `C:\y\z.db`（不再二次拼接） |

未改后端 `db.py`：后端当前行为是事实基准，启动脚本向其对齐，而不是反过来。

## 34. 验收证据

### 34.1 「修复前 vs 修复后」对照（含诱饵库，证明 B 类风险真实存在）

在 `<repo>\data\review_relative.db` 放入一个**诱饵库**（唯一赛事 id = **77**），
`backend\data\review_relative.db` 放真实库（唯一赛事 id = **41**），
`PINGPONG_DB_PATH=data\review_relative.db`，从**仓库根目录**执行：

| 语义 | probe 实际读取 | 解析出的 tid | 结论 |
| --- | --- | --- | --- |
| 修复前（env 优先，按 CWD 解析） | `data\review_relative.db` → `<repo>\data\review_relative.db` | **77** | 与 FastAPI 实际服务的 41 **不一致** → 会打印错误赛事链接 |
| 修复后（绝对 argv） | `<repo>\backend\data\review_relative.db` | **41** | 与 FastAPI 一致 |

并且**在诱饵库仍然存在**的情况下，真实运行修复后的脚本（从仓库根目录）打印
`/public/t/41/live`，同时 `GET /api/tournaments/41` 返回 `review-relative-41`：
证明「脚本打印的 id」与「FastAPI 实际使用的库」是同一个。

### 34.2 跨目录 × 4 个 DB 路径场景 smoke（真实运行脚本）

每个场景都真实执行 `start_pingpong.ps1 -SkipBuild -NoBrowser`，并额外用
`GET /api/tournaments/<打印出的 id>` 回查运行中的后端，确认该赛事**确实存在于被服务的库里**：

| 场景 | 工作目录 | 环境变量 | 打印 tid | 期望 | 后端回查 name | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| A 默认库 | 仓库根 | 无 | 1 | 1 | `1` | PASS |
| A 默认库 | `frontend\` | 无 | 1 | 1 | `1` | PASS |
| B 相对 `PINGPONG_DB_PATH` | 仓库根 | `data\review_relative.db` | 41 | 41 | `review-relative-41` | PASS |
| B 相对 `PINGPONG_DB_PATH` | `frontend\` | `data\review_relative.db` | 41 | 41 | `review-relative-41` | PASS |
| C 相对 `DEMO_DB_PATH` | 仓库根 | `data\review_demo_relative.db` | 42 | 42 | `review-demo-relative-42` | PASS |
| C 相对 `DEMO_DB_PATH` | `frontend\` | `data\review_demo_relative.db` | 42 | 42 | `review-demo-relative-42` | PASS |
| D 绝对 `PINGPONG_DB_PATH` | 仓库根 | `%TEMP%\review_abs_d4d.db` | 43 | 43 | `review-abs-43` | PASS |
| D 绝对 `PINGPONG_DB_PATH` | `frontend\` | `%TEMP%\review_abs_d4d.db` | 43 | 43 | `review-abs-43` | PASS |

**TOTAL=8 PASS=8**，调用目录不影响结果；smoke 夹具（`backend/data/review_*.db`、
`%TEMP%\review_abs_d4d.db`、临时 `<repo>\data\`）已全部删除，未进入版本库。

## 35. 测试补充与收窄

### 35.1 新增 `backend/tests/test_start_pingpong_script.py`（8 条静态契约回归）

无 Pester、不引入新依赖，用读文件 + 结构断言锁住那些“写错了也不报错、但会静默出错”的语义：

* 相对 override 必须以 `Join-Path $backend` 为基准，且 `IsPathRooted` 先于 `GetFullPath`；
* 优先级 `PINGPONG_DB_PATH > DEMO_DB_PATH > backend\data\demo.db` 与后端一致；
* probe 必须 `db = sys.argv[1]`，且**不含** `os.environ` / 两个环境变量名；
* probe 只读（`mode=ro`）且不含 INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/ATTACH/PRAGMA；
* 临时 probe 文件在 `finally` 中清理；
* 脚本保留 UTF-8 BOM（§17.4 的坑）；
* 脚本**永不**调用 `New/Set/Remove-NetFirewallRule`、`Set-NetFirewallProfile`、
  `netsh advfirewall set`、`New/Set-NetIPAddress`、`route add` 等改系统命令；
* Day4D 既有能力标记不缺失（虚拟网卡降权、多地址提示、防火墙只读、`-TournamentId`、
  无赛事降级、深链接、`Sort-Object Rank` 只排序不删除、逐个展示全部候选地址）。

### 35.2 收窄 `backend/tests/test_deployment_address_policy.py`（review 非阻断建议）

| 项 | 修复前 | 现在 |
| --- | --- | --- |
| `https?://` | 全局禁止（会误伤帮助文档 / 隐私政策 / 官网 / 未来 OAuth 跳转等合法外部链接） | **不再全局禁止** |
| `:8000` | 全局禁止（本身不等于部署耦合） | **不再全局禁止** |
| 回环 / RFC1918（`127.x`、`localhost`、`192.168.x.x`、`10.x.x.x`、`172.16-31.x.x`） | 禁止 | **保持禁止**（runtime source 扫描） |
| API 同源相对路径 | 精确断言 | **保持**，并新增 `api.ts` 不得出现任何绝对 URL 的兜底断言（只限 transport 层） |
| dist hash 文件名 | 禁止 | **保持** |

职责现在是清晰的「部署环境地址禁止」+「API transport 必须同源」两条精确规则，
不会再误伤业务页面里合法的外部 HTTPS 链接。

## 36. 本轮回归结果

| 命令 | 结果 |
| --- | --- |
| `cd backend && pytest` | **872 passed, 30 skipped**（rework 前 863 → 净增 9 条：部署策略测试 +1、启动脚本静态契约测试 +8） |
| `cd frontend && pnpm install --frozen-lockfile` | 退出码 0 |
| `pnpm exec tsc --noEmit` | 退出码 0 |
| `pnpm test` | 3 files / 29 passed（本轮未改前端） |
| `pnpm build` | 退出码 0 |
| `pnpm contract:check` | 仍失败：**master baseline OpenAPI 漂移**，与 PR #50 无关（输入未变，未改 snapshot） |
| PowerShell `Parser::ParseFile` | parse errors = **0** |
| UTF-8 BOM | 首字节 `EF BB BF` |

## 37. 本轮明确未改（避免范围扩张）

`RankingsPage.tsx` / `KnockoutPage.tsx` / `BigScreenPage.tsx` / `PublicRoutes.tsx` /
`PublicLayout.tsx` / `publicTournament.ts` / `backend/app/static_hosting.py` / `db.py`
均未改动；未接入 `format_code`、未 merge / cherry-pick #47 与 #48、未重做 LAN 地址枚举、
未引入新依赖、未做 Day5。

---

# D 轨 Day4D · 赛制契约接线轮（PR #50 第二轮 review）

> 触发：`#45` / `#47` / `#48` 已全部进入 master，PR #50 原先「等待 Tournament 赛制契约」的前提失效。
> 本轮把 Public / BigScreen 从「中性数据驱动」升级为**由后端 `format_code` 驱动的多赛制展示**。

## 38. 同步 master 与冲突解决

| 项 | 值 |
| --- | --- |
| merge 前 PR50 head | `64f067d0783c5ac268cb3d6b1b37136d2a724be6` |
| 实际 merge 的 master | `37a751aa3323f7bf9877262df503e001bc07f9dc`（含 #45 / #47 `76302df` / #48 `04ca855` / #52 / #53） |
| 方式 | `git merge origin/master`（**merge，不 rebase**，不 force push，不新开 PR） |
| 冲突文件 | 仅 `docs/WORKSTREAM_D.md` |
| 解决方式 | 用脚本按「公共前缀 + master(Day3 记录) + PR50(Day4D 记录)」重排，**两侧内容全部保留**，没有整文件选 ours/theirs；自动合并的 `api.ts` / `generated/openapi.d.ts` 等未手工逐行合并 |

冲突后校验：无 `<<<<<<<` / `=======` / `>>>>>>>` 残留，且同时包含
「# D 轨 Day 3 实施结果」「# D 轨 Day 4D 实施结果」「D 轨 Day4D · PR #50 Review Rework」三处标题。

## 39. Contract 同步（本轮主目标之一）

| 步骤 | 结果 |
| --- | --- |
| `cd backend && python export_openapi.py --check` | **PASS**（`OpenAPI snapshot is up to date`）→ 未修改 `docs/openapi-v0.2.json` |
| `cd frontend && pnpm contract:generate` | 重新生成 `src/generated/openapi.d.ts`（openapi-typescript 7.13.0） |
| `pnpm contract:check` | **PASS（退出码 0）** |

生成的 contract 中确认存在：

```text
TournamentFormat: "ROUND_ROBIN" | "SINGLE_ELIMINATION" | "GROUP_KNOCKOUT"
TournamentOut.format_code?: TournamentFormat | null
TournamentOut.rule_config?: { [key: string]: unknown }
TournamentOut.rule_version?: number | null
```

**类型来源（无第二套 enum、无 `as any`）**：

- `frontend/src/api.ts` 只新增一行 `export type TournamentFormat = Schemas['TournamentFormat']`；
- `publicFormat.ts` 的入参类型统一写成 `Tournament['format_code']`（即 generated DTO 的字段类型），
  不手写 `'ROUND_ROBIN' | ...` 联合类型；
- 页面里没有任何 `(tournament as any).format_code`。

## 40. 唯一 capability helper：`frontend/src/publicFormat.ts`

职责只有「某赛制展示哪些 Public 模块」，返回三个 UI 开关，**不计算任何业务结果**
（排名 / 晋级 / BYE / 种子 / 抽签 / 完赛状态 / 阶段推进一律不碰）。

| 赛制 | showRankings | showBracket | showChampion |
| --- | --- | --- | --- |
| `ROUND_ROBIN` | ✅ | ❌ | ❌ |
| `SINGLE_ELIMINATION` | ❌ | ✅ | ✅ |
| `GROUP_KNOCKOUT` | ✅ | ✅ | ✅ |
| `null` / 字段缺失（legacy） | ✅ | ✅ | ✅ |

`live` / `schedule` / `register` 始终可见，不受本 helper 控制。

**legacy 策略（D4A 冻结）**：`format_code == null` 时**不推断赛制**、不默认成 `GROUP_KNOCKOUT`，
一律返回「全部可见 + 数据驱动」：
有数据就展示，没数据由页面给出中性空态 —— 这样既不会破坏 V0.2 旧赛事，也不会凭猜测隐藏入口。
历史赛事「到底属于哪种赛制」是后端事实，前端只消费 `format_code` 本身，
不看 `stage`、不看有没有 group、不看有没有 knockout tree。

另外两个纯展示映射：

- `getRankingsTitle(format_code)`：只有明确 `GROUP_KNOCKOUT` 才叫「小组排名」，
  循环赛与 legacy 用中性的「赛事排名」；
- `getPublicStageLabel(format_code, stage)`：修掉「纯循环赛赛事因为库里也用
  `stage = GROUP_STAGE` 而被显示成小组赛」的误导（RR → 循环赛，SE → 单淘汰，
  GK / legacy 保持原有 小组赛 / 淘汰赛）。只做文案映射，不做状态机。

## 41. 接线明细

| 文件 | 改动 |
| --- | --- |
| `frontend/src/layouts/PublicLayout.tsx` | `NAV_ITEMS` 增加 `capability` 标记，按 `getPublicCapabilities(tournament.format_code)` 过滤「排名 / 签表 / 冠军」；阶段徽标改用 `getPublicStageLabel`。权限判断只在这一处。 |
| `frontend/src/pages/RankingsPage.tsx` | Public 先 `getTournament` 拿权威 `format_code`：`showRankings=false`（单淘汰）时**不请求** `/rankings` 与 GROUP 完赛查询，直接渲染只读「本赛事采用单淘汰赛制，不设置循环赛排名。」+「查看签表」CTA；标题由 `getRankingsTitle` 决定；管理端请求序列与标题完全不变。 |
| `frontend/src/pages/KnockoutPage.tsx` | Public 先拿 `format_code`：`showBracket=false`（循环赛）时**不请求** `/knockout`，渲染只读「本赛事采用循环赛制，不设置淘汰赛签表。」+「查看排名」CTA；`SINGLE_ELIMINATION` 只请求并渲染后端签表（BYE / 待定 slot 全部按服务端数据渲染），连 `/rankings` 都不请求，因此不会出现「请先完成小组赛 / 每组前 N 名」这类 GK 专属语义；GK 与 legacy 请求序列不变。 |
| `frontend/src/pages/BigScreenPage.tsx` | 先取 `format_code`，通用数据（tournament / dashboard / players / entries）之后按 capability 决定是否请求 `rankings` / `knockout`；出线区、签表、冠军、结束态排名面板都按 capability 门控；循环赛的排名区标题为「赛事排名」且不显示「出线」勾选；冠军仍只来自后端 `KnockoutTree.champion`。 |
| `backend/tests/test_start_pingpong_script.py` | 修正文档引用：`docs/D4D_PR50_REVIEW_REWORK.md`（不存在）→ `docs/WORKSTREAM_D.md` 的对应章节，**没有新建重复文档**。 |

**刻意不做的两件事**（避免范围扩张）：不重构 `ChampionJourneyPage`（仅通过导航隐藏 RR 的冠军入口）；
不动 `backend/app/services/formats.py` / `domain/draw.py` / `services/knockout.py` 等 B 轨算法。

## 42. 本轮新增测试

| 文件 | 条数 | 覆盖 |
| --- | --- | --- |
| `frontend/src/__tests__/publicFormat.test.ts` | 12 | helper 纯函数：三种赛制 + legacy 的能力矩阵、legacy 不被识别成 GK、helper 只返回三个开关、标题与阶段文案映射 |
| `frontend/src/__tests__/PublicFormatMatrix.test.tsx` | 15 | PublicLayout 导航矩阵（RR/SE/GK/null）、`/rankings` SE 不适用态（含「不请求排名数据」「无管理入口」「无写请求」）、`/bracket` RR 不适用态（含不请求 `/knockout`、无 GK 文案）、SE 渲染真实签表（BYE → 待定）、GK/legacy 不退化、BigScreen 四套赛制的区域与请求集合 |

## 43. 本轮回归结果

| 命令 | 结果 |
| --- | --- |
| `cd backend && python export_openapi.py --check` | PASS |
| `cd backend && pytest` | **955 passed, 20 skipped**（含本 PR 的 12 条：部署地址策略 4 + 启动脚本静态契约 8） |
| `cd frontend && pnpm install --frozen-lockfile` | 退出码 0 |
| `pnpm contract:generate` / `pnpm contract:check` | 生成成功 / **PASS（退出码 0）** |
| `pnpm exec tsc --noEmit` | 退出码 0 |
| `pnpm test` | **10 files / 138 passed**（master 合入的 MobileScore* / ConsoleScoreWorkflow / ApiErrorParsing / TournamentSettingsPage 全部继续通过） |
| `pnpm build` | 退出码 0 |
| PowerShell `Parser::ParseFile` | parse errors = **0** |
| UTF-8 BOM | 首字节 `EF BB BF` |

## 44. LAN smoke（真实执行 `start_pingpong.ps1`）

### 44.1 上一轮 P1 回归：数据库路径（8/8 PASS）

| 场景 | 工作目录 | 环境变量 | 打印 tid | 期望 | 后端回查 name |
| --- | --- | --- | --- | --- | --- |
| A 默认库 | 仓库根 / `frontend\` | 无 | 1 | 1 | `1` |
| B 相对 `PINGPONG_DB_PATH` | 仓库根 / `frontend\` | `data\review_relative.db` | 41 | 41 | `review-relative-41` |
| C 相对 `DEMO_DB_PATH` | 仓库根 / `frontend\` | `data\review_demo_relative.db` | 42 | 42 | `review-demo-relative-42` |
| D 绝对 `PINGPONG_DB_PATH` | 仓库根 / `frontend\` | `%TEMP%\review_abs_d4d.db` | 43 | 43 | `review-abs-43` |

### 44.2 三赛制 deep-link（同一库内 3 个赛事，14/14 PASS）

库内：`41 = ROUND_ROBIN`、`42 = SINGLE_ELIMINATION`、`43 = GROUP_KNOCKOUT`。

| 检查 | 结果 |
| --- | --- |
| `/api/health`、`/` | 200 |
| `/public/t/41/{live,rankings,bracket}` | 均 200 + SPA（刷新不 404） |
| `/public/t/42/{live,rankings,bracket}` | 均 200 + SPA |
| `/public/t/43/{live,rankings,bracket}` | 均 200 + SPA |
| `GET /api/tournaments/{41,42,43}.format_code` | 分别返回 `ROUND_ROBIN` / `SINGLE_ELIMINATION` / `GROUP_KNOCKOUT`（证明契约真的在服务端生效） |

**TOTAL=22 PASS=22 FAIL=0**（8 条数据库路径 + 9 条 deep link + 3 条 format 契约 + 2 条 health/root）。
HTTP 层只能证明「SPA 正常返回」；**「不适用空态」本身由 15 条 jsdom 集成测试断言**
（见 §42），二者互补。smoke 夹具已全部删除，未污染版本库，端口已释放。

## 45. 本轮明确未做

未实现 Day5 报名 / 二维码 / Organization / Venue；未复制任何 B 轨规则
（BYE / seed / 抽签 / ranking / advance / completion 全部仍由后端决定）；
未重构 `ChampionJourneyPage`；未引入新依赖；未修改 `docs/openapi-v0.2.json`。

已知取舍：`PublicLayout` 在赛事数据到达前按「全部可见」渲染导航，因此存在极短的
「全量导航 → 按赛制收敛」过渡帧。这是刻意选择 —— 赛制未知时隐藏入口，风险高于多显示一帧。

---

# D 轨 Day4D · 第三轮收口（PR #50 最终 review）

> 触发：reviewer 确认上一轮主阻断（master 同步 / `format_code` 接线 / generated contract /
> `contract:check` / Rankings / Bracket / BigScreen 主体 / LAN DB path）已关闭，本轮只剩 2 个 P1 + 1 个非阻断项。
> 范围：**小补丁收口**，不动 contract、不动 Rankings / Bracket / LAN 主方案。

## 46. master 同步判定

| 项 | 值 |
| --- | --- |
| 本轮开始时 PR50 head | `3aed9aef50e525614bb4bcc738cf2354fb158691` |
| `git fetch origin` 后的 `origin/master` | `37a751aa3323f7bf9877262df503e001bc07f9dc`（**未前进**） |
| `git merge-base HEAD origin/master` | 同上（= base） |
| behind / ahead | `0 / 7` |
| 结论 | **不制造空 merge**，直接在当前 head 上收口 |

## 47. P1-A：Public `/champion` 缺少 capability guard + 返回地址错误

### 47.1 根因

`ChampionJourneyPage` 内部**无条件**执行 `setTree(await api.getKnockout(tid))`，
而 Public adapter 直接把它挂到 `/public/t/:tid/champion`：

```text
ROUND_ROBIN 赛事（没有淘汰阶段）
  -> 访问 /public/t/<tid>/champion
  -> 仍然进入淘汰赛 / 冠军逻辑，并发出一次无意义的 /knockout 请求
```

同一页面的「返回签表」写死为 `to={`/knockout?tid=${tid}`}` —— 那是**管理端路由**，
Public 观众一点就会掉出 Public shell。

### 47.2 修复（最小改动，不重构页面）

1. `frontend/src/PublicRoutes.tsx` 新增 `PublicChampionView`：先 `api.getTournament(tid)`
   拿权威 `format_code`，再用 `getPublicCapabilities(...).showChampion` 决定走向；
2. `ROUND_ROBIN` → 不渲染 `ChampionJourneyPage`、不请求 `/knockout`，改为复用既有
   `PublicEmptyState`：标题「本赛事不设冠军之路」，说明「本赛事采用循环赛制，最终名次以赛事排名为准。」，
   CTA「查看排名」→ `/public/t/:tid/rankings`；
3. `ChampionJourneyPage` 新增**精确的** `backTo?: string` prop（默认值仍是管理端
   `/knockout?tid=<tid>`）；Public adapter 传 `/public/t/<tid>/bracket`。
   刻意不加模糊的 `readOnly`，也不重构页面行为。

| format_code | `/public/t/:tid/champion` |
| --- | --- |
| `ROUND_ROBIN` | 只读空态；**0 次** `/knockout` 请求；CTA → `/rankings` |
| `SINGLE_ELIMINATION` | 进入冠军之路；「返回签表」→ `/public/t/:tid/bracket` |
| `GROUP_KNOCKOUT` | 同上 |
| `null` / 字段缺失（legacy） | 同上（不默认成 GK，也不显示不适用空态） |

Public 页面**不再出现任何 `/knockout?tid=` 管理端 href**。

## 48. P1-B：ROUND_ROBIN 大屏比赛卡文案自相矛盾

### 48.1 根因

大屏顶部已用 `getPublicStageLabel()` 把 RR 显示成「循环赛」，
但「正在进行」的比赛卡仍写死 `tb.match.stage === 'GROUP' ? '小组赛' : '淘汰赛'`。
纯循环赛在领域模型里本来就是 `Match.stage = GROUP`（既有后端事实），于是同一场比赛出现两个说法：

```text
顶部：循环赛
比赛卡：小组赛
```

### 48.2 修复

在 `frontend/src/publicFormat.ts` 增加纯展示 helper：

```text
getPublicMatchStageLabel(formatCode, matchStage)
  ROUND_ROBIN + GROUP              -> 循环赛
  GROUP_KNOCKOUT / null + GROUP    -> 小组赛
  任意 + KNOCKOUT                   -> 淘汰赛
```

`BigScreenPage` 的比赛卡统一调用该 helper，**不再在 JSX 内复制赛制判断**。
**未修改** `TournamentStage` / `MatchStage` 枚举、DB CHECK、任何 Format Handler。

## 49. 本轮新增测试（全部非空洞）

| 文件 | 新增 | 要点 |
| --- | --- | --- |
| `frontend/src/__tests__/publicFormat.test.ts` | +6（合计 18） | `getPublicMatchStageLabel`：RR+GROUP → 循环赛；GK+GROUP / legacy+GROUP → 小组赛；任意 + KNOCKOUT → 淘汰赛；空 stage → 空串 |
| `frontend/src/__tests__/PublicFormatMatrix.test.tsx` | +6（合计 21） | Champion 深链 4 例（RR / SE / GK / legacy）、RR 比赛卡 1 例、GK 比赛卡 1 例 |

**非空洞性**（reviewer 明确要求）：

- RR 大屏 fixture 真的包含 `table.status = OCCUPIED` + `match.status = PLAYING` + `match.stage = GROUP`；
  断言用 `within(document.querySelector('.bigscreen-table'))` **定位到比赛卡**：
  卡内必须有「循环赛」、必须没有「小组赛」—— 只断言页面顶部会虚假通过，因此没有那样写；
- Champion 断言检查**真实 `href`**（`/public/t/12/bracket`），并反向断言不存在 `/knockout?tid=`；
- RR Champion 断言 `/knockout` 请求数为 **0**；
- jsdom 无 `ResizeObserver`（冠军之路在有签表时会用它测量连线），测试内做环境 shim，不改组件行为。

## 50. 本轮回归结果

| 命令 | 结果 |
| --- | --- |
| `cd backend && python export_openapi.py --check` | **PASS** |
| `cd backend && pytest` | **955 passed, 20 skipped** |
| `frontend: pnpm exec tsc --noEmit` | 退出码 0 |
| `frontend: pnpm test` | **10 files / 150 passed**（上一轮 138 → +12） |
| `frontend: pnpm build` | 退出码 0 |
| `frontend: pnpm contract:check` | **PASS（退出码 0）** |
| `start_pingpong.ps1` Parser / BOM | parse errors = 0 / `EF BB BF`（本轮未改该脚本） |

## 51. Champion deep-link smoke（production 单服务）

真实执行 `start_pingpong.ps1`，用同一库内的 `41 = ROUND_ROBIN` / `42 = SINGLE_ELIMINATION` /
`43 = GROUP_KNOCKOUT` 三个赛事验证：

| 深链接 | 结果 |
| --- | --- |
| `/public/t/41/champion`、`/public/t/42/champion`、`/public/t/43/champion` | 均 **200 + SPA root、刷新不 404** |
| `/api/health`、`/` | 200 |

语义层（RR 不请求 `/knockout`、SE/GK/legacy 返回 Public bracket、无管理端 href）
由 §49 的 jsdom 集成测试断言，二者互补。夹具已删除，端口已释放。

## 52. 本轮明确未做

未重新修改 `frontend/src/generated/openapi.d.ts`、`docs/openapi-v0.2.json`、
`RankingsPage.tsx`、`KnockoutPage.tsx`、`start_pingpong.ps1`、
`backend/tests/test_deployment_address_policy.py`、`backend/tests/test_start_pingpong_script.py`；
未触碰 `backend/app/services/formats.py`、`backend/app/domain/draw.py`、
`backend/app/services/knockout.py` 及 ranking / seed / BYE / qualification 逻辑；
未做 Day5（报名 / 二维码 / Organization / Venue）；未引入新依赖。
