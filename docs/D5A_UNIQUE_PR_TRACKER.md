# D5A 唯一 PR 执行跟踪

> 本文件用于声明 D5A 阶段只使用一个 PR，并冻结目标、契约、实施范围、验证门槛与跨轨边界。
> 本 PR 创建后，D5A 的后续代码、测试、文档和修改报告全部提交到本 PR，不新增第二个 D5A PR。

## 一、目标

将 Public 页面直接创建 Player 的旧报名路径替换为以下真实闭环：

```text
PUBLIC 报名
  -> Registration(PENDING)
  -> EVENT_ADMIN 按赛事权限确认
  -> 原子事务创建正式 Player
  -> 现有名单确认/配对流程生成 Entry
```

同时建立 Tournament 级报名开关，以及 Organization / Venue 的最小真实数据边界和赛事关联。

## 二、冻结契约

### 2.1 Registration 状态机

最小状态：

```text
PENDING
CONFIRMED
```

规则：

- Public 只能创建 `PENDING`，不能提交或修改 status。
- `PENDING -> CONFIRMED` 只能成功一次。
- 重复确认返回 `409`。
- 不提供任意 PATCH status 的绕过接口。
- `REJECTED` 不是当前来源明确要求；未与 C5/E5 确认前不扩展状态机。

### 2.2 Tournament 报名开关

新增 `registration_enabled`，历史赛事默认关闭：

```sql
INTEGER NOT NULL DEFAULT 0 CHECK (registration_enabled IN (0, 1))
```

- Public Tournament DTO 可读取该字段。
- 写入必须受赛事权限保护。
- 关闭后 PUBLIC 新报名稳定拒绝。

### 2.3 Registration 与正式名单

- Registration 保存报名事实，不成为 Entry 的第二真相源。
- 确认时创建正式 Player。
- 报名 `affiliation` 在确认时进入现有 `Player.college` 兼容链。
- Entry 继续由现有名单确认、双打配对或 Team roster 流程产生。
- 不复制 `build_singles_entries()`，不新增 `RegistrationEntry`。
- 不擅自为个人报名生成 TeamEntry。

### 2.4 Organization / Venue

- Organization 表示赛事组织方，不等同于 Affiliation。
- 不因报名单位自动创建 Organization。
- Organization 最小字段：`name`、可选 `contact_name`、可选 `contact`、可选 `note`。
- Venue 最小字段：`name`、可选 `address`、可选 `contact_name`、可选 `contact`、可选 `note`。
- Organization / Venue 均绑定 Tournament 并复用赛事授权。
- 不复制球台数据；现有 `tables` 继续是球台唯一事实源。
- Organization / Venue contact 不默认进入 Public DTO。

### 2.5 隐私与权限

- Public 创建响应只返回最小回执：`registration_id`、`status`、`name`、`created_at`。
- 禁止匿名读取全部报名或任何报名 contact。
- 管理列表仅在真实赛事权限下返回联系方式。
- 跨赛事读取或确认必须拒绝。
- VIEWER 不可修改赛事设置、报名确认、Organization 或 Venue。
- SYSTEM_ADMIN 不自动获得赛事业务权限。

## 三、建议 API 契约

```text
PUT  /api/tournaments/{tid}/registration
POST /api/tournaments/{tid}/registrations
GET  /api/tournaments/{tid}/registrations?status=PENDING
POST /api/tournaments/{tid}/registrations/{registration_id}/confirm
GET  /api/tournaments/{tid}/organization
PUT  /api/tournaments/{tid}/organization
GET  /api/tournaments/{tid}/venue
PUT  /api/tournaments/{tid}/venue
```

Schema 预计包括：

```text
RegistrationStatus
RegistrationCreate
RegistrationPublicOut
RegistrationAdminOut
RegistrationConfirmResult
TournamentRegistrationUpdate
OrganizationUpsert / OrganizationOut
VenueUpsert / VenueOut
TournamentOut.registration_enabled
```

## 四、明确不做

- 支付、报名收费。
- 微信、短信或邮件登录及通知。
- 候补队列和复杂审核流。
- Sponsor、Hotel、Commerce、CRM。
- 场馆预订、地图、GPS、多场馆排程。
- 完整 Affiliation 规范化迁移。
- 完整 Tournament lifecycle / ARCHIVED。
- B 轨排名、晋级、抽签算法。
- C 轨管理页和 D 轨 Public UI/QR 的页面实现。

## 五、跨轨交付边界

### C5

A5 提供 pending list、confirm、报名开关、Organization read/update、Venue read/update、稳定错误码和 OpenAPI。C5 不直接调用 `addPlayer()`，不自行标记 confirmed，不生成 Player id，不把 Organization 当成 Affiliation。

### D5

A5 提供 Public 报名创建、开关读取、关闭报名稳定拒绝和联系方式隐私边界。D5 最终必须停止把 `api.addPlayer()` 当作 Public 报名入口。

### E5

最终必须验证：

```text
创建赛事
-> 打开 registration_enabled
-> PUBLIC 提交报名
-> Registration=PENDING
-> 管理员查看待确认
-> 管理员确认
-> Player 进入正式名单
-> 确认名单/生成 Entry
-> 生成比赛并进入比赛流程
```

### 当前执行状态（2026-09-23 更新）

- A5 后端交付已通过 A5 后端范围复审（APPROVED）：migration v5、Registration/Organization/Venue 持久化与 API、确认事务、权限/隐私、Schema/OpenAPI/contract 及本地定向/全量验证均已完成。这里的“验证通过”仅代表当前 head 的本地证据，不替代远端 CI 或发布侧独立复验。
- C5 未完成：管理页面接入、临时字段清零仍由 C5 承接。
- D5 未完成：Public 停止使用 legacy `api.addPlayer()` 仍由 D5 承接。
- E5 未执行：`报名 -> 确认 -> Player -> Entry -> Match/比赛` 全链 E2E 尚未运行，D5A 最终完成门槛不能视为已通过。
- 最近复审针对 head `d712a92`；后续 tracker 文档更新不改变 A5 代码交付。当前仍没有可用的 GitHub Actions/status check 结果，D5A 最终 Gate 仍需 E5/发布侧独立复验。

## 六、实施清单

- [x] Migration v5：Tournament 报名开关及 Registration、Organization、Venue 持久化。
- [x] Repository：Registration、Organization、Venue 的读写与状态迁移。
- [x] Service：报名关闭检查、确认原子事务、名单锁定保护和重复确认保护。
- [x] Public API：创建 PENDING Registration，响应不泄露 contact。
- [x] Admin API：待确认列表与 confirm，返回 registration 和正式 player。
- [x] Organization / Venue API：赛事级读取和更新。
- [x] Schema / OpenAPI：更新请求、响应、TournamentOut，并生成契约快照。
- [x] 测试：migration、旧库升级、registration 状态机、并发确认、权限与隐私、Organization/Venue。
- [x] 后端定向测试、全量回归、OpenAPI `--check`、contract check（本地验证）。
- [ ] E5 报名 -> 确认 -> 比赛 E2E（尚未执行；由 E5 承接）。

## 七、完成门槛

前 14 项表示 A5 后端在当前 head 已具备并通过本地验证；其余四项尚未完成。

- [x] Public 不再直接创建 Player。
- [x] 新报名默认 PENDING，报名关闭时后端拒绝。
- [x] 有权限管理员可查看待确认并执行 confirm。
- [x] confirm 原子创建正式 Player，失败不留半状态。
- [x] 并发 confirm 不创建重复 Player。
- [x] roster 锁定后不能确认新报名。
- [x] Registration 与 Player 可追溯。
- [x] affiliation 进入 Player.college 兼容链。
- [x] Public 不泄露任何联系方式。
- [x] Organization 与 Affiliation 分离，且可关联 Tournament。
- [x] Venue 可关联 Tournament，且不复制 tables。
- [x] 越权读取、修改和确认被后端阻断。
- [x] Migration v5、transaction、permission、backend full 测试均通过（本地验证）。
- [x] OpenAPI 与 generated contract 无漂移。
- [ ] C5 页面接入完成，临时字段清零。
- [ ] D5 已停止使用 legacy `api.addPlayer()`。
- [ ] E5 全链 E2E 独立复验通过。
- [ ] 无越权、数据丢失、重复正式名单等 P0。

## 八、唯一 PR 声明

本阶段唯一 PR 分支：

```text
feature/D5A报名与场地组织API
```

建议 PR 标题：

```text
feat(A轨-D5)：完成报名确认与组织方场馆基础API
```

后续修改继续提交到本分支和本 PR。若需要同步 `master`，一律使用 merge，不使用 rebase。