# D7A V0.3 数据库 Schema 冻结说明

> 轨道：A 轨（后端 / 权限 / 数据模型 / 迁移与事务）
>
> 状态：D7A 发布候选冻结文档
>
> 冻结日期：2026-09-23
>
> 冻结基线：`origin/master` = `68e7a65f01a4a0d22707cad17aad103ed89e914a`
>
> 当前迁移版本：`v5`
>
> OpenAPI 快照：`docs/openapi-v0.2.json`

## 1. 冻结结论

V0.3 的以下契约进入发布候选冻结状态：

- SQLite 数据库结构；
- migration v1-v5 的版本和语义；
- 系统角色与赛事级权限角色；
- API 请求和响应结构对应的 OpenAPI 快照。

本次冻结不修改生产 Schema。除 E7 最终 RC review 明确确认的 P0，或明确升级为发布阻断的 P1 外，D7A 不再新增或修改业务表、列、CHECK 枚举、外键、API 字段和权限语义。

该冻结是 A 轨交付基线，不代表 E7 最终 release gate 已完成。E7 仍需完成最终 review、专项复验和 P0=0 确认。

## 2. 冻结范围

### 2.1 SQL Schema 来源

以下文件是 V0.3 SQLite Schema 与 API Schema 的唯一代码来源：

```text
backend/app/db.py
backend/app/migrations.py
backend/app/models.py
backend/app/schemas.py
docs/openapi-v0.2.json
```

冻结期间，上述文件的生产 Schema 相关 diff 应保持为 0。

### 2.2 当前 migration 链

```text
v1  master baseline
v2  auth_users_and_admins
v3  bootstrap_state_and_user_profile
v4  tournament_format_config
v5  registration_organization_venue
```

当前 `schema_migrations` 的最大版本为 `5`。v1-v5 是已发布历史链，不得重写、压平或直接修改其 SQL 语义。

### 2.3 当前数据库表

当前全新初始化数据库包含以下 22 张业务或框架表：

```text
entries
entry_members
groups
match_games
matches
organizations
players
qualification_decisions
registrations
schema_migrations
score_audits
score_requests
system_state
tables
team_qualifications
team_rubbers
team_ties
tournament_admins
tournaments
user_sessions
users
venues
```

恢复校验使用的 `REQUIRED_TABLES` 与上述当前表集合一致，共 22 张，不存在遗漏。

## 3. 冻结的业务约束

### 3.1 角色枚举

系统角色 `SystemRole`：

```text
SYSTEM_ADMIN
EVENT_ADMIN
```

赛事级角色 `TournamentRole`：

```text
OWNER
ADMIN
OPERATOR
VIEWER
```

冻结要求：

- `EVENT_ADMIN` 只能管理被明确授权的赛事；
- `SYSTEM_ADMIN` 不自动获得赛事写权限；
- 跨赛事访问必须继续由赛事级授权检查阻断；
- Public 只能读取允许公开的数据，不能读取联系方式列表；
- Public Registration 只能创建 `PENDING` 报名。

### 3.2 赛事与报名枚举

赛事阶段 `TournamentStage`：

```text
REGISTRATION
GROUP_STAGE
KNOCKOUT
FINISHED
```

赛事项目 `EventType`：

```text
SINGLES
DOUBLES
TEAM
```

赛制代码 `format_code`：

```text
ROUND_ROBIN
SINGLE_ELIMINATION
GROUP_KNOCKOUT
NULL
```

报名状态 `RegistrationStatus`：

```text
PENDING
CONFIRMED
```

报名状态一致性 CHECK 同时约束 `status`、`confirmed_at` 和 `confirmed_player_id` 的组合，不允许出现半确认状态。

### 3.3 比赛与结果枚举

比赛状态 `MatchStatus`：

```text
WAITING
PLAYING
FINISHED
```

比赛赛段 `MatchStage`：

```text
GROUP
KNOCKOUT
```

比赛结果类型 `ResultType`：

```text
NORMAL
FORFEIT
WALKOVER
NO_SHOW
DISQUALIFIED
```

球台状态 `TableStatus`：

```text
FREE
OCCUPIED
```

上述枚举值进入 V0.3 冻结范围。新增 `Swiss`、双败淘汰、支付、赞助、酒店、通知、复杂邀请 token、`ARCHIVED` 生命周期等结构均不进入 V0.3 RC，统一进入 V0.4 或后续版本评估。

## 4. 关键完整性与幂等约束

### 4.1 比分请求

- `score_requests.request_id` 为主键；
- `score_audits.request_id` 有 partial unique index `uq_score_audits_request`；
- 相同请求编号的相同载荷必须保持业务幂等；
- 相同请求编号的不同载荷必须被拒绝，不能产生第二份业务事实。

### 4.2 人工晋级裁定

`qualification_decisions` 使用 partial unique index `uq_qualification_decision_active`：

```sql
CREATE UNIQUE INDEX uq_qualification_decision_active
ON qualification_decisions(group_id)
WHERE invalidated_at IS NULL
```

同一小组最多只能有一条有效裁决，并发提交和失败回滚都不能留下多个有效结果。

### 4.3 赛事配置

- `registration_enabled` 默认为 `0`，只允许 `0` 或 `1`；
- `format_code` 仅允许冻结的三种赛制代码或 `NULL`；
- `rule_config` 当前为 TEXT 契约，不通过 D7A 修改其版本语义；
- `rule_version` 为可空整数，若存在则必须大于等于 `1`。

### 4.4 外键与事务

- 每个请求使用独立 SQLite 连接；
- 连接强制启用 `PRAGMA foreign_keys = ON`；
- 迁移版本在独立事务中执行；
- 迁移后执行 `PRAGMA foreign_key_check`，有违规时回滚该版本；
- 关键业务写入必须继续通过事务测试。

## 5. 冻结后的变更规则

### 5.1 允许的事项

- 补充文档、操作说明和验证证据；
- 增加不改变契约的回归测试；
- 修复已由 E7 确认的 P0，或明确认定为发布阻断的 P1；
- 为必要修复新增独立的下一版 migration。

### 5.2 禁止的事项

- 修改 v1-v5 已发布 migration 的 SQL、版本号或语义；
- 直接修改 `demo.db` 绕过 migration；
- 只改新库 DDL 而不改旧库升级路径；
- 未经 E7 确认增加业务表、业务列、CHECK 枚举、外键或 API 字段；
- 在 D7A 中实现 V0.4 候选功能。

### 5.3 如果必须新增迁移

若确认需要修复 Schema 级发布阻断：

1. 由 E7 明确认定该问题是发布阻断；
2. A 轨设计最小化变更；
3. 新增 `v6`，不得修改 v5；
4. 增加旧库升级、幂等、备份恢复和失败回滚测试；
5. 完成非作者 review；
6. 更新冻结版本与验证证据后重新进入 RC gate。

## 6. 验证证据

### 6.1 Schema 审计

在临时数据库中执行 clean install 后得到：

```text
migration max = 5
table count = 22
REQUIRED_TABLES missing = 0
PRAGMA integrity_check = ok
PRAGMA foreign_key_check = 0 violations
```

### 6.2 定向回归

备份、迁移、事务和导出：

```powershell
cd backend
python -m pytest `
  tests/test_database_backup_restore.py `
  tests/test_restart_persistence.py `
  tests/test_schema_migrations.py `
  tests/test_d6a_concurrency.py `
  tests/test_tournament_export.py -q
```

结果：`38 passed`，`0 failed`。

权限、报名、组织与场馆：

```powershell
cd backend
python -m pytest `
  tests/test_auth_authorization.py `
  tests/test_tournament_ownership.py `
  tests/test_tournament_admin_management.py `
  tests/test_registration_api.py `
  tests/test_registration_confirmation.py `
  tests/test_organization_venue.py -q
```

结果：`40 passed`，`0 failed`。

### 6.3 全量与契约门禁

```text
backend full pytest：1025 passed、0 failed、0 skipped，退出码 0；仅有第三方弃用警告
python backend/export_openapi.py --check：OpenAPI snapshot is up to date
pnpm contract:check：通过，生成后无 Git diff
pnpm exec tsc --noEmit：通过
pnpm test -- --run：10 个测试文件、150 passed
pnpm build：通过，74 modules transformed
```

生产 Schema diff 检查应至少覆盖：

```powershell
git diff origin/master...HEAD -- backend/app/db.py
git diff origin/master...HEAD -- backend/app/migrations.py
git diff origin/master...HEAD -- backend/app/models.py
git diff origin/master...HEAD -- backend/app/schemas.py
git diff origin/master...HEAD -- docs/openapi-v0.2.json
```

预期结果：全部为 0，除非 E7 已正式批准 v6 发布阻断修复。

## 7. 与当前开放 PR 的关系

基线检查时，D 轨 PR #58（Public 报名前端接线）仍处于 open 状态，不修改 backend Schema、migration 或 OpenAPI。该 PR 不阻塞 D7A 主体工作，但不能在它合并前宣称 E7 最终 gate 已完成。合并后应按最终 master 重新执行 contract、typecheck、frontend test 和 build。

## 8. 最新边界

- migration v1-v5 可以自动升级旧库，但不提供自动 down migration；
- 回滚依赖升级前整库 backup 和停服 restore；
- restore 会恢复整库，因此旧 `user_sessions` 可能随 backup 一起恢复；
- 没有在线热恢复，也没有云备份或自动定时备份服务；
- Tournament Export 是赛事归档和人工交接，不是可恢复数据库备份；
- E7 最终 RC review 和现场复验尚未完成。
