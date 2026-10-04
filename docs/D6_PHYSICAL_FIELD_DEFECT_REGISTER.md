# Day6 Physical Field 压测缺陷登记

登记时间：2026-10-04  
基线：`master @ 9dbcd6b3b82e4685fc79bac2bf08d97975c1c91a`  
压测目标：Windows 本机 production 单服务 + 普通无线路由器 + 5-6 台真实手机，完成 16 人 / 4 组 / 前 2 晋级 / 6 台的小组赛加淘汰赛现场链路。

## 当前判定

| 等级 | 数量 | 对本轮压测的影响 |
| --- | ---: | --- |
| P1 阻断 | 2 | DF-001 登录接线与 DF-005 锁屏恢复悬挂请求均影响真实手机登录链路；代码修复已完成，正式 Physical Gate 不能 PASS。 |
| P2 记录 | 3 | 不阻断数据正确性和压测执行，可本轮顺手修复，也可延后。 |
| P0 | 0 | 当前未发现比分、晋级、跨赛事、重启数据丢失类缺陷。 |

DF-001 与 DF-005 代码修复已完成，但真实手机 LAN 回验尚未完成；Day6 Physical Field Gate 只能维持：

```text
BLOCKED — DF-001 field revalidation pending
```

## DF-001

| 字段 | 内容 |
| --- | --- |
| 等级 | P1 |
| 状态 | FIXED_CODE_ONLY — 待真实手机 LAN 回验 |
| 分类 | 认证 / 录分 / 路由 |
| 影响端 | 真实手机 Admin Console、Mobile Score、用户菜单 |
| 是否阻断压测 | 是 |

### 现象

真实手机打开管理端后显示「用户信息待接入」，「修改密码」和「退出登录」为灰色。访问 `/login` 没有独立登录页，SPA 仍渲染空的管理端壳。录分链路无法由现场人员在手机上完成登录。

### 复现

1. 使用 production 单服务从真实手机访问 LAN 地址，例如 `http://<server-lan-ip>:8000/`。
2. 打开管理端页面。
3. 观察右上角用户菜单。
4. 直接访问 `/login`。

### 预期

存在可用的登录入口；登录后管理端显示当前用户和角色；修改密码与退出登录可用；未登录访问受保护管理页时能安全进入登录流程。

### 实际

`AdminShell` 只向 `AdminLayout` 传赛事信息，没有传 `currentUserLabel`、`onChangePassword`、`onLogout`。前端路由表没有 `/login`；`LoginPage` 组件存在但未挂载。前端 API 客户端也没有 auth 方法。

### 根因定位

- `frontend/src/App.tsx`：`AdminShell` 未接入用户态回调。
- `frontend/src/layouts/AdminLayout.tsx`：缺少 props 时渲染「用户信息待接入」并禁用按钮。
- `frontend/src/main.tsx`：通配路由进入 `App`，但 `App` 没有 `/login` 路由。
- `frontend/src/pages/LoginPage.tsx`：组件存在但未被导入。
- `frontend/src/api.ts`：未实现 login / logout / me / change-password。
- `frontend/src/MobileScoreRoutes.tsx`：`AdminScoreGuardBoundary` 仍是预留接线点，未接 `RequireAuth` / `RequireTournamentAccess`。

### 对压测手册的影响

以下场景无法按手册完成：

- 手机 3 通过 Mobile Score A 登录并录分。
- 手机 4 通过 Mobile Score B 登录并并发录另一场比赛。
- 手机 6 与手机 3 对同一场比赛做冲突提交。
- Mobile Score 物理断网后恢复并重新提交。
- 后台 30-60 秒返回后继续录分。

后端本身已经具备 `/api/v1/auth/login`、`/me`、`/logout`、`/change-password`，录分接口也依赖 `require_tournament_write`；问题集中在前端 Auth shell 未接线，不是服务端未鉴权或网络不可达。

### 修复验收

1. 真实手机在 LAN 下可通过 UI 登录，不再依赖浏览器 console、CDP 或脚本预置 Cookie。
2. 登录成功后调用 `/api/v1/auth/me`，管理端用户菜单显示用户名和角色。
3. 「修改密码」和「退出登录」在真实手机上可操作。
4. 未登录访问 Mobile Score 时进入安全登录流程，不能把失败写成保存成功。
5. OPERATOR 账号能访问已授权赛事的录分页并正常提交；未授权账号按后端契约收到 401 / 403 / 404，且页面展示明确错误。
6. 重新执行 DF-001 关联场景：正常录分、不同 Match 并发、同 Match 冲突、断网提交不假成功、恢复后重试。
7. `pnpm test`、`pnpm exec tsc --noEmit`、`pnpm build` 通过。
8. 留存真实手机截图或录屏，记录手机型号、LAN IP、账号角色和提交结果。

#### 修复记录

- 前端 API 已接入 browser 会话模式的 login / logout / me / change-password。
- `/login`、`/change-password` 已挂载；未登录访问受保护管理页和手机录分页会进入登录流程，登录后按站内相对 `next` 跳回。
- Admin Shell 已显示用户名、角色、可切换赛事，并接通修改密码和退出登录。
- Mobile Score 已接入登录与赛事访问守卫；写权限仍由后端契约裁决。
- Auth Context 已处理初始 `/me` 探测与登录成功之间的晚到 401 竞态。
- 2026-10-04 真实手机首轮复验：专用 LAN 测试账号可登录；锁屏恢复后触发 DF-005，已按新缺陷登记并修复。
- 代码级验证：Vitest 18 个文件 / 236 条用例通过，`tsc --noEmit` 通过，production build 通过。
- 真实手机 LAN 回验、截图/录屏与账号角色记录尚未完成，因此本条不能关闭为 Field PASS。

## DF-002

| 字段 | 内容 |
| --- | --- |
| 等级 | P2 |
| 状态 | FIXED |
| 分类 | 视觉 / 响应式 |
| 影响端 | 360px Public Live / BigScreen 标题 |
| 是否阻断压测 | 否 |

超长无断点标题在 360px 下被硬裁切，页面无横向溢出，按钮和数据不受影响。来源见 `docs/D6D_FIELD_SIMULATION.md` 的 P2 第 1 条。后续最小修复方向是给 `.bigscreen-header h1` 增加 `overflow-wrap: anywhere`。

### 修复记录

- `.bigscreen-header h1` 已增加 `overflow-wrap: anywhere`。
- 页面级回归断言已覆盖该 CSS 修复。

## DF-003

| 字段 | 内容 |
| --- | --- |
| 等级 | P2 |
| 状态 | FIXED |
| 分类 | 文案 |
| 影响端 | Mobile Score |
| 是否阻断压测 | 否 |

「比分已保存」与「比分已保存，但最新状态刷新失败……」相邻渲染时文案重复。语义正确，不是提交失败。后续可合并为一条提示，避免现场人员误读。

### 修复记录

- 刷新失败时完成态只保留一条合并提示，不再与“比分已保存”重复。
- Mobile Score 回归测试覆盖 reload 失败场景。

## DF-004

| 字段 | 内容 |
| --- | --- |
| 等级 | P2 |
| 状态 | FIXED |
| 分类 | 管理端操作流 |
| 影响端 | Players / 报名确认 |
| 是否阻断压测 | 否 |

确认完最后一条报名后仍停留在「待确认报名」tab，需要手动切换到「正式名单」。数据正确，只是多一步操作。后续可在列表清空后自动切回或提供显式跳转。

### 修复记录

- 确认最后一条 PENDING 报名后自动切回“正式名单”；仍存在待确认报名时保持当前 tab。
- 已补“最后一条自动切换”和“仍有一条待确认时不切换”的回归测试。

## DF-005

| 字段 | 内容 |
| --- | --- |
| 等级 | P1 |
| 状态 | FIXED_CODE_ONLY — 待真实手机 LAN 回验 |
| 分类 | 认证 / 移动端生命周期 / 网络容错 |
| 影响端 | 真实手机 Admin Console、Mobile Score、登录页 |
| 是否阻断压测 | 是 |

### 现象

真实手机登录成功后锁屏；回到浏览器时始终停在「正在检查登录状态…」。返回历史记录进入登录页后再次提交账号密码，按钮停留在「正在登录…」，无法完成登录。

### 复现

1. 使用 production 单服务从真实手机 LAN 地址登录。
2. 登录成功后锁屏，稍后回到浏览器。
3. 观察鉴权页面状态；再返回登录页重复提交。

### 预期

移动端后台恢复后，悬挂的鉴权请求必须进入失败/重试路径；登录按钮不能无限保持提交中。

### 根因定位

手机浏览器锁屏会暂停页面和网络请求；恢复后旧 `fetch` Promise 可能长时间保持 pending。前端 `request()` 没有请求超时，`AuthProvider` 的 `/me` 探测和 `LoginRoute` 的登录 Promise 都无法进入 `catch` / `finally`，导致守卫加载态和提交态卡死。

### 修复记录

- Auth 请求改用 `api.requestWithTimeout()` 增加 8 秒超时：`AbortController` 取消底层请求，`Promise.race` 保证 UI Promise 必然结束。
- 共享 `api.request()` 保持无超时；score、导入导出、赛制生成等既有请求语义不变。
- 超时抛出 `ApiError(0, '请求超时，请检查服务器或本地网络', 'NETWORK_TIMEOUT')`，由登录页和守卫统一走网络错误/重试路径。
- 新增 `AuthHungRequest.test.tsx`：先以永久 pending 的 `/me` 和 `/login` 请求复现两个卡死症状，修复后断言加载态释放、登录按钮可重试。
- 代码级验证：Vitest 18 个文件 / 236 条用例通过，`tsc --noEmit` 通过，production build 通过。
- 真实手机锁屏恢复后重复登录、进入受保护页和移动录分仍需回验，因此本条不能关闭为 Field PASS。

## 关闭规则

1. 每条缺陷修复后保持最小改动，不做无关重构。
2. P1 必须在真实手机和 LAN 环境复验，不能只使用模拟器或 BrowserContext。
3. P2 修复后至少补对应页面级回归；不修复则必须在现场回执中继续登记为 P2。
4. 任何新增缺陷按 `复现 -> 留证据 -> 分级 -> 最小修复 -> 回验原场景` 处理。
5. 只有 DF-001 与 DF-005 关闭且新执行未发现 P0 / P1 后，才能恢复 Day6 Physical Field Gate 的正式判定。
