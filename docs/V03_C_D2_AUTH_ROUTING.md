# PingpongSystem V0.3 — C 轨 Day 2 登录与权限路由设计

状态：前端展示层与接线边界已冻结

基线：`origin/master@b8fe480`（包含 C 轨 Day 1 / PR #38）

分支：`feat/v03-admin-auth-routing`

## 1. 本轮交付结论

PR #42 当前已完成 A2.1 数据模型/迁移和 A2.2 认证安全/初始化服务，包含 Bootstrap 三态、`phone` / `note`、密码与 Session 服务；A2.3 Auth API 和 OpenAPI contract 尚未提供。因此 C 轨本轮实现不依赖真实认证 API 的页面、ViewModel 和交互边界；不创建 AuthContext、Guard 或认证客户端，不修改 OpenAPI，不在 localStorage 写入登录状态，也不硬编码任何管理员。

本轮新增：

- LoginPage 展示层与两类固定错误文案；
- ForbiddenPage 与 TournamentUnavailablePage；
- EventSelectorPage 的等待契约、零赛事和多赛事 ViewModel；
- SystemLayout、SystemDashboardPage、SystemUsersPage 展示层；
- AdminLayout 的赛事切换器、用户角色区与简单账号菜单；
- 本文档中的最终路由表、Guard 层级及接线条件。

本轮不把新页面接入 `App.tsx`。在真实 `/auth/me`、赛事授权列表及 Bootstrap contract 合入前，把 `/system` 或赛事管理路由暴露为无 Guard 的“可访问页面”会产生错误安全语义。

## 2. Login UX

登录页只包含品牌、用户名、密码和登录按钮，不提供注册、第三方登录、验证码、记住我、OAuth、找回密码或营销内容。

固定错误语义：

| UI 场景 | 文案 |
| --- | --- |
| 用户名、密码错误或账号停用 | 用户名或密码错误 |
| 网络故障 | 无法连接服务器，请检查服务器或本地网络 |

`LoginPage` 只产出 UI 表单值并调用注入的 `onSubmit`，不会假装这是后端 DTO。没有认证适配器时，登录按钮明确显示“等待认证服务接入”并保持不可用。

## 3. Bootstrap 三状态

| 状态 | 前端入口 | 语义 |
| --- | --- | --- |
| `NEEDS_INITIALIZATION` | `/setup` | 仅服务器本机可用；后端原子创建第一个 SYSTEM_ADMIN 并写入 `bootstrap_completed=true` |
| `READY` | `/login` | 正常登录 |
| `RECOVERY_REQUIRED` | 恢复说明页 | 已初始化但无可用 SYSTEM_ADMIN；禁止重新开放 Web setup，提示在服务器本机执行恢复流程 |

C 轨不根据 SYSTEM_ADMIN 数量自行推断 Bootstrap 状态，不实现 CLI、恢复密钥或安全协议。

## 4. 登录后角色分流

### SYSTEM_ADMIN

登录后进入 `/system`。System Admin 是独立管理域，左侧固定为系统总览、用户管理、赛事列表、备份与恢复。系统角色本身不赋予任何一场赛事的写权限。

### EVENT_ADMIN

以 `/auth/me` 和后端可管理赛事列表为唯一依据：

| 可管理赛事数 | 登录后目标 |
| ---: | --- |
| 0 | `/events`，显示“目前没有可管理的赛事”并允许创建赛事 |
| 1 | 直接进入 `/?tid=<id>` |
| 2+ | `/events` |

Day 2 规则取代 Day 1 的固定“我的赛事 → 选择赛事 → Admin”：一场赛事时不增加中间页面。

## 5. 路由表

### Public / Bootstrap

| 路由 | Owner | Guard |
| --- | --- | --- |
| `/login` | C UI / A Auth | Bootstrap 为 READY 时公开 |
| `/setup` | A/D | 后端确认 NEEDS_INITIALIZATION 且仅服务器本机 |
| `/schedule`、`/bigscreen`、`/register`、`/journey` | D | Public 策略；URL 显式携带赛事 ID |

### System

| 路由 | 页面 | Guard |
| --- | --- | --- |
| `/system` | System Dashboard | RequireAuth → RequireSystemAdmin |
| `/system/users` | 用户管理 | RequireAuth → RequireSystemAdmin |
| `/system/events` | 系统赛事列表 | RequireAuth → RequireSystemAdmin |
| `/system/backups` | 备份与恢复 | RequireAuth → RequireSystemAdmin |

### Admin

现有 URL 继续兼容：`/`、`/players`、`/draw`、`/orderbook`、`/console`、`/rankings`、`/knockout`、`/settings`。它们使用 RequireAuth → RequireTournamentAccess，并继续以 `?tid=<id>` 携带赛事上下文。

旧深链 `/preflight`、`/match-print`、`/team-roster`、`/team-ties`、`/team-tie`、`/team-rankings`、`/team-qualification`、`/team-knockout` 必须保留，不因 Layout 接入而删除。

## 6. Guard 层级与错误语义

```text
Bootstrap gate
├─ NEEDS_INITIALIZATION → /setup（仅本机）
├─ RECOVERY_REQUIRED → 恢复说明
└─ READY
   ├─ Public routes
   └─ RequireAuth
      ├─ RequireSystemAdmin → /system/*
      └─ RequireTournamentAccess → Admin routes + tid
```

| 后端结果 | UI 行为 |
| --- | --- |
| `401 AUTH_REQUIRED` | 进入重新认证流程，并保存原始目标 URL；不得立即清空页面输入上下文 |
| `403 FORBIDDEN` | 显示 ForbiddenPage，允许按上下文返回，不自动切赛事 |
| `404 RESOURCE_NOT_FOUND` | 显示 TournamentUnavailablePage：“该赛事不存在，或当前账号没有访问权限” |

前端 Guard 只改善 UX，服务端仍是唯一安全边界。赛事越权使用 404 统一语义，不泄露资源存在性。

## 7. Session UX

- 刷新与正常重开浏览器后尽量保持登录；
- 短暂断线和休眠不主动退出；
- Session 正常续期无感；
- 收到真实 401 时保留目标 URL和未提交输入上下文，完成重新认证后再恢复；
- 主动退出时清除认证状态和当前用户的敏感草稿，并进入 `/login`。

Session 生命周期、Cookie、Bearer Token、续期与撤销全部由 A 轨 contract 决定。C 轨不自行发明刷新 Token 或持久化协议。

## 8. 赛事切换

AdminLayout 接收后端授权结果映射出的 `manageableEvents`，不会从 localStorage 推导权限。多赛事时显示其他可管理赛事及“查看全部赛事”；一场赛事时仅显示当前赛事，不强迫跳转 `/events`。

切换时保留当前 pathname，并只替换 query 中的 `tid`。若后端随后拒绝或目标不支持该功能，再由接线层回到该赛事 Dashboard。

## 9. 权限 UI

赛事角色沿用后端：OWNER、ADMIN、OPERATOR、VIEWER。AdminLayout 只接收“可操作 / 只读 / 无权限”的权威结果：

- 无权限菜单保留位置并灰态；
- 点击灰态菜单明确提示；
- 直接访问由 Guard 和后端错误语义处理；
- VIEWER 的只读按钮状态不能替代服务端限制。

本阶段不建设 RBAC 编辑器。

## 10. 用户管理边界

SystemUsersPage 建立表格、创建 EVENT_ADMIN 表单和回调边界。创建表单遵循 A2.2 已实现的数据约束：username、display_name、初始密码为必填，phone、note 为可选，角色固定 EVENT_ADMIN，默认启用；提交仍等待用户管理 API。列表字段为姓名、用户名、角色、状态、最近登录和操作。允许查看详情、重置密码、停用/启用、查看赛事授权；不提供删除用户、查看旧密码或 password_hash。

没有用户管理 API 时所有动作保持不可用，不显示假成功。创建 User 与 TournamentAdmin 赛事授权始终分离。

密码规则 UI 可在真实 contract 接入时展示“至少 12 个字符、至少包含字母和数字”，最终验证以后端为准。

## 11. Owner 边界

| Owner | 本阶段责任 |
| --- | --- |
| A 秦培豪 | 认证后端、Session、Bootstrap、User/TournamentAdmin、权限依赖、401/403/404、OpenAPI contract |
| B 高翌哲 | 赛制、抽签、比分、排名算法 |
| C | Login/错误页/赛事选择/System/AdminLayout 展示层；contract 到位后的前端 Auth/Guard 接线 |
| D 谢嘉然 | PublicLayout、公开页面、移动录分、部署与 LAN |
| E 周子腾 | 测试、集成与 Review |

## 12. 等待 A contract

PR #42 的 A2.2 已具备后端 Bootstrap 状态、密码/Session 服务、登录/退出/改密服务函数、账号停用撤销 Session，以及 `phone` / `note` 数据字段；这些还不是前端可调用的 API contract。

下列能力当前没有接线：

- login、logout、me、change-password；
- Bootstrap 状态查询与 setup Router；
- 当前用户及系统角色；
- 当前用户可管理赛事列表与赛事权限；
- 用户管理、停用/启用、重置密码；
- 赛事创建成为 OWNER；
- 服务端 401/403/404 错误 DTO。

A 轨完成 A2.3/A2.4 并输出稳定 OpenAPI contract 后，C 轨才能新增 generated type 驱动的 Auth client、AuthContext、RequireAuth、RequireSystemAdmin、RequireTournamentAccess，并对 `App.tsx` 做最小接线。

## 13. 明确未做

后端认证、密码哈希、Session 安全、Bootstrap 后端、权限算法、OpenAPI schema、PublicLayout、移动录分、比赛规则以及假登录均未实现。
