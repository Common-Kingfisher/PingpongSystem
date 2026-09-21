# A 轨 D2：认证鉴权与三端骨架详细执行计划

> 状态：执行计划冻结稿（本轮仅建立唯一 PR，不实施代码）  
> 基线：`master@34fd8b7`  
> 工作分支：`feature/AuthAndPortalSkeleton`  
> PR 策略：D2 A 侧的全部后续实现、测试和文档都提交到同一个 PR，不新增第二个阶段 PR。

## 1. 阶段目标

D2 A 侧的验收结果固定为：

1. 用户、服务端会话、赛事级授权关系和赛事负责人字段可在空库与旧库中稳定创建。
2. `SYSTEM_ADMIN`、`EVENT_ADMIN` 可登录；浏览器 Cookie 与非浏览器 Bearer Token 均可工作。
3. 退出、改密、账号停用和会话过期会立即阻断旧会话。
4. `SYSTEM_ADMIN` 不自动获得赛事业务写权限。
5. `EVENT_ADMIN` 创建赛事后自动成为该赛事 `OWNER`。
6. `EVENT_ADMIN` 只能读取、管理自己创建或被明确授权的赛事。
7. 未登录访问管理写接口返回 `401`；系统角色不足返回 `403`；跨赛事资源访问统一返回 `404`，不泄露资源存在性。
8. 前端具备 Admin、Public、System 三端路由骨架；未登录或角色不符时不能进入受保护页面。
9. 认证专项测试、全量后端测试、前端构建、OpenAPI 生成和契约检查全部有可复核证据。

## 2. 本轮严格不做

- 不实现公开报名、报名审核、报名状态机。
- 不实现 Affiliation、Organization、Venue。
- 不实现赛事生命周期 `DRAFT/PUBLISHED/RUNNING/ARCHIVED` 的完整业务动作。
- 不实现系统管理端的用户增删改、备份、恢复和迁移管理页面。
- 不重构现有赛事业务页。
- 不改变赛事业务规则、排名算法、赛制处理器或比分规则。
- 不引入 ORM、JWT、OAuth、短信登录或新的第三方密码库。

## 3. 已冻结的最小契约

### 3.1 API

| 方法 | 路径 | 成功 | 说明 |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | `200` | `browser` 设置 `pp_session` Cookie；`bearer` 返回 `access_token` |
| `POST` | `/api/v1/auth/logout` | `204` | 撤销当前会话并清除 Cookie；重复退出保持幂等 |
| `GET` | `/api/v1/auth/me` | `200` | 返回当前用户与赛事授权数量，不返回密码或 Token 哈希 |
| `POST` | `/api/v1/auth/change-password` | `204` | 校验当前密码；成功后撤销该用户全部旧会话 |

旧 `/api/*` 保留，不在 D2 中整体迁移到 `/api/v1`。认证接口使用 `/api/v1`；赛事业务接口继续使用现有 `/api`，但写操作用于服务端强制鉴权。

### 3.2 会话

- 服务端不透明 Session Token，默认有效期 12 小时。
- Cookie 名固定为 `pp_session`，属性为 `HttpOnly`、`SameSite=Lax`、`Path=/`；HTTPS 环境追加 `Secure`。
- 同时接受 Cookie 与 `Authorization: Bearer <token>`。
- 同一请求两种凭据指向不同会话时必须拒绝。
- 数据库只保存 Token 的 SHA-256 哈希。
- 退出、账号停用、改密后旧会话立即不可用。

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

### 3.5 错误语义

| 场景 | HTTP | 稳定错误码 |
|---|---:|---|
| 未登录、会话过期、会话撤销 | `401` | `AUTH_REQUIRED` |
| 登录用户名、密码或账号状态错误 | `401` | `AUTH_INVALID_CREDENTIALS` |
| 有效登录但系统角色不足 | `403` | `FORBIDDEN` |
| 资源不存在或当前用户无权访问该资源 | `404` | `RESOURCE_NOT_FOUND` |

## 4. 工作包、顺序与交付物

### A2.1 版本化迁移与认证数据模型

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

### A2.2 密码、会话与认证服务

依赖：A2.1。

实施内容：

1. 新增 `backend/app/security.py`，实现密码哈希、密码校验、Token 生成和 Token 哈希。
2. 在 SQL 访问层增加用户、会话、授权关系的查询与写入函数。
3. 新增认证服务，统一处理：
   - 登录成功创建 Session；
   - 登录失败统一凭据错误；
   - 当前会话读取与 `last_seen_at` 更新；
   - 退出撤销；
   - 改密校验、更新哈希、撤销全部旧会话；
   - 过期、撤销、停用账号的会话判定。
4. Session 时间统一使用 UTC ISO 8601，API 返回带时区时间。

交付文件：

- `backend/app/security.py`
- `backend/app/services/auth.py`
- `backend/app/repository.py`
- `backend/tests/test_security.py`
- `backend/tests/test_auth_service.py`

验收测试：

- 相同密码生成不同哈希。
- 正确/错误密码、损坏哈希、未知算法测试。
- Token 只存 SHA-256 哈希。
- 过期、撤销、停用用户会话不可用。
- 改密后旧 Session 全部失效。

### A2.3 认证 API 与统一错误

依赖：A2.2。

实施内容：

1. 新增 `backend/app/routers/auth.py`。
2. 在 `backend/app/main.py` 注册认证 Router。
3. 在 `backend/app/schemas.py` 增加登录、用户、当前用户、改密 DTO。
4. 实现 Cookie 设置和清除，保持 Bearer 响应不设置明文 Token 到 Cookie。
5. 对认证失败统一返回稳定错误码；业务接口不泄露密码哈希、Token 和会话内部字段。

交付文件：

- `backend/app/routers/auth.py`
- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/tests/test_auth_api.py`

验收测试：

- 浏览器模式登录返回 `Set-Cookie: pp_session=...; HttpOnly; SameSite=lax; Path=/`。
- Bearer 模式返回 `access_token`，数据库只能查到其哈希。
- 错误密码、停用账号、未知用户均返回同一种 `401 AUTH_INVALID_CREDENTIALS`。
- `/auth/me` 未登录返回 `401 AUTH_REQUIRED`，登录后不返回敏感字段。
- 改密需要当前密码；成功后返回 `204`，旧会话失效。
- 退出返回 `204` 且重复退出不报错。

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
6. 使用 FastAPI 依赖缓存，避免同一请求重复查询当前用户。

交付文件：

- `backend/app/dependencies.py`
- `backend/tests/test_auth_dependencies.py`

验收测试：

- 无凭据、过期凭据、撤销凭据。
- `SYSTEM_ADMIN` 可进入系统级依赖，但访问赛事写接口失败。
- `EVENT_ADMIN` 对自有赛事可写。
- 第二 `EVENT_ADMIN` 对他人赛事返回 `404`，而不是泄漏赛事存在性。
- `VIEWER` 可读不可写。

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

### A2.6 三端前端路由骨架

依赖：A2.3 的稳定响应模型与 A2.4 的权限语义。

并行约束：

- 现有开放 PR #38 已创建 `AdminLayout`、`AdminDashboardPage`，与本工作包重叠。
- 不重复创建同义组件，不与 #38 争抢同一文件。
- 先等待 #38 合并或明确采用其布局；随后在当前 D2 PR 中只接入认证状态、角色守卫和三端分组。

实施内容：

1. 新增认证客户端和 Auth Context，Cookie 请求使用 `credentials: 'include'`。
2. 新增登录页和会话失效处理。
3. 复用已合入的管理端 Layout，不重写现有业务页。
4. 增加公共端只读路径分组与 System 入口占位页。
5. 对现有路由按 D1 路由矩阵归类：
   - Admin：首页、选手与分组、赛前检查、控制台、排名、淘汰赛、团体管理、打印等。
   - Public：赛程、大屏、冠军之路、秩序册、报名入口。
   - System：系统状态、会话信息占位；不加入赛事写操作。
6. 未登录访问 Admin 或 System 页面重定向登录；角色不符显示无权限页。
7. 前端守卫只改善体验，最终权限仍以后端为准。

交付文件：

- `frontend/src/auth/*`
- `frontend/src/layouts/*`（仅在 #38 合并后复用或增量修改）
- `frontend/src/pages/LoginPage.tsx`
- `frontend/src/pages/SystemPage.tsx`
- `frontend/src/App.tsx`
- 对应前端测试或至少 `npm/pnpm build` 证据

验收测试：

- 登录角色分流正确。
- 直接访问受保护 URL 被拦截。
- Cookie 凭据在开发代理和同源部署下生效。
- 现有业务页构建通过。

### A2.7 契约、测试与交付证据

依赖：A2.1-A2.6。

实施内容：

1. 更新 OpenAPI 导出文件。
2. 重新生成前端 OpenAPI TypeScript 类型。
3. 更新 D2 执行进度文档。
4. 汇总所有命令、结果、失败、风险和未覆盖场景。
5. 只在当前唯一 PR 中追加修改报告，不修改初始 PR 正文。

必须运行：

```powershell
# backend
C:\Users\lenovo\Desktop\乒乓球平台\辅助生成文件\.venv-v03-a\Scripts\python.exe -m pytest

# frontend
pnpm build

# contract
python backend/export_openapi.py
pnpm contract:check
```

验收证据：

- 认证专项 pytest 全通过。
- 后端全量 pytest 全通过。
- 前端 build 通过。
- OpenAPI 可生成且契约检查无 diff。
- 已知未冻结项没有被代码静默绕过。

## 5. 文件级执行顺序

1. `backend/app/migrations.py`
2. `backend/app/db.py`
3. `backend/app/security.py`
4. `backend/app/repository.py`
5. `backend/app/services/auth.py`
6. `backend/app/dependencies.py`
7. `backend/app/schemas.py`
8. `backend/app/routers/auth.py`
9. `backend/app/main.py`
10. `backend/app/services/tournaments.py`
11. 现有写 Router
12. `backend/tests/conftest.py`
13. 认证与授权测试
14. 前端认证与路由文件
15. `docs/openapi-v0.2.json`、`frontend/src/generated/openapi.d.ts`
16. 进度与交接文档

## 6. 测试分批策略

### 第一批：迁移与安全基础

- schema migration 测试
- password hash 测试
- session service 测试
- 认证 API 测试

### 第二批：授权

- 依赖单元测试
- 赛事 Owner 创建测试
- 跨赛事越权测试
- 现有业务 Router 的认证回归

### 第三批：全量回归与前端

- 全量 `pytest`
- 前端 `build`
- OpenAPI 导出与 `contract:check`

每批通过后才能进入下一批；如果全量测试失败，必须在 D2 交付文档列出失败用例，不虚报完成。

## 7. 风险与阻塞

| 风险 | 影响 | 处理策略 |
|---|---|---|
| 第 10 节契约尚未逐项打勾 | D2 实施存在评审返工 | 本 PR 先固化执行计划；代码只实现本计划明确项，不扩展未冻结内容 |
| PR #38 与 A2.6 重叠 | 路由/布局文件冲突 | 不争抢布局文件；等待 #38 合并后再接入认证守卫 |
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

初始进度：`0/7（0%）`。

- A2.1：未开始或待按本计划整理迁移草稿。
- A2.2：未开始。
- A2.3：未开始。
- A2.4：未开始。
- A2.5：未开始。
- A2.6：未开始，等待 PR #38 协调。
- A2.7：未开始。

本文件只冻结执行顺序和验收边界，不代表上述实现已经完成。
