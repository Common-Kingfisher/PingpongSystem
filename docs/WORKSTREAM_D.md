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
