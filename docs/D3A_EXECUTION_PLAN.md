# D3A 详细具体工作清单

> 轨道：A 轨（后端 / 权限）
>
> 日期：Day 3
>
> 原始计划目标：**支持协作管理员最小模型；异常结果接口配合**
>
> 当前执行状态：**A 侧实现与 A 侧自动化验证已完成（10/10）；等待 E/非作者复核、D 轨实机联调及最终 Merge Gate。**
>
> 当前验证状态：定向测试 71 passed；干净环境后端全量测试 890 collected / 30 skipped / 0 failed；OpenAPI snapshot up to date；`git diff --check` 通过。
>
> 当前前置状态：D2A PR #42 已于 2026-09-22 合并到 `master`；D3A 从 `origin/master@3052c37` 独立创建。
>
> PR 策略：D3A 的全部后续实现、测试、文档与 review 修复均进入同一个 D3A PR，不新增第二个阶段 PR。

---

# 1. D3A 今日目标

D3A 只完成两件事：

1. **协作管理员最小闭环**
   - 基于 D2A 已有 `TournamentAdmin` 数据结构；
   - 支持赛事 Owner / Admin 对现有 EVENT_ADMIN 进行最小赛事授权管理；
   - 支持查询授权、添加/更新授权、撤销授权；
   - 权限判断继续以后端为唯一权威；
   - 不扩展成完整邀请系统。

2. **异常结果接口配合**
   - 不新建第二条比分写入接口；
   - 继续复用现有：
     - `POST /api/matches/{match_id}/score`
     - `POST /api/matches/{match_id}/revise-score`
   - A 轨只负责：
     - 登录/赛事权限；
     - 资源归属校验；
     - Schema / OpenAPI 契约；
     - 稳定错误语义；
   - 比分合法性、异常结果业务规则、改分影响仍由 B 轨负责；
   - 手机异常结果交互仍由 D 轨负责。

---

# 2. 来源范围与职责边界

## 2.1 来源明确要求

V0.3 五人分工中，A 轨负责：

- User；
- TournamentAdmin；
- 认证鉴权；
- 赛事生命周期；
- Registration / Organization / Venue 数据与 API；
- 迁移与事务。

Day 3 对 A 轨的明确要求只有：

> **支持协作管理员最小模型；异常结果接口配合。**

V0.3 P1 还列出：

> **EVENT_ADMIN 邀请 / 添加协作管理员。**

因此 D3A 应实现“最小可用授权闭环”，不应扩大成完整邀请中心、邮件邀请、注册链接、复杂 RBAC 管理器。

## 2.2 现有代码基础

D2A 当前已经建立：

- `TournamentRole`
  - `OWNER`
  - `ADMIN`
  - `OPERATOR`
  - `VIEWER`
- `tournament_admins`
- `upsert_tournament_admin()`
- `get_tournament_access()`
- `require_tournament_read()`
- `require_tournament_write()`
- EVENT_ADMIN 登录与赛事授权体系。

因此 D3A **原则上不需要新建第二套协作管理员表**。

## 2.3 异常结果现有基础

当前后端已经存在：

- `ResultType.NORMAL`
- `ResultType.FORFEIT`
- `ResultType.WALKOVER`
- `ResultType.NO_SHOW`
- `ResultType.DISQUALIFIED`

当前 `ScoreRequest` 已包含：

- `player_a_score`
- `player_b_score`
- `games`
- `result_type`
- `forfeit_entry_id`
- `note`
- `request_id`
- `operator_name`
- `change_reason`

当前比分 Router 已受 `require_tournament_write` 保护。

因此 D3A **不应新建 `/abnormal-result` 之类的第二写入口**。

---

# 3. D3A 开工前置检查

## A3.0 检查 D2A 是否已经进入 master

- [x] `git fetch --prune origin`
- [x] 确认 PR #42 是否已合并。
- [x] 确认 `origin/master` 已包含 D2A：
  - User；
  - TournamentAdmin；
  - Auth API；
  - Session；
  - `require_tournament_read/write`；
  - Tournament owner / access。
- [x] 确认 D2A 最终 OpenAPI 已稳定。
- [x] 确认工作区干净。
- [x] 确认没有未提交或未跟踪的重要文件。

### 如果 D2A 尚未合并

> 说明：D2A 已合并，本条件分支不适用；以下保留原计划内容，不作为 D3A 未完成项。

D3A 暂停正式代码实现，只允许：

- [ ] 整理接口契约；
- [ ] 整理测试清单；
- [ ] 检查与 B/D 轨接口边界；
- [ ] 检查现有代码是否已经满足异常结果接口；
- [ ] 等 D2A 合并后再从最新 master 创建 D3A 分支。

**不要直接从旧 master 再造一套 TournamentAdmin / Auth。**

---

# 4. 创建 D3A 独立分支和 PR

D3A 是新的一天，应使用新的分支、新的 PR，不继续把 Day3 代码追加到 D2A PR。

建议分支：

```text
feat/D3A协作管理员与异常结果接口
```

建议 PR 标题：

```text
feat(A轨-D3)：完成协作管理员最小授权与异常结果接口配合
```

要求：

- [ ] 从最新 `master` 创建。
- [ ] 不直接修改 `master`。
- [ ] 不使用 rebase。
- [ ] 如需同步最新 master，一律 merge。
- [ ] PR 标题、正文、评论使用中文。
- [ ] 不修改 D2A 原始 PR 正文。
- [ ] 未获得明确授权前不执行 commit / push / 创建 PR / merge。

---

# 5. 工作包 A3.1：冻结“协作管理员最小模型”

## 5.1 先冻结最小语义

D3A 的“协作管理员”定义为：

> 已存在的有效 `EVENT_ADMIN` 用户，被赛事 Owner / Admin 授予指定赛事角色。

今日不做：

- 邮件邀请；
- 短信邀请；
- 邀请链接；
- 注册后自动入赛；
- 多阶段审批；
- 权限模板；
- 自定义 permission JSON；
- 跨组织权限继承；
- SYSTEM_ADMIN 自动获得赛事权限。

## 5.2 角色语义保持 D2A 已冻结规则

| 角色 | 读取赛事 | 写赛事业务 | 管理赛事授权 |
|---|---:|---:|---:|
| OWNER | 是 | 是 | 是 |
| ADMIN | 是 | 是 | 是 |
| OPERATOR | 是 | 是 | 否 |
| VIEWER | 是 | 否 | 否 |

检查项：

- [x] `OWNER` 仍由 `tournaments.owner_user_id` 表示。
- [x] 不允许通过普通协作管理员接口转移 Owner。
- [x] 普通授权接口只管理：
  - `ADMIN`
  - `OPERATOR`
  - `VIEWER`
- [x] `SYSTEM_ADMIN` 不因为系统身份自动获得赛事角色。
- [x] 被授权账号必须是有效 `EVENT_ADMIN`。
- [x] 被停用账号即使授权记录仍在，也不能继续访问。

---

# 6. 工作包 A3.2：设计最小协作管理员 API

> 原始资料没有规定具体 URL。以下路径是基于现有 REST 风格的**建议最小契约**；实施前优先检查仓库是否已有命名约定。

建议：

```text
GET    /api/tournaments/{tournament_id}/admins
POST   /api/tournaments/{tournament_id}/admins
DELETE /api/tournaments/{tournament_id}/admins/{user_id}
```

可选：

```text
PATCH  /api/tournaments/{tournament_id}/admins/{user_id}
```

如果 `POST` 已采用 upsert 语义，则可以不增加 PATCH。

## 6.1 GET 管理员列表

返回最小信息：

- [x] user id
- [x] username
- [x] display_name
- [x] tournament role
- [x] active
- [x] 是否为 owner
- [x] 授权创建时间
- [x] 可选：created_by_user_id

不得返回：

- [x] password_hash
- [x] Session token
- [x] token hash
- [x] 内部敏感认证字段

权限：

- [x] OWNER 可查看。
- [x] ADMIN 可查看。
- [x] OPERATOR 不允许查看授权管理面。
- [x] VIEWER 不允许查看。
- [x] 无权赛事统一按现有防泄漏规则处理。

## 6.2 POST 添加 / 更新协作管理员

建议请求：

```json
{
  "user_id": 123,
  "role": "OPERATOR"
}
```

或如果现有系统更适合 username：

```json
{
  "username": "referee01",
  "role": "OPERATOR"
}
```

只能选择一种主标识方式，不要同时设计多套模糊查找。

校验：

- [x] 目标赛事存在。
- [x] 操作者拥有授权管理权限。
- [x] 目标用户存在。
- [x] 目标用户为 `EVENT_ADMIN`。
- [x] 目标用户 `active=true`。
- [x] role 仅允许 `ADMIN / OPERATOR / VIEWER`。
- [x] 禁止通过该接口写 `OWNER`。
- [x] 同一个用户重复授权保持幂等或更新角色。
- [x] 已撤销授权重新添加时可恢复。
- [x] 写入 `created_by_user_id`。
- [x] 整个操作使用单事务提交。

## 6.3 DELETE 撤销协作管理员

- [x] OWNER 可撤销普通协作管理员。
- [x] ADMIN 按冻结规则可管理赛事授权。
- [x] OPERATOR 不可撤销。
- [x] VIEWER 不可撤销。
- [x] 不允许通过此接口删除赛事 OWNER。
- [x] 撤销使用现有 `revoked_at` 语义，优先软撤销，不删除历史授权记录。
- [x] 重复撤销保持稳定、可预期。
- [x] 被撤销用户下一次请求立即失去赛事访问能力。

---

# 7. 工作包 A3.3：补齐 Repository / Service 层

优先复用 D2A 已有：

```text
upsert_tournament_admin()
get_tournament_access()
```

建议新增或补齐：

```text
list_tournament_admins()
revoke_tournament_admin()
get_tournament_admin()
```

如果项目已有等价函数，则复用，不重复实现。

## Repository 检查

- [x] 查询只返回未撤销授权。
- [x] Owner 能出现在管理列表中，但来源应明确为 `owner_user_id`。
- [x] 普通 TournamentAdmin 来自 `tournament_admins`。
- [x] 不制造重复 owner 行。
- [x] role 更新后立即反映在 `get_tournament_access()`。
- [x] revoke 后 `get_tournament_access()` 返回无权。
- [x] SQL 使用参数绑定。
- [x] 不拼接用户输入 SQL。

## Service 层

建议新增：

```text
backend/app/services/tournament_admins.py
```

职责只做：

- [x] 授权前校验；
- [x] 用户类型校验；
- [x] role 校验；
- [x] owner 保护；
- [x] grant / update；
- [x] revoke；
- [x] 事务处理；
- [x] 稳定业务错误。

不要把复杂权限判断散落在 Router。

---

# 8. 工作包 A3.4：新增 Schema 与 Router

可能涉及：

```text
backend/app/schemas.py
backend/app/routers/tournament_admins.py
backend/app/main.py
```

## Schema 建议

- [x] `TournamentAdminGrantRequest`
- [x] `TournamentAdminOut`
- [x] 可选 `TournamentAdminListResponse`

Schema 必须表达：

- [x] user_id / username
- [x] display_name
- [x] role
- [x] active
- [x] is_owner
- [x] created_at

不要暴露敏感字段。

## Router

- [x] Router 注册到 `main.py`。
- [x] 读取/授权管理使用赛事权限依赖。
- [x] 不通过前端参数信任 `owner_user_id`。
- [x] 不信任客户端传 `created_by_user_id`。
- [x] `created_by_user_id` 必须来自当前认证用户。
- [x] 目标 tournament_id 必须来自 URL / 后端资源关系。
- [x] 错误格式保持现有 D2A 稳定错误结构。

---

# 9. 工作包 A3.5：协作管理员权限反例测试

建议新增：

```text
backend/tests/test_tournament_admin_management.py
```

至少覆盖：

## 成功路径

- [x] OWNER 添加 ADMIN。
- [x] OWNER 添加 OPERATOR。
- [x] OWNER 添加 VIEWER。
- [x] ADMIN 添加 OPERATOR。
- [x] 重复添加同一用户更新角色而不产生重复授权。
- [x] revoke 后重新添加可恢复授权。

## 权限边界

- [x] 未登录调用返回 401。
- [x] 无赛事访问权限返回 404。
- [x] VIEWER 不能授权。
- [x] OPERATOR 不能授权。
- [x] VIEWER 不能撤销。
- [x] OPERATOR 不能撤销。
- [x] SYSTEM_ADMIN 没有显式赛事授权时不能操作该赛事授权。
- [x] 另一赛事的 OWNER 不能管理当前赛事。

## 用户合法性

- [x] 不存在用户不能授权。
- [x] inactive EVENT_ADMIN 不能新增授权。
- [x] SYSTEM_ADMIN 不能被当作普通协作赛事管理员授权。
- [x] 非法 role 被拒绝。
- [x] 普通 grant API 不能授予 OWNER。
- [x] 普通 revoke API 不能撤销 OWNER。

## 即时失效

- [x] OPERATOR 撤销前可以调用赛事写接口。
- [x] revoke 后同一账号再次请求赛事写接口立即失败。
- [x] role 从 OPERATOR 降为 VIEWER 后写操作立即失败。
- [x] role 从 VIEWER 升为 OPERATOR 后写操作按新权限生效。

---

# 10. 工作包 A3.6：异常结果接口配合

D3A 这里的原则是：

> **检查和补齐接口契约，不重写 B 轨比分规则。**

## 10.1 保持单一比分真相源

继续使用：

```text
POST /api/matches/{match_id}/score
POST /api/matches/{match_id}/revise-score
```

- [x] 不新增第二个异常结果写接口。
- [x] 不新增第二套比赛完成状态。
- [x] 不在 A 轨重算 winner。
- [x] 不在 A 轨重算 ranking。
- [x] 不在 A 轨实现淘汰晋级。
- [x] 不在 A 轨复制 B 轨 score validation。

## 10.2 当前异常类型

检查现有：

- [x] `FORFEIT`
- [x] `WALKOVER`
- [x] `NO_SHOW`
- [x] `DISQUALIFIED`

注意：

- **BYE 不应在 D3A 被当成一场正常 Match 的异常比分。**
- BYE 属于 Day4 B 轨赛制 / 淘汰签位处理范围。
- 不要为了满足“异常结果”字面含义在 D3A 给 `ResultType` 强塞 BYE。

## 10.3 A 轨负责的接口权限

针对异常结果提交：

- [x] 未登录 → 401。
- [x] 无权赛事 → 404。
- [x] VIEWER → 不可写。
- [x] OPERATOR → 可按赛事写权限提交。
- [x] ADMIN → 可提交。
- [x] OWNER → 可提交。
- [x] SYSTEM_ADMIN 无赛事授权 → 不自动获得写权限。

## 10.4 A 轨负责的接口契约

确认 OpenAPI 对以下字段可见：

- [x] `result_type`
- [x] `forfeit_entry_id`
- [x] `note`
- [x] `request_id`
- [x] `operator_name`
- [x] `change_reason`

确认：

- [x] 异常结果不要求前端伪造 `games`。
- [x] 不要求 D 轨生成假局分。
- [x] 异常结果错误返回可被 D 轨统一展示。
- [x] API 保持当前相对 `/api/...` 路径，不写死 localhost / LAN IP。

---

# 11. 工作包 A3.7：与 B 轨的接口边界

B 轨 Day3 主责：

- 大比分必填；
- 小比分可选；
- 小比分与大比分一致性；
- 改分影响保护；
- 异常结果的比分/晋级规则正确性。

A 轨不要修改：

- [ ] `scores_service` 的核心胜负算法，除非 B 明确要求配合接口。
- [ ] ranking 算法。
- [ ] knockout advance。
- [ ] score impact analysis。
- [ ] abnormal result 对排名/晋级的业务裁决。

A 轨需要确认 B 提供：

- [ ] 正常比分校验已经覆盖。
- [ ] 异常结果无需伪造小比分。
- [ ] 非法异常方能返回稳定 422。
- [ ] 改分的下游保护仍有效。
- [ ] 异常结果不会静默污染晋级。

如果 B 轨接口字段发生变化：

- [ ] 先由 B/A 明确后端契约。
- [ ] 更新 OpenAPI。
- [ ] 再通知 D 轨适配。
- [ ] 禁止 D 轨临时发明字段。

---

# 12. 工作包 A3.8：与 D 轨 Day3 手机录分对接

当前 D 轨 Day3 已明确：

- 使用 `POST /api/matches/{matchId}/score`；
- 使用现有 `ResultType`；
- 异常结果不带伪造 games；
- 401 / 403 / 404 / 409 / 422 分开显示；
- Auth 最终接线依赖 A 轨。

D3A 应检查：

- [ ] D 轨没有创建第二套 Auth。
- [ ] D 轨没有用 localStorage 模拟赛事权限。
- [ ] 手机录分页最终通过 A 轨真实 Session / Bearer 登录态。
- [ ] D 轨请求的比赛必须属于 URL 中赛事。
- [ ] 服务端仍是唯一安全边界。
- [ ] 前端 Guard 只改善 UX，不代替后端校验。
- [ ] 401 / 404 语义与 D2A 冻结契约一致。
- [ ] D 轨无需因为协作管理员功能修改比分 payload。

如果 D 轨当前 PR 已经基于旧 master：

- [ ] 不要求 D 轨复制 A 的后端代码。
- [ ] 等 A 的 Auth / OpenAPI 契约进入 master 后再做最小接线。
- [ ] 由 D 轨自己完成其前端修改。

---

# 13. 工作包 A3.9：OpenAPI 与契约更新

如果 D3A 新增协作管理员 API，则属于 API 变化。

必须：

- [x] 更新 Pydantic Schema。
- [x] 注册 Router。
- [x] 重新导出：

```powershell
cd backend
python export_openapi.py
python export_openapi.py --check
```

- [x] 检查 `docs/openapi-v0.2.json`。
- [x] 不手改生成 OpenAPI。
- [ ] 通知 C 轨消费新的管理员授权接口。
- [ ] 如前端生成类型受影响，由前端 Owner 更新。
- [x] 不在 A 轨直接修改 C/D 拥有的页面完成“顺手适配”。

---

# 14. 工作包 A3.10：测试与 Merge Gate

## 14.1 定向测试

建议先跑：

```powershell
cd backend

python -m pytest `
  tests/test_auth_dependencies.py `
  tests/test_auth_authorization.py `
  tests/test_tournament_ownership.py `
  tests/test_tournament_admin_management.py `
  tests/test_auth_api.py `
  tests/test_openapi_auth_contract.py `
  -q
```

如果异常结果权限另加 API 测试，再加入对应测试文件。

验收：

- [x] 0 failed。
- [x] 越权反例全部覆盖。
- [x] grant / revoke / role change 有测试。
- [x] 异常结果权限有测试。
- [x] OpenAPI 契约有测试。

## 14.2 全量后端测试

定向测试通过后执行一次：

```powershell
python -m pytest
```

记录：

- [x] collected
- [x] passed
- [x] skipped
- [x] warnings
- [x] exit code
- [x] 总耗时

要求：

- [x] `0 failed`
- [x] exit code `0`

不要把测试数量写死为历史值；以 D3A 最终 HEAD 实际结果为准。

## 14.3 Diff 检查

```powershell
git status --short
git diff --check
git diff origin/master...HEAD
```

检查：

- [x] 无临时 DB。
- [x] 无 `.venv`。
- [x] 无缓存。
- [x] 无探针脚本误提交。
- [x] 无无关格式化。
- [x] 无 B/C/D 轨业务代码越界。
- [x] 无第二套 Auth / Score 实现。

---

# 15. 建议文件变更范围

## 很可能需要修改

```text
backend/app/repository.py
backend/app/schemas.py
backend/app/main.py
docs/openapi-v0.2.json
```

## 建议新增

```text
backend/app/services/tournament_admins.py
backend/app/routers/tournament_admins.py
backend/tests/test_tournament_admin_management.py
```

## 可能只需检查、不一定修改

```text
backend/app/dependencies.py
backend/app/models.py
backend/app/routers/scores.py
backend/app/services/scores.py
backend/tests/test_auth_authorization.py
backend/tests/test_openapi_auth_contract.py
```

原则：

> 如果现有实现已经满足 D3A 某一验收项，不为了“看起来有工作量”重复改代码。

---

# 16. 今日明确不做

- [x] 不做完整邀请系统。
- [x] 不做邮件 / 短信邀请。
- [x] 不做一次性邀请 Token。
- [x] 不做组织级权限体系。
- [x] 不做自定义 RBAC 权限编辑器。
- [x] 不做赛事 Owner 转移流程。
- [x] 不做 Registration。
- [x] 不做 Organization / Venue。
- [x] 不做 Tournament format/rule_config。
- [x] 不做 Affiliation。
- [x] 不做 BYE。
- [x] 不做种子 / 抽签。
- [x] 不做排名。
- [x] 不做晋级算法。
- [x] 不做手机 UI。
- [x] 不做部署脚本。
- [x] 不新建异常结果第二写入口。
- [x] 不修改 C/D 页面来“顺手完成联调”。

这些分别属于 Day4/Day5 或 B/C/D 轨职责。

---

# 17. D3A 验收场景

## 场景 1：Owner 添加裁判协作者

1. Owner 登录。
2. 添加一个 active EVENT_ADMIN 为 OPERATOR。
3. OPERATOR 登录。
4. OPERATOR 能进入被授权赛事。
5. OPERATOR 可以录分。
6. OPERATOR 不能管理赛事授权。

- [x] 通过。

## 场景 2：Viewer 只读

1. Owner 添加 EVENT_ADMIN 为 VIEWER。
2. Viewer 能查看赛事。
3. Viewer 调用比分写接口失败。
4. Viewer 调用授权管理接口失败。

- [ ] 通过。

## 场景 3：撤销即时生效

1. EVENT_ADMIN 原本有 OPERATOR 权限。
2. Owner 撤销授权。
3. 原 Session 保持登录。
4. 再访问该赛事时仍必须因为赛事授权已撤销而失败。

- [x] 通过。

## 场景 4：跨赛事隔离

1. 用户是赛事 A 的 ADMIN。
2. 尝试管理赛事 B 的协作管理员。
3. 返回与资源不存在一致的 404 防泄漏语义。

- [x] 通过。

## 场景 5：异常结果权限

1. OPERATOR 对自己有权限赛事提交 `FORFEIT`。
2. 请求通过权限层。
3. 比分合法性由 B 轨规则层裁决。
4. VIEWER 提交同样请求被后端拒绝。
5. SYSTEM_ADMIN 无赛事授权时不能提交。

- [ ] 通过。

## 场景 6：D 轨手机录分

1. 手机端使用真实 Auth。
2. 提交异常结果。
3. 不带伪造逐局比分。
4. 后端权限与业务规则均通过后才成功。
5. 越权或非法异常方返回稳定错误。

- [ ] 通过。

---

# 18. D3A 完成门槛

D3A 只有同时满足以下条件才算完成：

- [x] D2A 已进入当前开发基线，D3A 未复制旧认证实现。
- [x] 协作管理员最小授权闭环完成。
- [x] Owner / Admin 可以管理普通赛事授权。
- [x] OPERATOR / VIEWER 不能管理赛事授权。
- [x] SYSTEM_ADMIN 不自动获得赛事业务权限。
- [x] grant / role change / revoke 即时影响后端权限。
- [x] 没有新增第二套协作管理员数据模型。
- [x] 没有新增第二套异常结果比分接口。
- [x] 异常结果继续使用现有 `ScoreRequest / ResultType`。
- [x] 异常结果接口有真实赛事权限保护。
- [x] B 轨仍是比分 / 改分业务规则 Owner。
- [x] D 轨仍是手机异常结果 UI Owner。
- [x] API 变化已同步 OpenAPI。
- [x] 定向测试通过。
- [x] 后端全量 pytest 0 failed。
- [x] `git diff --check` 通过。
- [ ] E / 非作者完成必要复核。
- [ ] 无越权、数据丢失、错误结果等 P0。

---

# 19. 建议原子提交拆分

D3A 建议最多拆为 3～4 个原子提交：

### Commit 1

```text
feat(A轨-D3)：增加赛事协作管理员授权接口
```

内容：

- repository
- service
- schema
- router

### Commit 2

```text
test(A轨-D3)：补充协作管理员权限反例
```

内容：

- grant / revoke
- owner protection
- role boundary
- cross-tournament
- immediate revoke

### Commit 3

如果异常结果接口确实需要 A 侧契约修正：

```text
feat(A轨-D3)：补齐异常结果权限与接口契约
```

如果现有接口已经完全满足要求，则**不要为了凑提交修改生产代码**，只把验证结果写进 PR。

### Commit 4

```text
docs(A轨-D3)：更新协作管理员与异常结果接口契约
```

内容：

- OpenAPI
- D3A 交付说明
- 跨轨接线边界

---

# 20. PR 正文需要包含

## 本次改动

- 协作管理员最小授权。
- grant / revoke / role。
- 异常结果接口权限/契约配合。
- 自动化测试。

## 明确未改

- B 轨比分算法。
- B 轨改分影响。
- 排名/晋级。
- C 轨页面。
- D 轨手机录分 UI。
- Day4 赛制/BYE/种子/Affiliation。
- Day5 Registration/Organization/Venue。

## 影响范围

至少明确：

- [x] 数据库迁移：预期无新增表；如实际变化必须说明。
- [x] API / Schema：如果新增管理员授权 API。
- [x] OpenAPI：如果 API 有变化。
- [x] 核心比分规则：A 轨不修改。
- [x] 权限边界。

## 测试

- 定向测试。
- 后端完整 pytest。
- OpenAPI check。
- 越权反例。
- 异常结果权限。
- 主裁判最小手测步骤。

## 已知限制

- 无邀请链接。
- 无邮件/短信。
- 无 Owner 转移。
- 无复杂 RBAC。
- BYE 不属于 D3A 异常比分入口。

---

# 21. Commit 前人工审核材料

修改和验证完成后先停止，不直接提交。

必须报告：

- [x] 修改文件清单。
- [x] 每个文件修改原因。
- [x] diff 摘要。
- [x] 定向测试结果。
- [x] 全量测试结果。
- [x] OpenAPI check 结果。
- [x] 已知风险。
- [x] 与 B/C/D 轨的未完成联调项。
- [x] 当前 Git 状态。
- [x] 建议 commit 信息。

在收到明确：

```text
commit
```

之前不提交。

`commit`、`push`、创建 PR、merge 分别单独授权。

---

# 22. D3A 当前依赖 / 阻塞关系

| 来源 | 是否阻塞 | 原因 |
|---|---|---|
| D2A | **是，当前硬前置** | 协作管理员直接依赖 User / TournamentAdmin / Session /赛事授权进入 master |
| B3 | 部分协作，不阻塞管理员模型 | 异常结果的业务合法性和改分影响由 B 负责；A 不应抢做 |
| D3 | 部分协作 | 手机异常结果页面已使用现有 Score API；最终 Auth 接线依赖 A 的稳定契约 |
| C3 | 非硬阻塞 | 管理端可后续消费协作管理员 API |
| E3 | **最终 Merge Gate** | 越权、异常结果、重复提交、回归测试可阻断合并 |

---

# 23. 推荐执行顺序

1. [x] 完结并合并 D2A。
2. [x] 从最新 master 创建 D3A 分支。
3. [x] 冻结协作管理员最小 API。
4. [x] 先写权限反例 / contract 测试骨架。
5. [x] 实现 repository + service。
6. [x] 实现 schema + router。
7. [x] 跑协作管理员定向测试。
8. [x] 检查现有异常结果接口是否已经满足 A 轨职责。
9. [x] 只补缺失的 Auth / Schema / OpenAPI，不改 B 轨算法。
10. [ ] 与 D 轨核对手机录分 Auth 接线。
11. [x] 导出并检查 OpenAPI。
12. [x] 跑后端全量 pytest。
13. [x] `git diff --check` + 最终 diff review。
14. [x] 输出人工审核材料。
15. [ ] 等待 commit 授权。
16. [ ] commit 后等待 push 授权。
17. [ ] push 后等待创建 PR 授权。
18. [ ] PR review 打回时追加新的中文修改报告，不改原 PR 正文。

---

## D3A 一句话完成定义

> **在 D2A 权限体系之上，以最小增量完成 TournamentAdmin 协作授权闭环，并保证现有异常结果比分接口通过真实赛事权限安全暴露给 B/D 轨使用；不复制比分算法、不新建第二写入口、不扩展完整邀请系统。**
