# Team Runtime Contract v1（A4.1）

状态：**已实现**（PR #20 / A4.1）。机器真相是 `backend/app/schemas.py` → `docs/openapi-v0.2.json`
→ `frontend/src/generated/openapi.d.ts`；本文负责解释字段语义、nullable、状态机、权限与错误契约，
不重复定义字段类型。

本文与 B 工作线的 Draft（`feat/b-team-ui-shell` 上的同名文件）对齐；两者的差异只有
"候选阵容按边分组"等几点，列在文末「与 B Draft 的差异」，合并时以本文为准。

边界：本契约只描述页面消费的数据与操作权限，**不冻结任何真实团体赛规则**。
生产赛制由组织者确认后版本化登记：A5 起已有第一版 `LOCAL_CLASSIC_5_V1`
（5 盘、先赢 3 盘、单/单/双/单/单；**不声明**等同于任何官方规则，详见 `docs/TEAM_DOMAIN.md`）。
盘序、兼项、替补、选手角色映射与提前结束规则都不在本契约里；**页面不得根据 `format.code` 推导业务逻辑**
（不得出现 `if code === 'LOCAL_CLASSIC_5_V1'` 或写死 `TARGET_WINS = 3`），
一律按后端返回的 `rubbers` 渲染、按 `target_wins` 显示。规则变化一律新增版本，不覆盖已有 code。

## 1. 读取模型：`TeamTieRuntimeOut`

`GET /api/tournaments/{tid}/team-ties/{tie_id}` 直接返回它（**没有**第二套 `/team-tie-runtime` 路径）。
它是 A3 详情响应（`TeamTieOut` + `rubbers`）的**超集**：原有字段与命名全部保留，只追加运行态字段，
因此对已消费方是兼容升级。

| 字段 | 类型 | nullable | 说明 |
| --- | --- | --- | --- |
| `id`, `tournament_id` | integer | 否 | 对抗与赛事标识。 |
| `stage` | `GROUP \| KNOCKOUT` | 否 | 展示用赛段，不推导规则。 |
| `group_id` | integer | 是 | 绑定的小组（未绑定为 null）。 |
| `round`, `match_index` | integer | `round` 否 / `match_index` 是 | 轮次与场序。 |
| `status` | `WAITING \| PLAYING \| FINISHED` | 否 | 对抗状态；第一盘开始 → PLAYING，达到获胜盘数 → FINISHED。 |
| `home_team`, `away_team` | `TeamSummary` | 否 | 主队 = `entry_a_id`，客队 = `entry_b_id`。 |
| `home_score`, `away_score` | integer | 否 | 后端按 FINISHED 的盘**重算**的团体总比分。 |
| `team_a_score`, `team_b_score` | integer | 否 | 同上（A3 存储字段名，保持兼容）。 |
| `entry_a_id`, `entry_b_id` | integer | 否 | 双方队伍 Entry id（A3 命名）。 |
| `target_wins` | integer | **是** | 获胜所需盘数，由后端从赛制快照读取；无可用快照时为 null。 |
| `format` | `TeamFormatRuntime` | 否 | 只展示；前端**不得**由 code 推算盘序。 |
| `rubbers` | `TeamRubberRuntimeOut[]` | 否 | 后端返回的实际盘次顺序（按 `sequence`）。 |
| `winner_entry_id` | integer | 是 | 对抗未结束为 null。 |
| `permissions` | `TeamPermission` | 否 | 对抗级权限（各盘权限的汇总）。 |
| `format_code`, `format_version`, `format_snapshot` | string / integer / string | 是 | 建盘时固化的赛制与快照原文。 |
| `called_at`, `started_at`, `finished_at` | string | 是 | UTC SQLite 时间戳；对抗首次开始与结束时间。 |
| `created_at` | string | 否 | 创建时间。 |

列表接口 `GET /api/tournaments/{tid}/team-ties` 仍返回轻量 `TeamTieOut[]`（不含队伍与盘）；
需要阵容、比分与权限时读详情，避免列表 N+1。

## 2. `TeamSummary`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entry_id` | integer | 队伍（`entry_type='TEAM'` 的 Entry）id。 |
| `display_name` | string | 队名。 |
| `status` | `ACTIVE \| WITHDRAWN` | 已退赛的队伍不能安排新对抗与新阵容。 |
| `members` | `EntryMemberOut[]` | 成员内嵌：`player_id`、`name`、`college`、`rating_points`、`member_order`。 |

B 不需要为显示一支队伍再发额外请求。

## 3. `TeamFormatRuntime`

| 字段 | 类型 | nullable | 说明 |
| --- | --- | --- | --- |
| `code`, `display_name` | string | 是 | 赛制代号与名称（未建盘为 null；建盘后为快照里的值，例如 `LOCAL_CLASSIC_5_V1` / 经典五盘三胜团体赛）。 |
| `version` | integer | 是 | 赛制版本（快照里的版本，不随注册表变化）。 |
| `rubbers_to_win` | integer | 是 | 获胜所需盘数；与对抗上的 `target_wins` 同源。 |

前端**不得**自己算 `(len(rubbers)+1)/2`、写死 3，或按 `code` / 盘数分支渲染：
一律 `rubbers.map(...)` + 显示后端给的 `target_wins`。

## 4. `TeamRubberRuntimeOut`

| 字段 | 类型 | nullable | 说明 |
| --- | --- | --- | --- |
| `id`, `team_tie_id`, `sequence` | integer | 否 | 盘标识与显示顺序。 |
| `rubber_type` | `SINGLES \| DOUBLES` | 否 | 只控制文案与**每边人数**（1 / 2）。 |
| `status` | `PENDING \| READY \| PLAYING \| FINISHED \| SKIPPED` | 否 | 后端状态机；SKIPPED 只由后端决定。 |
| `home_slots`, `away_slots` | string[] | 否 | 赛制要求的"位置代号"（例如生产赛制双打盘的 `["HOME_R3_1","HOME_R3_2"]`）。只是位置标识：不承载"某个固定角色/选手必须打这里"的语义，页面只用于展示。 |
| `home_player_ids`, `away_player_ids` | integer[] | 否 | 本盘**实际**上场队员 id（未确认为空数组）。写操作用它。 |
| `home_players`, `away_players` | string[] | 否 | 与上面对应的展示名（用于比分条/直播文案）。 |
| `home_score`, `away_score` | integer | 是 | 本盘胜局数；未结束/跳过为 null。 |
| `winner_side` | `HOME \| AWAY` | 是 | 本盘胜方；未结束/跳过为 null。 |
| `winner_entry_id` | integer | 是 | 本盘胜方队伍 Entry id。 |
| `match_id` | integer | 是 | **恒为 null**：一盘不创建普通比赛（架构边界，见 TEAM_DOMAIN）。 |
| `lineup_valid` | boolean | 否 | 已保存阵容是否仍满足"选手属于本队 + 队伍在赛"；`false` 时不能开始。 |
| `lineup_invalid_reason` | string | 是 | `lineup_valid=false` 时的可展示原因（例如队员已被移出名单、队伍已退赛）。 |
| `permissions` | `TeamPermission` | 否 | 盘级权限。 |
| `lineup_options` | `{ home, away }` | 否 | 两边的候选阵容（见 §5）。 |
| `created_at` | string | 否 | 建盘时间。 |
| `started_at`, `finished_at` | string | 是 | 本盘开始/结束时间。 |

## 5. `TeamLineupOptions` 与候选规则

`GET /api/tournaments/{tid}/team-ties/{tie_id}/rubbers/{rubber_id}/lineup-options`
与详情里内嵌的 `lineup_options` 同源，结构为 `{ "home": [...], "away": [...] }`。
每项：`player_id`、`name`、`available`、`unavailable_reason`（`available=false` 时必须给可展示原因）。

本版只执行**通用硬约束**（`unavailable_reason` 就是下面这些原因）：

1. 候选必须属于该边的 TeamEntry（因此两个列表天然互斥）；
2. 队伍必须是 `ACTIVE`（已退赛 → 全部不可用）；
3. 对抗不能已结束；
4. 本盘必须是 `PENDING`/`READY`（已开始/已结束 → 阵容锁定）。

**刻意不做**（规则未冻结，等组织者确认后再通过 `can_start` / 候选规则扩展）：
"同一选手最多打一盘"、"不能兼项"、"双打必须一单一双"、"必须按盘序出场"、"替补/换人历史"。

## 6. 权限 `TeamPermission`

| 字段 | 规则 |
| --- | --- |
| `can_edit_lineup` | 对抗未结束 且 本盘处于 `PENDING`/`READY`。 |
| `can_confirm_lineup` | 与 `can_edit_lineup` 同义：本版"提交合法阵容即确认"（`PENDING → READY`），没有单独的确认步骤。保留该字段供 UI 的"确认阵容"按钮使用。 |
| `can_start` | 对抗未结束 且 本盘 `READY` 且**没有**其它盘处于 `PLAYING` 且 `lineup_valid = true`（队员已被移出名单 / 队伍已退赛时不允许开始）。 |
| `can_record_score` | 本盘 `PLAYING`。 |
| `can_revise_score` | 恒为 `false`（A4.1 不做改分）。 |

对抗级 `permissions` 是各盘权限的"任一为真"汇总（`can_revise_score` 恒 false）。
前端按钮必须直接消费这些字段，**不得**再根据状态、盘序或人数自行推导。

## 7. 写操作与状态机

所有写操作都返回最新的完整 `TeamTieRuntimeOut`：前端 `setTeamTie(response)` 整体替换即可，无需二次拉取。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tournaments/{tid}/team-ties/{tie_id}` | 读取运行态。 |
| GET | `.../rubbers/{rubber_id}/lineup-options` | 候选阵容（两边的可用性与原因）。 |
| PUT | `.../rubbers/{rubber_id}/lineup` | 提交本盘实际参赛人（覆盖式写入；人数必须等于盘型要求）。 |
| POST | `.../rubbers/{rubber_id}/start` | 开始本盘。 |
| POST | `.../rubbers/{rubber_id}/score` | 录入本盘大比分。 |

一盘：

```
PENDING ──提交合法阵容──▶ READY ──start──▶ PLAYING ──score──▶ FINISHED
   │                          │
   └────── 对抗被提前结束（一方达到 target_wins）──────▶ SKIPPED
```

规则：

- **只记大比分**：`home_score`/`away_score` 是胜局数，按赛事 `games_to_win` 校验
  （复用个人赛的同一套规则），例如 `games_to_win=2` 时合法值只有 `2:0`、`2:1`、`0:2`、`1:2`。
  不建逐局小比分，也不支持异常结果（弃权/未到/取消资格）。
- **只允许 `PLAYING` 录分**：不做个人赛里"未排台直接录分"的捷径（现场补录以后单独加）。
- **串行执行**：同一对抗同时最多一盘 `PLAYING`；因此提前结束时不会残留进行中的盘。
- **不强制盘序**：`sequence` 只用于展示；正式赛制若要求严格顺序，后续通过 `can_start` 扩展。
- **对抗总分由后端重算**：每次录分后按 FINISHED 的盘重新统计，达到 `target_wins` 时
  `status=FINISHED`、写入 `winner_entry_id` 与 `finished_at`，并把剩余 `PENDING`/`READY` 盘标成
  `SKIPPED`（`FINISHED` 的盘不动）。**不存在**直接提交"对抗 3:1"的接口，避免两个真相源。
- 已 `FINISHED` 或 `SKIPPED` 的盘不能改阵容、不能开始、不能录分；本版也不支持改分。

### 名单冻结与阵容失效（PR #20 复审补强）

- **提交阵容时**：校验"人数与盘型一致、选手属于本队、队伍在赛"。
- **开始一盘时**：在写事务内**原子重新校验已保存的阵容**。若队员已被移出队伍、或队伍已退赛，
  `start` 返回 409（盘仍是 `READY`，可以重新提交阵容后再开始），并且运行态里
  `lineup_valid=false` + `can_start=false`，前端不需要自己判断原因。
- **队伍一旦有对抗进入 `PLAYING`/`FINISHED`**：`PATCH /teams/{entry_id}` 改 `member_ids` 返回 409
  （"团体赛名单在对抗开始后不可更改"）；改名与积分不受影响。这样已开赛的对抗不可能出现
  "已经不属于本队"的选手继续上场。
  **注意**：本版没有"撤销已开始的对抗"，因此名单冻结在赛事内是单向的（团体赛按固定名单进行）。
- 对抗尚未开始时仍可修正名单（包括 `READY` 的盘），失效的阵容由上面第二条兜住。

### 并发与原子性（PR #20 复审补强）

Runtime 的每个写操作都满足：

1. **read-check-write 在同一个 `BEGIN IMMEDIATE` 写事务里**：同一对抗的并发请求被写锁串行化，
   后来者读到的是前一个请求已提交的状态；另一个连接正在处理该对抗时返回可读的 409
   （"该对抗正在被另一个请求处理，请稍后重试"），不会把 SQLite 锁错误漏成 500。
2. **写入是带预期旧状态的条件更新**（`WHERE id=? AND status='READY'` 等）并检查 rowcount：
   并发下 PLAYING 不会被写回 READY，FINISHED 也不会被第二次录分覆盖——"本版不支持改分"
   因此在数据库层成立，而不只是接口层的读后判断。
3. **跨行不变量在任何写入之前校验**：例如"同一对抗同时最多一盘 PLAYING"在结算前先检查，
   不满足时直接 409，不会留下"当前盘已被改成 FINISHED"的未提交脏状态。
4. **队伍成员变更与 `start` 共用同一把写锁**：`PATCH /teams/{entry_id}` 改 `member_ids` 时同样先
   `BEGIN IMMEDIATE` 再重新读取"对抗是否已开始"，因此 roster mutation 与 Runtime start 原子串行化——
   两者只会有一个成功：要么名单先改完（随后 `start` 因阵容失效 409），要么盘先开始（随后改名单 409 名单锁定）。
   只改队名或积分不进入这把锁。
5. **写事务实现在 `services/transaction.py`（PR #22 复审 P1）**：`write_transaction()` 是
   `BEGIN IMMEDIATE` + 异常回滚 + 锁等待超时映射的唯一实现，Runtime 各写操作与建盘骨架
   （`POST .../rubber-skeleton`）共同复用。因此建盘也满足本节第 1 条：并发重复建盘，
   一个成功、另一个拿 409，不会把 `UNIQUE (team_tie_id, sequence)` 撞成 500。

## 8. 错误契约

| 状态码 | 场景 |
| --- | --- |
| 404 | 赛事 / 团体对抗 / 盘 / 选手不存在（或盘不属于该对抗、对抗不属于该赛事）。 |
| 409 | 业务状态冲突：对抗已结束、本盘未 READY、本盘已在其它状态、已有另一盘 PLAYING、阵容已锁定、队员不属于该队伍、队伍已退赛、阵容已失效（队员已被移出名单）、名单已冻结（队伍已有对抗开赛）、缺少可用赛制快照、另一个请求正在处理该对抗（写锁等待超时）；建盘/重建：已有骨架（未显式 `replace`）、或对抗已进入 Runtime（有盘 READY/PLAYING/FINISHED/SKIPPED）——**开赛后换赛制或重建骨架是永久 409**。 |
| 422 | payload 本身非法：人数与盘型不符、同一边重复队员、比分不合法、建盘时提交了**未登记/未知的赛制 code**（不会退回默认赛制，也不会变成 500）。 |

失败响应保持项目现有风格（`{"detail": "可展示的中文原因"}`），B 直接展示 `detail`。

## 9. 明确不在 A4.1（不要在 UI 里假设存在）

异常结果（弃权/未到/取消资格）、比分修改（`can_revise_score` 恒 false）、逐局小比分、
多盘并行与球台占用、scheduler / ETA 接入、团体小组排名与淘汰晋级、正式团体赛制、
`TeamRubber → Match` 适配器、完整团体赛前端页面。

## 10. 与 B Draft 的差异（B 接线时需要对齐）

| 项 | B Draft | 本契约（机器真相） | 原因 |
| --- | --- | --- | --- |
| `lineup_options` | 扁平数组 | `{ home: [...], away: [...] }` | 每边候选只来自本队，扁平数组无法区分边。 |
| 阵容字段 | 只有 `home_players`/`away_players`（string[]） | 追加 `home_player_ids`/`away_player_ids` | 写 lineup 需要 id，避免前端靠名字反查。 |
| `can_confirm_lineup` | 列在权限集合里 | 保留字段，语义 = `can_edit_lineup`（提交即确认） | 本版没有单独的确认步骤，但按钮字段保留。 |
| `TeamSummary.members` | 可选 | 始终返回 | 避免 B 为显示队伍再发多次请求。 |
| 详情响应 | `TeamTieView` | `TeamTieRuntimeOut`（A3 字段的超集） | A3 详情响应是它的子集，兼容升级。 |
| 阵容有效性 | 无 | 追加 `lineup_valid` / `lineup_invalid_reason` | PR #20 复审：队员被移出名单或队伍退赛后，`start` 会 409；B 可以直接展示原因而不是自己判断。 |

其余字段名与语义与 Draft 一致。B 的 mock（`frontend/src/team/types.ts`）按生成的
`openapi.d.ts` 对齐即可；两处同名文档合并时以本文为准。

## 11. 变更流程

破坏性字段变更必须先由 A/B 同意、Reviewer 确认是否涉及业务规则、更新本文档后再改实现。
本契约与 OpenAPI 保持一致；不能形成第二套长期真相源。
