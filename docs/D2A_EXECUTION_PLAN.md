# A 轨 D2：认证鉴权与契约交付详细执行计划

> 状态：执行计划修订稿（A2.1 已完成；A2.2+ 按 PR #42 最新 C/D 轨反馈调整）
> 基线：`master@b8fe480`（PR #38 已合入）
> A2.1 已完成提交：`564e2d2`
> 工作分支：`feature/AuthAndPortalSkeleton`  
> PR 策略：D2 A 侧的全部后续实现、测试和文档都提交到同一个 PR，不新增第二个阶段 PR。
> 同步要求：进入 A2.2 前，必须先将 `origin/master` merge 到当前分支；禁止 rebase。

## 0. 本次修订摘要（2026-09-21）

1. A/C 前后端职责冻结：A 只负责认证后端、Session、权限依赖、赛事授权、用户管理和 OpenAPI contract；C 负责 LoginPage、AuthContext/Guard、403、EVENT_ADMIN 登录分流、AdminLayout/System 前端接入。
2. 同步 A/D/E 已确认的 Bootstrap 契约：持久化 `bootstrap_completed`；状态固定为 `NEEDS_INITIALIZATION`、`READY`、`RECOVERY_REQUIRED`；初始化入口仅服务器本机可用；初始化完成后不得因没有可用 `SYSTEM_ADMIN` 而重新开放 Web bootstrap。
3. `EVENT_ADMIN` 创建字段冻结为 `username`、`display_name`、`password`、`phone`（可选）、`note`（可选）；A 侧通过后续迁移将 `phone`、`note` 补为 nullable 字段。
4. 保留 `OWNER`、`ADMIN`、`OPERATOR`、`VIEWER` 赛事角色。C D2 只根据后端授权结果实现允许、只读、无权限 UI，不实现复杂权限编辑器。
5. `feature/AuthAndPortalSkeleton` 当前落后于 `origin/master@b8fe480`；A2.2 开始前先 merge 最新 master，避免与 #38 前端布局和路由冲突。

## 1. 阶段目标

D2 A 侧的验收结果固定为：

1. 用户、服务端会话、赛事级授权关系和赛事负责人字段可在空库与旧库中稳定创建。
2. `SYSTEM_ADMIN`、`EVENT_ADMIN` 可登录；浏览器 Cookie 与非浏览器 Bearer Token 均可工作。
3. 退出、改密、账号停用和会话过期会立即阻断旧会话。
4. `SYSTEM_ADMIN` 不自动获得赛事业务写权限。
5. `EVENT_ADMIN` 创建赛事后自动成为该赛事 `OWNER`。
6. `EVENT_ADMIN` 只能读取、管理自己创建或被明确授权的赛事。
7. 未登录访问管理写接口返回 `401`；系统角色不足返回 `403`；跨赛事资源访问统一返回 `404`，不泄露资源存在性。
8. A 轨交付稳定认证、授权与 OpenAPI contract；Admin、Public、System 前端路由和页面由 C 轨按该 contract 接入，A 轨不重复实现前端。
9. A 轨认证专项测试、全量后端测试、OpenAPI 生成与契约冻结均有可复核证据；前端构建证据由 C 轨提供并在 A2.7 汇总，不作为 A 轨源码交付物。

## 2. 本轮严格不做

- 不实现公开报名、报名审核、报名状态机。
- 不实现 Affiliation、Organization、Venue。
- 不实现赛事生命周期 `DRAFT/PUBLISHED/RUNNING/ARCHIVED` 的完整业务动作。
- 不实现系统管理端的用户增删改、备份、恢复和迁移管理页面。
- 不重构现有赛事业务页。
- 不改变赛事业务规则、排名算法、赛制处理器或比分规则。
- 不引入 ORM、JWT、OAuth、短信登录或新的第三方密码库。
- 不实现或修改 C 轨拥有的 `LoginPage`、`AuthContext`、前端 Guard、403 页面、AdminLayout 和 System 前端页面。
- 不在 A 轨重复生成前端认证组件；OpenAPI 类型由 C 轨按稳定契约生成。

## 3. 已冻结的最小契约

### 3.1 API

| 方法 | 路径 | 成功 | 说明 |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | `200` | `browser` 设置 `pp_session` Cookie；`bearer` 返回 `access_token` |
| `POST` | `/api/v1/auth/logout` | `204` | 撤销当前会话并清除 Cookie；重复退出保持幂等 |
| `GET` | `/api/v1/auth/me` | `200` | 返回当前用户与赛事授权数量，不返回密码或 Token 哈希 |
| `POST` | `/api/v1/auth/change-password` | `204` | 校验当前密码；成功后撤销该用户全部旧会话 |
| `GET` | `/api/v1/system/bootstrap/status` | `200` | 只返回 `NEEDS_INITIALIZATION`、`READY` 或 `RECOVERY_REQUIRED`，不返回敏感数据 |
| `POST` | `/api/v1/system/bootstrap` | `201` | 仅服务器本机调用；原子创建第一个 `SYSTEM_ADMIN` 并写入 `bootstrap_completed=true` |
| `POST` | `/api/v1/system/users` | `201` | 仅 `SYSTEM_ADMIN` 调用；创建 `EVENT_ADMIN` |

旧 `/api/*` 保留，不在 D2 中整体迁移到 `/api/v1`。认证接口使用 `/api/v1`；赛事业务接口继续使用现有 `/api`，但写操作用于服务端强制鉴权。

### 3.1.1 Bootstrap 系统状态

- 系统状态必须在数据库中持久化，新增单例系统状态记录 `bootstrap_completed`，不得以 `COUNT(SYSTEM_ADMIN)` 作为入口开关。
- 全新数据库 `bootstrap_completed=false`；首次初始化必须在同一事务内创建第一个 `SYSTEM_ADMIN` 并置为 `true`。
- 初始化完成后永久关闭 Web bootstrap；即使最后一个 `SYSTEM_ADMIN` 被停用或不可用，也只能进入 `RECOVERY_REQUIRED`，通过服务器本机恢复流程处理。
- `/api/v1/system/bootstrap` 仅接受服务器本机连接；局域网客户端调用返回 `404 RESOURCE_NOT_FOUND`，不泄露初始化入口。
- `GET /api/v1/system/bootstrap/status` 可用于前端只读分流，允许局域网访问，但不得返回账号、路径或恢复信息。
- 状态固定为：
  - `NEEDS_INITIALIZATION`：`bootstrap_completed=false`；
  - `RECOVERY_REQUIRED`：`bootstrap_completed=true` 且不存在 active `SYSTEM_ADMIN`；
  - `READY`：`bootstrap_completed=true` 且至少存在一个 active `SYSTEM_ADMIN`。

### 3.1.2 SYSTEM_ADMIN 创建 EVENT_ADMIN

- 创建请求字段冻结为 `username`、`display_name`、`password`、`phone`（可选）、`note`（可选）。
- `username` 全局唯一且大小写不敏感；数据库只保存 `password_hash`；`phone`、`note` 不参与认证。
- A2.1 已提交的迁移版本 2 不追溯改写；A2.2 新增迁移版本 3，为 `users` 增加 nullable `phone`、`note`。
- `EVENT_ADMIN` 创建与赛事 `TournamentAdmin` 授权保持分离，创建账号本身不授予任何赛事权限。

### 3.2 会话

- 服务端不透明 Session Token，默认有效期 12 小时。
- Cookie 名固定为 `pp_session`，属性为 `HttpOnly`、`SameSite=Lax`、`Path=/`；HTTPS 环境追加 `Secure`。
- 同时接受 Cookie 与 `Authorization: Bearer <token>`。
- 同一请求两种凭据指向不同会话时必须拒绝。
- 数据库只保存 Token 的 SHA-256 哈希。
- 退出、账号停用、改密后旧会话立即不可用。
- 每次鉴权必须重新检查 `users.active`；`active=false` 后，已签发 Cookie/Bearer Token 也不得继续访问。
- 停用账号与撤销该用户全部有效 Session 必须在同一事务内完成。

### 3.3 密码

- `PBKDF2-HMAC-SHA256`，使用 Python 标准库。
- 每个密码独立随机盐，校验使用 `hmac.compare_digest`。
- 格式：`pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`。
- 默认迭代次数 `600000`，允许通过环境变量覆盖。
- 新密码至少 12 个字符，并至少包含字母和数字；禁止空白密码和明文回退。

### 3.4 角色与资源权限

系统角色：

- `SYSTEM_ADMIN`：系统账号、配置、备份恢复等系统能力；不自动获得赛事业务写权限。
- `EVENT_ADMIN`：可创建赛事，并管理自己创建或被授权的赛事。

赛事角色：

| 赛事角色 | 读赛事 | 写赛事业务数据 | 管理赛事授权 |
|---|---:|---:|---:|
| `OWNER` | 是 | 是 | 是 |
| `ADMIN` | 是 | 是 | 是 |
| `OPERATOR` | 是 | 是 | 否 |
| `VIEWER` | 是 | 否 | 否 |

赛事创建时同一事务写入 `tournaments.owner_user_id` 和 `tournament_admins(role='OWNER')`。

C 轨 D2 不实现复杂权限编辑器；前端只根据后端返回的允许、只读或无权限结果展示 UI，真实权限始终以后端为准。

### 3.5 错误语义

| 场景 | HTTP | 稳定错误码 |
|---|---:|---|
| 未登录、会话过期、会话撤销 | `401` | `AUTH_REQUIRED` |
| 登录用户名、密码或账号状态错误 | `401` | `AUTH_INVALID_CREDENTIALS` |
| 有效登录但系统角色不足 | `403` | `FORBIDDEN` |
| 资源不存在或当前用户无权访问该资源 | `404` | `RESOURCE_NOT_FOUND` |
| bootstrap 已完成或并发初始化失败 | `409` | `BOOTSTRAP_ALREADY_COMPLETED` |
| 已初始化但无可用系统管理员 | `409` | `RECOVERY_REQUIRED` |
| 非本机访问 bootstrap 写接口 | `404` | `RESOURCE_NOT_FOUND` |

## 4. 工作包、顺序与交付物

### A2.1 版本化迁移与认证数据模型

状态：已完成（提交 `564e2d2`；专项测试 `7 passed`）。

依赖：无。

实施内容：

1. 新增 `backend/app/migrations.py`，建立 `schema_migrations`。
2. 版本 1 登记当前 master 基线，不重复建现有业务表。
3. 版本 2 创建：
   - `users`
   - `user_sessions`
   - `tournament_admins`
   - `tournaments.owner_user_id`
4. 在 `backend/app/db.py::init_db()` 的现有基线升级完成后调用迁移入口。
5. 对每个版本使用独立事务；执行后运行 `PRAGMA foreign_key_check`。
6. 用户名使用 `COLLATE NOCASE UNIQUE`；同一用户在同一赛事只有一条授权记录。

交付文件：

- `backend/app/migrations.py`
- `backend/app/db.py`
- `backend/tests/test_schema_migrations.py`
- `backend/tests/test_auth_schema.py`

验收测试：

- 空库首次启动创建全部表与迁移记录。
- 当前旧库副本升级后历史数据行数不变。
- 重复执行 `init_db()` 不重复迁移、不报错。
- 用户名大小写重复被拒绝。
- `tournament_admins(user_id, tournament_id)` 重复被拒绝。
- `users`、`user_sessions`、`tournament_admins`、`tournaments.owner_user_id` 外键检查通过。

### A2.2 安全基础、Bootstrap 状态与认证服务

依赖：A2.1，且已 merge `origin/master@b8fe480`。

实施内容：

1. 新增 `backend/app/security.py`，实现密码哈希、密码校验、Token 生成和 Token 哈希。
2. 新增迁移版本 3：
   - 创建单例系统状态记录 `bootstrap_completed`；
   - 为 `users` 增加 nullable `phone`、`note`。
3. 在 SQL 访问层增加用户、会话、授权关系和系统状态的查询与写入函数。
4. 新增认证服务，统一处理：
   - 登录成功创建 Session；
   - 登录失败统一凭据错误；
   - 当前会话读取与 `last_seen_at` 更新；
   - 退出撤销；
   - 改密校验、更新哈希、撤销全部旧会话；
   - 过期、撤销、停用账号的会话判定；
   - 停用账号时同事务撤销全部有效 Session；
   - 原子 bootstrap：检查 `bootstrap_completed=false`、创建首个 `SYSTEM_ADMIN`、写入完成状态。
5. Session 时间统一使用 UTC ISO 8601，API 返回带时区时间。
6. bootstrap 状态计算固定为 `NEEDS_INITIALIZATION`、`READY`、`RECOVERY_REQUIRED`，不得回退到“统计管理员数量”作为入口开关。

交付文件：

- `backend/app/migrations.py`
- `backend/app/security.py`
- `backend/app/services/auth.py`
- `backend/app/repository.py`
- `backend/tests/test_security.py`
- `backend/tests/test_auth_service.py`
- `backend/tests/test_bootstrap_service.py`

验收测试：

- 相同密码生成不同哈希。
- 正确/错误密码、损坏哈希、未知算法测试。
- Token 只存 SHA-256 哈希。
- 过期、撤销、停用用户会话不可用。
- 改密后旧 Session 全部失效。
- `active=false` 后旧 Cookie/Bearer Token 不再可用，且停用时历史 Session 被撤销。
- 全新数据库首次 bootstrap 成功且 `bootstrap_completed=true`。
- 连续两次或并发 bootstrap 只能成功一次。
- 初始化后重启、已初始化版本备份恢复均不重新开放 bootstrap。
- 旧项目数据库升级到迁移版本 3 后赛事数据保留，且 `bootstrap_completed=false`。
- `bootstrap_completed=true` 且无 active `SYSTEM_ADMIN` 时状态为 `RECOVERY_REQUIRED`，恢复不能走 Web bootstrap。

### A2.3 认证 API、Bootstrap API 与系统用户接口

依赖：A2.2。

实施内容：

1. 新增 `backend/app/routers/auth.py`，并新增或扩展系统 Router。
2. 在 `backend/app/main.py` 注册认证与系统 Router。
3. 在 `backend/app/schemas.py` 增加登录、当前用户、改密、bootstrap 状态/初始化请求、`EVENT_ADMIN` 创建 DTO。
4. 实现 Cookie 设置和清除，保持 Bearer 响应不设置明文 Token 到 Cookie。
5. 对认证失败统一返回稳定错误码；业务接口不泄露密码哈希、Token 和会话内部字段。
6. 实现 `GET /api/v1/system/bootstrap/status`，只返回三种冻结状态之一。
7. 实现 `POST /api/v1/system/bootstrap`：
   - 仅接受服务器本机连接，不信任 `X-Forwarded-For` 等可伪造请求头；
   - 原子创建首个 `SYSTEM_ADMIN`；
   - 已初始化、并发失败或 `RECOVERY_REQUIRED` 时绝不重复创建 Web 管理员；
   - 非本机访问按 `404 RESOURCE_NOT_FOUND` 处理。
8. 实现 `POST /api/v1/system/users`，仅允许 `SYSTEM_ADMIN` 创建 `EVENT_ADMIN`，字段固定为 `username`、`display_name`、`password`、`phone`、`note`。
9. A 轨不新增或修改 C 轨前端文件。

交付文件：

- `backend/app/routers/auth.py`
- 系统用户 Router（文件路径在 A2.3 实现前冻结）
- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/tests/test_auth_api.py`
- `backend/tests/test_bootstrap_api.py`
- `backend/tests/test_system_users_api.py`

验收测试：

- 浏览器模式登录返回 `Set-Cookie: pp_session=...; HttpOnly; SameSite=lax; Path=/`。
- Bearer 模式返回 `access_token`，数据库只能查到其哈希。
- 错误密码、停用账号、未知用户均返回同一种 `401 AUTH_INVALID_CREDENTIALS`。
- `/auth/me` 未登录返回 `401 AUTH_REQUIRED`，登录后不返回敏感字段。
- 改密需要当前密码；成功后返回 `204`，旧会话失效。
- 退出返回 `204` 且重复退出不报错。
- bootstrap 状态只返回三种冻结值，初始化完成后重启入口不再出现。
- 非本机 bootstrap 请求被拒绝；本机首次初始化成功，连续两次只能成功一次。
- `RECOVERY_REQUIRED` 时 Web bootstrap 始终拒绝。
- `SYSTEM_ADMIN` 创建 `EVENT_ADMIN` 时 `phone`、`note` 可为空，响应不含密码哈希或 Token。
- `EVENT_ADMIN` username 全局大小写不敏感，冲突返回稳定业务错误。
- 停用账号后旧 Cookie/Bearer Token 返回 `401 AUTH_REQUIRED`。

### A2.4 统一鉴权依赖与资源授权

依赖：A2.2、A2.3。

实施内容：

1. 新增 `backend/app/dependencies.py`。
2. 实现：
   - `get_current_user`
   - `require_system_admin`
   - `require_event_admin`
   - `get_tournament_access`
   - `require_tournament_read`
   - `require_tournament_write`
3. 赛事级依赖根据 `tournament_id` 查询授权；Match 类接口根据 `match_id` 反查赛事。
4. `SYSTEM_ADMIN` 不因系统角色自动通过赛事写权限。
5. 不存在赛事与无权赛事使用同一个 `404 RESOURCE_NOT_FOUND`。
6. `get_current_user` 每次请求必须检查 `users.active`；停用账号即使 Session 记录仍存在，也统一返回 `401 AUTH_REQUIRED`。
7. 使用 FastAPI 依赖缓存，避免同一请求重复查询当前用户。

交付文件：

- `backend/app/dependencies.py`
- `backend/tests/test_auth_dependencies.py`

验收测试：

- 无凭据、过期凭据、撤销凭据。
- `SYSTEM_ADMIN` 可进入系统级依赖，但访问赛事写接口失败。
- `EVENT_ADMIN` 对自有赛事可写。
- 第二 `EVENT_ADMIN` 对他人赛事返回 `404`，而不是泄漏赛事存在性。
- `VIEWER` 可读不可写。
- `active=false` 后旧 Cookie/Bearer Token 均不可继续访问。

### A2.5 赛事创建归属与现有写接口接入

依赖：A2.4。

实施内容：

1. 修改 `repository.create_tournament()`，支持 `owner_user_id`。
2. 修改 `create_tournament_with_tables()`，在同一事务写入 Owner 授权。
3. `POST /api/tournaments` 仅允许 `EVENT_ADMIN`，并传入当前用户。
4. 赛事列表只返回当前用户有权限的赛事；详情和写接口按赛事重新校验。
5. 对现有赛事写 Router 接入 `require_tournament_write`：
   - tournaments 删除
   - players
   - entries
   - groups
   - seeds
   - demo
   - matches
   - scheduling
   - scores
   - qualification_decisions
   - knockout
   - teams
   - team_roster
   - team_ties
   - team_qualification
   - team_knockout
6. Match 类写接口通过 `match_id -> tournament_id` 做资源校验。
7. 历史无 Owner 赛事不自动授予所有管理员；默认保持不可见，后续通过显式认领或迁移策略处理。

测试兼容策略：

- `client` Fixture 创建测试 `EVENT_ADMIN`、登录并携带 Bearer Token。
- 认证专项测试另建匿名 Client，不使用已登录 Fixture。
- 不增加生产环境鉴权旁路。

交付文件：

- `backend/app/repository.py`
- `backend/app/services/tournaments.py`
- `backend/app/routers/*.py`
- `backend/tests/conftest.py`
- `backend/tests/test_auth_authorization.py`
- `backend/tests/test_tournament_ownership.py`

验收测试：

- 未登录调用任一战事管理写接口返回 `401`。
- `EVENT_ADMIN` 创建赛事后，`owner_user_id` 与 `OWNER` 授权同时存在。
- 伪造其他赛事 ID 无法读、改、删。
- 列表不返回未授权赛事。
- 原有业务测试在登录 Fixture 下等价通过。

### A2.6 认证契约交接与 C 轨前端协作

依赖：A2.3 的稳定响应模型与 A2.4 的权限语义。

职责边界：

- C 轨拥有 LoginPage、AuthContext/Guard、403、EVENT_ADMIN 登录分流、AdminLayout、System 前端页面及前端路由接入。
- A 轨拥有后端认证、Session、权限依赖、赛事授权、系统用户接口和 OpenAPI contract。
- A 轨不新增或修改 C 轨拥有的前端文件；如 contract 必须变化，先更新 OpenAPI 与变更说明，再通知 C 轨调整。
- PR #38 已合入 `master@b8fe480`，A2.2 开始前先 merge 最新 master，不抢改布局文件。

实施内容：

1. 固化登录、退出、当前用户、改密、bootstrap、系统用户创建接口的请求/响应 DTO、Cookie 行为、错误码和权限语义。
2. 导出并校验 OpenAPI，确保 C 轨可直接生成客户端类型。
3. 将 `NEEDS_INITIALIZATION`、`READY`、`RECOVERY_REQUIRED` 以及 `/setup` 仅本机的边界写入 contract 交付说明。
4. 明确 C 轨只消费后端允许/只读/无权限结果，不实现复杂权限编辑器。
5. 增加 OpenAPI 契约测试，防止敏感字段、错误码或状态枚举被静默改坏。
6. 不修改 `frontend/src/**`。

交付文件：

- `docs/openapi-v0.2.json`
- `backend/tests/test_openapi_auth_contract.py`
- A2.7 交付报告中的 C 轨接入说明

验收测试：

- C 轨可从 OpenAPI 获得全部认证、bootstrap、系统用户接口及 DTO。
- bootstrap 三状态、local-only 入口、active=false 会话失效语义在 contract 中可验证。
- A 轨没有修改 C 轨拥有的前端文件。
- contract 冻结后若需变更，已有明确版本化说明和通知机制。

### A2.7 契约、测试与交付证据

依赖：A2.1-A2.6。

实施内容：

1. 更新 OpenAPI 导出文件。
2. 通知 C 轨从冻结后的 OpenAPI 重新生成 TypeScript 类型；A 轨不修改 `frontend/src/**`。
3. 更新 D2 执行进度文档。
4. 汇总所有命令、结果、失败、风险和未覆盖场景。
5. 汇总 C 轨提供的前端 build 与 contract 检查证据。
6. 只在当前唯一 PR 中追加修改报告，不修改初始 PR 正文。

A 轨必须运行：

```powershell
# backend
C:\Users\lenovo\Desktop\乒乓球平台\辅助生成文件\.venv-v03-a\Scripts\python.exe -m pytest

# contract
python backend/export_openapi.py
```

C 轨提供以下证据：

```powershell
# frontend
pnpm build
pnpm contract:check
```

验收证据：

- 认证专项 pytest 全通过。
- 后端全量 pytest 全通过。
- OpenAPI 可生成且认证契约测试通过。
- C 轨前端 build 与 contract 检查通过。
- 已知未冻结项没有被代码静默绕过。

## 5. 文件级执行顺序

0. 先 merge `origin/master@b8fe480`，解决冲突并运行基线测试。
1. `backend/app/migrations.py`
2. `backend/app/db.py`
3. `backend/app/security.py`
4. `backend/app/repository.py`
5. `backend/app/services/auth.py`
6. `backend/app/dependencies.py`
7. `backend/app/schemas.py`
8. `backend/app/routers/auth.py`
9. 系统用户 Router
10. `backend/app/main.py`
11. `backend/app/services/tournaments.py`
12. 现有写 Router
13. `backend/tests/conftest.py`
14. 认证、bootstrap、系统用户与授权测试
15. `docs/openapi-v0.2.json`
16. 进度、契约交接与 C 轨证据汇总文档

## 6. 测试分批策略

### 第一批：迁移与安全基础

- schema migration 与迁移版本 3 测试
- password hash 测试
- session service 与 `active=false` 会话失效测试
- bootstrap service / API 测试
- 认证 API 测试

### 第二批：授权

- 依赖单元测试
- 赛事 Owner 创建测试
- 跨赛事越权测试
- 现有业务 Router 的认证回归
- 系统用户创建与 username 冲突测试

### 第三批：全量回归与契约

- 全量 `pytest`
- OpenAPI 导出与认证契约测试
- C 轨前端 `build` 与 `contract:check` 证据

每批通过后才能进入下一批；如果全量测试失败，必须在 D2 交付文档列出失败用例，不虚报完成。

## 7. 风险与阻塞

| 风险 | 影响 | 处理策略 |
|---|---|---|
| 第 10 节契约尚未逐项打勾 | D2 实施存在评审返工 | 本 PR 先固化执行计划；代码只实现本计划明确项，不扩展未冻结内容 |
| PR #38 已合入 `master@b8fe480`，A2.6 前端职责曾重叠 | 当前分支落后 master，前端文件可能冲突 | A 不修改 C 拥有的前端文件；A2.2 前先 merge 最新 master；前端接入由 C 完成 |
| bootstrap 状态未持久化 | 管理员全部停用后可能重新暴露初始化入口 | 使用单例系统状态；初始化与首个管理员创建同事务；无 active `SYSTEM_ADMIN` 仅进入 `RECOVERY_REQUIRED` |
| 局域网误访问 bootstrap | 首个管理员可能被远端抢占 | 写入口仅允许服务器本机；测试覆盖 loopback/非 loopback，不信任代理头 |
| 已初始化备份恢复 | 若状态未随备份持久化会重开 bootstrap | `bootstrap_completed` 入库；验收覆盖已初始化版本备份恢复 |
| `active=false` 未覆盖旧 token | 被停用管理员继续访问 | 每次鉴权检查 active；停用同事务撤销全部 Session；增加旧 Cookie/Bearer 测试 |
| 旧赛事没有 `owner_user_id` | 历史赛事可见性未定 | D2 默认不可见；另立显式认领/迁移方案，不批量授权 |
| 旧 `/api` 写接口强制鉴权影响 B/C/D 轨 | 现有调用和测试可能中断 | 当前 D2 PR 统一改造测试 Fixture；合入前通知其他轨道并观察依赖页面 |
| Cookie + 局域网 HTTP 与 CSRF | 浏览器会话安全边界未确认 | 保持 `HttpOnly/SameSite=Lax`；HTTPS 追加 `Secure`；若需要跨站 Cookie 必须先评审 CSRF |
| `SYSTEM_ADMIN` 的排障读权限 | 可能误读赛事隐私 | D2 默认无赛事业务权限；临时权限必须另做显式授权与审计 |
| 全量测试体量较大 | 单次运行可能超时 | 先跑定向测试，再在交付前运行一次完整 pytest 并保留日志 |

## 8. 完成判定

只有同时满足以下条件，D2 A 侧才标记完成：

- A2.1-A2.7 全部有代码或文档交付物。
- 所有验收测试与检查有日志、命令和结果。
- 当前唯一 PR 已收口，没有擅自新增第二个 D2 PR。
- 未完成、阻塞、已知风险在交付报告中明确列出。
- 用户对最终 diff、测试结果和风险完成人工审核后，才进行对应 Git 操作。

## 9. 当前进度

当前进度：`2/7（约 29%）`。

- A2.1：已完成，提交 `564e2d2`；专项测试 `7 passed`。
- A2.2：已完成实现与专项验收；新增迁移版本 3、持久化 bootstrap 状态、`phone/note` 字段、原子首次初始化、账号停用与会话撤销；认证专项测试 `28 passed`。
- A2.3：待实施；当前工作区已有一版未完成草稿，其提前对赛事 API 加鉴权会使旧 API 测试因未登录返回 `401`，需在 A2.3 统一补齐登录测试夹具与 Router 注册后再跑全量回归。
- A2.4：待实施。
- A2.5：待实施。
- A2.6：职责已调整为契约交接；前端实现归 C 轨，等待认证 contract 冻结。
- A2.7：未开始。

本文件代表 A2.1、A2.2 已完成；A2.3-A2.7 仍按修订后的执行顺序和验收边界实施。
