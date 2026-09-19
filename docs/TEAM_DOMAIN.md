# 团体赛（TEAM）领域基础与边界（A3 + A4.1 + A5 + A6.1）

最近维护：A6.1（Group Tie Generator）。本文只描述**已经落地**的团体赛能力，以及**刻意没做**的部分和原因。
若与代码冲突，以 `backend/app/` 的 Pydantic 契约、SQLite DDL 与测试为准，并在同一 PR 修正本文。
运行态字段、状态机与权限的消费契约见 [Team Runtime Contract](TEAM_RUNTIME_CONTRACT.md)。

## 一句话结论

- A3 交付"团体赛领域地基 + 骨架接口"：
  - `EventType.TEAM` 成为正式枚举值；旧库自动迁移 **`tournaments.event_type` 与 `entries.entry_type`
    两张表**的 CHECK（只迁移前者会让旧库"能建 TEAM 赛事、一建队伍就 500"）；
  - **队伍就是 `entries(entry_type='TEAM')`**，队员就是 `entry_members`，不新建名单表；
  - 新增 `team_ties`（一场"A 队 vs B 队"对抗）与 `team_rubbers`（对抗中的一盘）；
  - 赛制规格 `TeamFormatSpec` + 校验 + 快照 + 骨架构建；
  - 按已登记赛制生成"盘骨架"（每盘需要几个出场位置），**不创建任何普通比赛**。
- A4.1 交付"一场团体对抗的完整 Runtime"：**阵容绑定 → 盘状态机 → 盘比分 → 对抗自动计分 →
  达到获胜盘数自动结束 → 剩余盘 SKIPPED**，并把这些状态、比分、权限通过
  `TeamTieRuntimeOut` 暴露给前端。
- A5 交付"第一个生产可用、版本化的团体赛赛制"：`LOCAL_CLASSIC_5_V1`
  （5 盘、先赢 3 盘、单/单/双/单/单），真实 TEAM 赛事不再需要测试赛制就能建盘并直接进入 Runtime。
  **它只是平台第一版生产模板，不声明等同于任何官方规则**，详见下一节。
- A6.1 交付"团体小组循环对阵生成"：已经分好组的 TEAM 队伍可以**一次性生成组内单循环的全部对抗**
  （`POST .../team-ties/generate-group-ties`），不再需要手工一场一场建对抗。

它仍**不是**完整的团体赛赛事功能：**没有团体小组积分与排名、没有出线/晋级、没有团体淘汰赛**、
不参与排程与预计时间、
赛事阶段 `stage` 也不会因生成对抗而推进。`team_rubbers.match_id` 仍恒为 NULL。

## 团体小组循环对阵生成（A6.1）

### 做什么

对已经分好组的 TEAM 赛事，按 `POST /api/tournaments/{id}/team-ties/generate-group-ties`
一次性生成**组内单循环**的全部 `TeamTie`：

| 场景 | 结果 |
|---|---|
| 1 个 4 队小组 | 6 场（3 轮 × 2 场） |
| 2 个 4 队小组 | 12 场（每组 6 场，绝不跨组） |
| 1 个 3 队小组 | 3 场（3 轮 × 1 场，每轮 1 队轮空） |
| 1 个 5 队小组 | 10 场（5 轮 × 2 场，每轮 1 队轮空） |

返回 `{"ties_generated": 12, "per_group": {"A组": 6, "B组": 6}}`（最小 DTO，见下）。

### 算法与确定性

复用个人赛同一份纯函数 `domain/round_robin.py::round_robin`（固定轮转法 / circle method），
**没有**为团体赛复制第二份算法，也没有为了复用去重构个人赛。每组是一个**独立**的循环：

- 输入顺序 = 该组 `ACTIVE` TeamEntry 按 **`id` 升序**。队伍工作表的 `sort_order` 是名单展示与
  正式队伍顺序；小组循环对阵保留 A6.1 的 `id` 顺序，以避免编辑展示顺序后悄然重排既有编排语义；
- `round`：组内轮次，**从 1 开始**（偶数 N → N-1 轮；奇数 N → N 轮）；
- `match_index`：**轮内**场序，从 1 开始，取 round-robin 在该轮的输出顺序；
- 无随机数、无 `random.shuffle`、不依赖数据库未声明的隐式顺序：
  同样的输入必然得到同样的 `round` / `match_index` / 配对
  （测试逐场比对该组落库结果与 `round_robin()` 的输出）；
- 奇数队伍那一轮的**轮空不落库**：绝不创建 `TeamEntry vs NULL` 这种假对抗，
  也不会为了凑数把轮空做成"系统轮空"的 Match。

### 生成前校验（顺序与错误码）

| 条件 | 结果 |
|---|---|
| 赛事不存在 | 404 |
| 不是 `EventType.TEAM` | 409（该接口仅用于团体赛事） |
| 赛事还没有任何小组 | 409（请先完成分组） |
| 存在 `ACTIVE` 队伍 `group_id IS NULL` | 409，**整批拒绝** |
| 已有任何 `stage=GROUP` 的对抗（手工建立的也算） | 409，不补齐 / 不覆盖 / 不重新生成 |
| 只有 1 支 `ACTIVE` 队伍的小组 | 0 场（不是错误；一场对抗需要两支队伍） |

**为什么"有队伍没分组"必须整批拒绝**：否则会留下一个看起来正常、实际缺失部分对阵的小组赛，
而且事后无法与"手工赛程"区分。**为什么不支持补齐缺失赛程**：手工赛程 + 自动赛程混在一起会产生
重复对阵、`round` 与 `match_index` 冲突以及不完整的赛事事实；"补齐"与"安全撤销团体小组赛"
都是独立课题，本批次不实现。

### 退赛口径（沿用既有规则，不新增语义）

`WITHDRAWN` 队伍**不参与**生成，与 `create_team_tie()` 完全一致（已退赛的队伍不能被安排**新的**对抗）。
退赛后某组只剩 1 支队伍时该组 0 场；"先建对抗、之后队伍才退赛"仍然**不会**被自动判负或改写
（那需要团体赛的异常结果规则，尚未冻结）。

### 原子性与并发

"检查是否已有 GROUP 对抗 → 创建一批对抗"属于 **read-check-write**，与 PR #22 的建盘骨架是同一类问题，
因此整个生成放进 `services/transaction.py::write_transaction`（`BEGIN IMMEDIATE`）：

- 事务**前**的只读校验只是快速失败（请求明显不合法时不必去抢写锁）；
- 拿到写锁后**重新读取**赛事、小组、队伍与已有对抗，再做最终判断与全部写入——
  "读到的状态"与"写入的依据"是同一份事实；
- 两个并发生成请求恰好一个成功：后拿到写锁的请求一定读到前者**已提交**的对抗 →
  稳定 409「团体小组赛已经生成…不能重复生成」；拿不到写锁（前者还在写）→ 409「正在被另一个请求生成」。
  两条路径都不会出现两套赛程，也不会把 `sqlite3.OperationalError` 漏成 500
  （`backend/tests/test_team_group_ties.py` 有并发回归用例，含"未分组 / 手工对抗"等拒绝路径）。

### 刻意不做

- **不推进 `tournaments.stage`**：TEAM 的 `REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED`
  必须与团体排名、晋级、排程一起设计；本批次只生成对抗，赛事阶段保持原样。
- **不批量生成 rubber skeleton**：`build_rubber_skeleton()` 有自己独立的事务与安全契约
  （PR #22 复审），批量调用会造成嵌套写事务；生成后仍按既有接口逐个"选生产赛制 → 建盘"。
- **不做团体小组积分/排名/出线、团体淘汰赛、团体 Scheduler/ETA**：
  这些规则 Reviewer 尚未冻结，代码里**不存在**任何 `team standings` / `qualification` /
  `team knockout` 实现，也没有"胜一场 2 分、负一场 1 分"这类看起来常见但未确认的规则。
- **不做安全撤销/重建团体小组赛**（以后独立设计）。

## Production Team Format V1（A5）

生产注册表 `PRODUCTION_FORMATS` 从 A5 起**不再为空**，当前只有一条：

| 字段 | 值 |
|---|---|
| `code` | `LOCAL_CLASSIC_5_V1` |
| `version` | `1` |
| `display_name` | 经典五盘三胜团体赛 |
| Rubber 数量 | `5` |
| Rubber 类型顺序 | `SINGLES` / `SINGLES` / `DOUBLES` / `SINGLES` / `SINGLES`（sequence 1–5，从 1 连续） |
| `rubbers_to_win` | `3` |
| 位置代号（每边） | 单打 `HOME_R<序>` / `AWAY_R<序>`；双打 `HOME_R3_1`、`HOME_R3_2` / `AWAY_R3_1`、`AWAY_R3_2` |

### 命名与诚实边界（必须保留）

- 这是**平台当前第一版生产赛制模板**，**不声明**等同于某一届 ITTF / 奥运会 / 中国乒协官方规则。
  因此刻意不使用 `ITTF_OFFICIAL` / `ITTF_CLASSIC_V1` / `OLYMPIC` / `NATIONAL_STANDARD` /
  `OFFICIAL_CLASSIC` 这类容易被读成"官方认证"的名字（有测试断言这些 code 一定不存在）。
- 组织者若提供正式赛事规程：**新增**一个版本化 `TeamFormatSpec`（例如 `..._V2` 或新的 code），
  **不覆盖**已经创建的赛事快照。
- 位置代号只是"这一盘这一边的第几个位置"，不是选手，也不是角色。刻意不用 `A/B/C/X/Y/Z`，
  因为那会暗示"某个固定角色 = 某个位置必须由谁上场"，而角色映射恰恰**没有冻结**。
  实际上场人由 Runtime 的 lineup 决定。

### 本版**没有**冻结的规则（因此代码里也不存在）

- 选手角色映射（A/B/C/X/Y/Z 谁打哪个位置）；
- 谁必须打一单 / 二单；
- 双打由哪些人组成、双打组合提交时机；
- 同一人最多参加几盘、单打与双打能否兼项；
- 是否允许替补、替补人数、替补时机；
- 排阵提交时间；
- 是否必须严格按照 `sequence` 开赛；
- 团体小组积分规则、团体排名与晋级。

Runtime 继续只执行已有的通用规则（阵容只做"本队队员 + 队伍在赛 + 盘未结束"这类硬约束），
`services/team_runtime.py` 里**没有**任何 `if format_code == "LOCAL_CLASSIC_5_V1"` 或
`if len(rubbers) == 5: target_wins = 3` 之类的分支——`target_wins` 只从该对抗的
`format_snapshot` 读取，盘数与盘类型只来自 `TeamFormatSpec`。

### 版本化与不可变

`TeamFormat` 是**版本化不可变业务定义**：

- 规则变化**不得**修改旧 code 的语义，必须新增 `LOCAL_CLASSIC_5_V2` 或新的 code；
- 建盘时把 `format_code` + `format_version` + `format_snapshot` 一起冻结在 `team_ties` 上；
- Runtime 与读取路径一律基于 `format_snapshot` 解释，**不重新读取当前注册表**。
  因此即使未来 V1 被改写、被替换、甚至从注册表下线，已创建的 V1 对抗仍按原始规则运行
  （`backend/tests/test_team_format_v1.py` 有对应的快照稳定性测试）。
## 队伍与名单工作表（B）及冻结契约

`/team-roster?tid={id}` 是 TEAM 赛事的独立桌面管理页，主站赛事列表和顶部导航均只在 TEAM 项目中引导至该页。
它以完整草稿一次保存队伍、队员、跨队调换和正式排序：`GET/PUT /api/tournaments/{id}/team-roster` 使用不透明
`revision`，保存在单一 SQLite 写事务中重读版本并原子提交；陈旧草稿返回 409，不会静默覆盖服务器数据。

名单确认仍使用 `POST /api/tournaments/{id}/confirm-roster`，但对 TEAM 的含义已明确为**确认并冻结名单**：

- 确认后，队伍/队员 CRUD、导入、种子和工作表保存全部返回 409，不能绕过冻结直接修改名单；
- 仅在 `REGISTRATION` 阶段、且没有 `PLAYING` 或 `FINISHED` 团体对抗时，可调用
  `POST /api/tournaments/{id}/team-roster/unconfirm` 撤销冻结；
- 撤销后恢复编辑。尚未开始的 `WAITING` 对抗可以保留，但随后改动名单可能让已提交阵容在开始时需重新校验；
- 已有对抗开始或结束后，冻结不可撤销；队伍成员和队内顺序同样不可再改。

这收紧了 A4.1 早期的“赛前可直接改名单、开始时重校验阵容”路径：如果名单已经确认，组织者必须先撤销冻结，
再修改名单并重新确认。赛事单场选手总数统一上限为 120；工作表新增/删除会按保存后的最终人数校验，不能绕过该上限。

## 数据模型

### 队伍：复用 `entries` + `entry_members`

| 概念 | 落库位置 | 说明 |
|---|---|---|
| 队伍（TeamEntry） | `entries.entry_type = 'TEAM'` | 与单打 / 双打参赛位同一张表、同一套接口语义 |
| 队员 | `entry_members(entry_id, player_id, member_order)` | 沿用既有唯一约束 `UNIQUE(player_id)` |
| 队伍人数 | 无独立字段 | 只有下限"至少 1 人"；具体赛制要几人由赛制决定 |

不新建 `teams` / `team_members`：种子、分组、导出、级联删除、成员冲突检测都已经是"围绕 Entry"实现的，
再造一套名单表会立刻产生"两处名单谁是真实来源"的分裂。

### `team_ties`（对抗）

| 列 | 含义 |
|---|---|
| `tournament_id` | 所属赛事（`ON DELETE CASCADE`） |
| `stage` | `GROUP` / `KNOCKOUT`（复用 `MatchStage` 的取值，不新增 `MatchStage.TEAM`） |
| `group_id` / `round` / `match_index` | 小组、轮次、场序（A3 不强制场序唯一，编排属于 A4）；**绑定小组时有归属不变量，见下** |
| `entry_a_id` / `entry_b_id` | 双方队伍，`NOT NULL`，**故意不带 CASCADE**：删队伍必须被业务层拦住 |
| `team_a_score` / `team_b_score` / `winner_entry_id` | 对抗比分与胜者；A3 只读，恒为 0 / NULL |
| `status` | `WAITING` / `PLAYING` / `FINISHED`（A3 只写入初值 `WAITING`） |
| `format_code` / `format_version` / `format_snapshot` | 建盘时固化的赛制；未建盘时为 NULL |
| `called_at` / `started_at` / `finished_at` | 预留的时间字段（与 A2 的比赛时间同口径），A3 不写入 |

### `team_rubbers`（盘）

| 列 | 含义 |
|---|---|
| `team_tie_id` | 所属对抗（`ON DELETE CASCADE`） |
| `sequence` | 第几盘；同一对抗内 `UNIQUE (team_tie_id, sequence)`，从 1 连续 |
| `rubber_type` | `SINGLES` / `DOUBLES`（**没有 TEAM**：TEAM 是赛事项目，不是盘类型） |
| `home_slots_json` / `away_slots_json` | 赛制要求的"位置代号"列表，例如 `["HOME_R3_1","HOME_R3_2"]`（中性位置标识，不是角色、不是选手 id） |
| `home_player_ids_json` / `away_player_ids_json` | **A4.1**：本盘实际参赛人（lineup binding），未绑定时为 NULL |
| `home_score` / `away_score` | **A4.1**：本盘胜局数；未结束为 NULL |
| `winner_entry_id` | **A4.1**：本盘胜方队伍；未结束为 NULL |
| `started_at` / `finished_at` | **A4.1**：本盘开始/结束时间（UTC） |
| `status` | `PENDING` / `READY` / `PLAYING` / `FINISHED` / `SKIPPED`；A4.1 起真正使用状态机 |
| `match_id` | **恒为 NULL**：不把一盘做成普通 Match（原因见下文决策记录） |

位置代号（slot）与实际上场人是两件事：`home_slots` 是赛制要求的槽位，`home_player_ids` 是本盘真实上场的人。
A4.1 的 lineup binding 直接落在盘上（不建 `team_lineups` / `team_lineup_slots`）：一盘的阵容就是这一盘的属性，
等正式排阵规则（兼项、替补、换人历史）冻结后再独立迁移。

### 旧库迁移（两张表 + 运行态列）

旧库的 `tournaments.event_type` 与 `entries.entry_type` 的 CHECK 都只有 `SINGLES/DOUBLES`。
`CREATE TABLE IF NOT EXISTS` 不会修改已有表的 CHECK，所以启动时用同一套安全流程重建这两张表
（`db.py::_rebuild_table_to_allow_team`）：读 `sqlite_master` 判断是否需要迁移（已含 `'TEAM'` 即跳过，
幂等）；`foreign_keys=OFF` + `legacy_alter_table=ON`，使 `entry_members` / `matches` / `team_ties`
等既有子表的 `REFERENCES <表>(id)` 继续指向同名新表；只拷贝"旧列 ∩ 新列"，因此既兼容真正旧库，
也兼容已经带了 #14 退赛审计列的库。新建库 DDL 与迁移 DDL 共用 `TOURNAMENTS_TABLE_SQL` /
`ENTRIES_TABLE_SQL`，并有测试断言两者完全一致。

A4.1 给 `team_rubbers` 追加运行态列时**不重建表**（CHECK 没变）：DDL 提取为
`TEAM_RUBBERS_TABLE_SQL` 供新建库使用，旧库（含 PR #19 已建过的库）通过
`TEAM_RUBBER_RUNTIME_COLUMNS` + `_add_column_if_missing` 原地 `ADD COLUMN` 升级，不要求删除 `demo.db`。

## 赛制：`backend/app/domain/team_formats.py`

- `TeamFormatSpec(code, version, display_name, rubbers_to_win, rubbers[])`；
- `RubberTemplate(sequence, rubber_type, home_slots, away_slots)`；
- `validate_format_spec()` 只校验**规格自洽**：code 非空、version ≥ 1、盘数 ≥ 1、
  盘序从 1 连续且唯一、单打 1 个位置 / 双打 2 个位置、位置代号非空且同侧不重复、
  `1 ≤ rubbers_to_win ≤ 盘数`。它不假设任何一条真实赛事规则；
- `snapshot_dict / dump_snapshot / load_snapshot`：把规格固化为 JSON（含 `snapshot_version`）。
  赛事进行中即使注册表升级，历史对抗仍按创建时的 `format_code + format_version + format_snapshot` 解释；
- `build_rubber_skeleton(spec)`：生成 `status=PENDING` 的盘骨架；
- `PRODUCTION_FORMATS` 只登记**组织者确认冻结的平台模板**。A3 时故意为空；A5 起登记了第一版
  `LOCAL_CLASSIC_5_V1`（见上一节）。注册表**不是**"默认赛制"的来源：未登记的 code 一律 422，
  不会退回任何缺省规则；`TEST_ONLY_*` 之类的测试规格只存在于测试进程内，不进生产注册表。

测试中使用的赛制 code 形如 `TEST_ONLY_*`，只存在于测试进程内（fixture 注册后自动移除），
不通过任何接口暴露，也不代表任何官方规则。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tournaments/{id}/teams` | 队伍列表（返回 `EntryOut`，`entry_type='TEAM'`） |
| POST | `/api/tournaments/{id}/teams` | 新建队伍（`display_name`、`member_ids`、可选 `rating_points`） |
| GET | `/api/tournaments/{id}/teams/{entry_id}` | 单支队伍 |
| PATCH | `/api/tournaments/{id}/teams/{entry_id}` | 改名 / 全量替换队员 / 改积分 |
| DELETE | `/api/tournaments/{id}/teams/{entry_id}` | 删除队伍（已被对抗引用时 409） |
| GET | `/api/tournaments/{id}/team-roster` | TEAM 完整名单工作表及 `revision` |
| PUT | `/api/tournaments/{id}/team-roster` | 原子保存完整队伍/队员草稿（含排序、跨队调换和显式删除） |
| POST | `/api/tournaments/{id}/team-roster/unconfirm` | 在未开赛前撤销 TEAM 名单冻结 |
| GET | `/api/tournaments/{id}/team-ties` | 对抗列表（轻量 `TeamTieOut`，不含阵容/权限） |
| POST | `/api/tournaments/{id}/team-ties` | 建立对抗（双方必须是同一赛事的 TEAM 队伍；绑定小组时须双方同组） |
| POST | `/api/tournaments/{id}/team-ties/generate-group-ties` | **A6.1** 按小组单循环批量生成小组对抗；返回 `{ties_generated, per_group}`；重复生成 / 有队伍未分组 / 非 TEAM 一律 409 |
| GET | `/api/tournaments/{id}/team-ties/{tie_id}` | **对抗运行态**（`TeamTieRuntimeOut`：队伍、比分、盘、权限） |
| POST | `/api/tournaments/{id}/team-ties/{tie_id}/rubber-skeleton` | 按已登记赛制建盘；已存在时 409，`replace=true` 且**所有盘仍为 PENDING 且对抗未进入 Runtime** 时可重建；对抗一旦有盘 READY/PLAYING/FINISHED/SKIPPED 就永久 409 |
| GET | `.../rubbers/{rubber_id}/lineup-options` | 两边的候选阵容（可用性与不可用原因） |
| PUT | `.../rubbers/{rubber_id}/lineup` | 提交本盘实际参赛人（人数按盘型校验） |
| POST | `.../rubbers/{rubber_id}/start` | 开始本盘（READY → PLAYING） |
| POST | `.../rubbers/{rubber_id}/score` | 录入本盘大比分（PLAYING → FINISHED，并自动结算对抗） |

队伍接口的业务守卫：赛事不存在 → 404；不是 TEAM 项目 → 409；不在 `REGISTRATION` 阶段 → 409；
队员为空 / 重复 → 422；队员不属于本赛事 → 404；队员已在别处 → 409；队伍重名 → 409；
已被对抗引用 → 409；已退赛的队伍加入新对抗 → 409；队伍已有对抗开赛后改队员名单 → 409。
全部是业务错误，不会漏成 500。

对抗接口的业务守卫：赛事不存在 → 404；不是 TEAM 项目 → 409；自己打自己 → 422；
赛段非法 → 422；轮次/场序非法 → 422；队伍不存在或不属于本赛事 → 404；不是 TEAM 实体 → 409；
已退赛队伍 → 409；小组不存在或跨赛事 → 404；`KNOCKOUT` 却指定小组 → 422；
绑定小组但双方不同组 → 409。

小组循环生成接口（A6.1）的业务守卫：赛事不存在 → 404；不是 TEAM 项目 → 409；
还没有小组 → 409；有 `ACTIVE` 队伍未分组 → 409（整批拒绝，0 条新增）；
已有任何 `stage=GROUP` 对抗（含手工建立的）→ 409；并发下后者 → 409（不 500）。
**不推进赛事阶段、不建盘、不创建 Match。**

Runtime 写操作的守卫见 [Team Runtime Contract](TEAM_RUNTIME_CONTRACT.md) §8：
404（赛事/对抗/盘/选手不存在）、409（对抗已结束、盘未 READY、已有盘 PLAYING、阵容已锁定、
队员不属于队伍、缺少赛制快照）、422（人数与盘型不符、同边重复队员、比分不合法）。

## 明确未实现（后续批次待办清单）

1. **赛事规程版本化**：第一版生产模板已登记（`LOCAL_CLASSIC_5_V1`）。组织者提供正式规程后
   必须**新增**版本化 `TeamFormatSpec`，不覆盖旧版本；未登记的赛制仍一律 422。
2. **对抗编排**：小组内循环编排已由 **A6.1** 完成（见上文「团体小组循环对阵生成」）。
   仍然未实现的是：**团体淘汰赛结构**、**场序唯一性约束**（`round`/`match_index` 由生成器稳定产出，
   但数据库层没有唯一索引，手工建对抗仍可重复）、以及**安全撤销/重建团体小组赛**。
3. **盘 → 比赛适配器**：`team_rubbers.match_id` 未启用（原因见下节）；盘有自己的运行态比分。
4. **异常结果与改分**：弃权/未到/取消资格与 `revise score` 未实现（`can_revise_score` 恒 false）；
   逐局小比分也不建（一团体的盘只记大比分，复用赛事 `games_to_win`）。
5. **排程 / 球台 / 预计时间**：团体赛不进入调度器与 ETA。一场对抗是否占一张球台、各盘能否并行、
   兼项选手如何避免撞台——这些问题**尚未冻结**，`services/scheduling.py` 与 `services/eta.py` 未改动。
   当前同一对抗**串行**执行（同时最多一盘 PLAYING），这是简化而不是现场规则。
   （A6.1 生成的小组对抗同样不参与排程：`round`/`match_index` 只是编排序号，不是时间计划。）
6. **团体排名与晋级**：`domain/ranking.py` 是单打/双打口径的胜场-净胜局-积分算法，没有团体赛排名。
   A6.1 只生成对阵，**不**计算团体小组积分/排名/出线，也不决定晋级。
7. **队伍种子**：团体赛种子规则未冻结；`entries.rating_points` 默认 0，只接受显式传入，
   绝不按队员积分求和或推导；打分赛的「按积分生成种子」对 TEAM / DOUBLES 都返回 409。
8. **Demo 模拟**：`demo/finish-group-stage` 与小组赛/淘汰赛生成接口对 TEAM 一律 409，不伪造团体赛结果。
9. **删除与审计**：删赛事会级联清掉 `team_ties` / `team_rubbers`（有测试）；
    但团体赛的归档与操作审计仍沿用 A1.1 的待办（尚未实现）。

## 小组归属不变量（PR #19 Reviewer 修正）

`team_ties.group_id` 与 `entries.group_id` 不允许互相矛盾。建立对抗时：

| 请求 | 结果 |
|---|---|
| `stage=GROUP` + `group_id=NULL` | 允许（还没绑定具体小组的通用对抗；A3 保持这个 contract 不变） |
| `stage=GROUP` + `group_id` 指定 | **双方队伍的 `entries.group_id` 必须都等于该小组**，否则 409：双方未分组、只有一方分组、双方在别的组、双方分处两组全部拒绝 |
| `stage=KNOCKOUT` + `group_id` 指定 | 422（淘汰赛段不挂小组） |

拒绝时返回 409（请求结构合法但当前领域状态冲突），且不会写入任何对抗行。这样后续的小组排名、
晋级、导出、重分组不必再猜 `team_ties.group_id` 和 `entries.group_id` 哪个才是真实来源。

## 与整项退赛（`#14`）的交互

整项退赛已合入基线：`entries` 增加 `withdrawn_at / withdrawn_by / withdrawal_reason`，
`POST /api/tournaments/{id}/entries/{entry_id}/withdraw` 会把参赛位标记为 `WITHDRAWN`，
并且分组、生成比赛、排名与淘汰晋级都只认 `ACTIVE` 的参赛位。团体赛沿用同一口径：

- **已退赛的队伍不计入**名单确认的"至少 2 支在赛队伍"，也不能被安排**新的**团体对抗（409）；
- 已退赛队伍里的选手仍然算"有队"——不强迫组织者删除历史队伍名单；
- **先建立对抗、之后队伍才退赛**时，A3 **不会**自动判负或改写对抗：`team_ties` 的比分、
  状态与已生成的盘骨架都保持原样。对抗层面的退赛判定需要团体赛的盘比分与状态机（A4），
  A3 不伪造对抗结果。

A6.1 的小组循环生成沿用这一口径，**没有新增退赛语义**：
已退赛队伍不参与生成（不会得到新的对抗），退赛到只剩 1 支在赛队伍的小组生成 0 场对抗
（不伪造 `队伍 vs NULL`，也不把退赛队伍拉回来凑数）。

## 关键决策记录：为什么一盘不是一场 Match

A3 刻意**不**为任何一盘创建 `matches` 行：

1. `entry_members` 对 `player_id` 有全局 `UNIQUE` 约束，一名选手最多属于一个参赛实体。
   一场双打盘需要两名选手同时上场；若把"盘"做成普通 Match，就必须为每一盘再建 Entry、
   把选手从队伍 Entry 里挪出来 → 直接违反唯一约束。
2. `services/scheduling.py::_match_member_ids()` 会把 Entry 的**全部**成员标记为占用。
   若把队伍 Entry 当作比赛一方，排台会把整队人一次性标记为"正在比赛"，明显错误。
3. 比分展示、冲突检测、ETA、名次推导都建立在"一场比赛 = 两个参赛位、最多两名选手"的假设上。

因此 A3 只落"骨架"（第几盘、单打/双打、每边几个位置），把"盘 ↔ 比赛"的映射连同球台占用与
兼项校验一起留给后续批次 —— 那需要独立的适配器与新表，而不是把团体赛塞进现有 Match。

**A4.1 继续沿用这个边界**：盘有了自己的运行态比分、胜者与起止时间，`match_id` 仍然恒为 NULL。
团体赛 MVP 不再被"架构统一"阻塞；以后若确实要统一到 Match，再独立做 adapter 与迁移。

## Runtime Engine（A4.1）

一盘的完整闭环（详细契约见 [Team Runtime Contract](TEAM_RUNTIME_CONTRACT.md)）：

```
PENDING ──提交合法阵容──▶ READY ──start──▶ PLAYING ──score──▶ FINISHED
                              │
                              └── 对抗被提前结束（一方达到 target_wins）──▶ SKIPPED
```

- 阵容落在盘上（`home_player_ids_json` / `away_player_ids_json`），人数按盘型（单打 1 / 双打 2）；
  只做通用硬约束，不实现"最多打一盘 / 不能兼项 / 必须一单一双"等未冻结规则。
- 盘比分只记大比分，复用个人赛同一套合法性规则（`scores.validate_aggregate_score`）。
- 对抗总分 `team_a_score` / `team_b_score` 由后端按 FINISHED 的盘重算，没有直接改对抗比分的接口。
- `target_wins` 只从赛制快照读取；达到后对抗自动 FINISHED，剩余未打的盘自动 SKIPPED。
- 串行执行（同时最多一盘 PLAYING）、不强制盘序、不接 scheduler/ETA、不创建 Match。
- **名单冻结与阵容失效**：提交阵容时校验"选手属于本队、队伍在赛"；**开始一盘时原子重校验已保存的阵容**
  （队员被移出名单或队伍退赛后 `start` 返回 409，可重新提交阵容）；队伍一旦有对抗进入
  `PLAYING`/`FINISHED`，`PATCH /teams` 改队员返回 409（改名/积分不受影响）。
- **并发安全**：写操作把"读-判断-写"放进 `BEGIN IMMEDIATE` 写事务，写入使用带预期旧状态的条件更新
  （并检查 rowcount），跨行不变量在任何写入之前校验——并发请求无法绕过"最多一盘 PLAYING / 不允许改分"。
- **建盘骨架同样是写操作（PR #22 复审 P1）**：`build_rubber_skeleton()` 的"查已有盘 → 判断重复 →
  插入"也是 read-check-write，必须与 Runtime 写操作上同一把写锁。写锁在读取之前取得，因此两个并发
  `POST .../rubber-skeleton` 只可能有一个成功，另一个稳定拿到 **409**（"该对抗已生成 N 盘骨架"），
  最终只有一套盘（5 盘制就是 5 条，不会变成 10 条）；修复前后提交者会撞
  `UNIQUE (team_tie_id, sequence)` 抛 `sqlite3.IntegrityError`，用户看到 500。
- **写事务只有一份实现**：`services/transaction.py::write_transaction(conn, *, busy_message,
  conflict_message)` 提供 `BEGIN IMMEDIATE` + 回滚 + 锁超时映射，`team_runtime._write_tx` 与
  `team_ties.build_rubber_skeleton` 共同复用（`team_runtime` 仍负责把异常翻译成自己的业务错误）。
  这样"又一处 read-check-write"不需要再抄第三份事务代码。

## 阶段门禁现状（为什么对抗创建与小组赛生成都不校验 stage）

TEAM 赛事目前**没有任何接口**能把 `stage` 从 `REGISTRATION` 推进到 `GROUP_STAGE`：
`generate_group_matches()` 与 `generate_knockout()` 对 TEAM 显式 409，`confirm-roster` 只写
`roster_confirmed`，不改 stage。如果 TeamTie 创建要求"必须已开赛"，就等于永久禁止创建对抗。
所以对抗创建只校验"赛事是 TEAM 项目 + 双方合法"，阶段门禁与团体赛排程一起设计。
队伍编辑仍按既有规则锁定在 `REGISTRATION`（与选手/名单一致）。

A6.1 的小组循环生成**同样不挂 stage 门禁**，也不推进 stage（只校验"是 TEAM + 已分组 +
无未分组在赛队伍 + 无既有小组对抗"）。理由完全一致：`stage` 无法推进，用它做门禁等于永久禁止
生成小组赛；而 TEAM 阶段推进规则必须与团体排名、晋级、排程一起冻结。
生成小组对抗后赛事仍停在 `REGISTRATION`，这是**已知且刻意**的状态，不是 bug。

关于 `roster_confirmed`：它是 TEAM **名单编辑写入的冻结锁**，确认后队伍/队员 CRUD、导入、
种子和工作表保存都返回 409；但它**不是**小组对抗生成门禁，也不推进赛事阶段（见
`services/teams.py` 的边界说明）。现有 contract 里没有"未确认名单不能生成正式小组赛"这条规则，
因此本批次没有新增它——凭空收紧会挡住当前可用的流程（手工分组后即可生成），而"名单是否准备好"
已由"必须先有小组 + 队伍必须已分组"间接覆盖。

## 验证

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
.\backend\.venv\Scripts\python.exe backend/export_openapi.py --check
pnpm -C frontend run build
```

- `backend/tests/test_team_migration.py`：`tournaments.event_type` 与 `entries.entry_type` 的旧 CHECK
  都写不进 TEAM（前提）；迁移后数据、id、退赛审计列与子表外键全部保留（`REFERENCES tournaments(id)` /
  `REFERENCES entries(id)` 不被改写成 legacy 表名）；真实链路"旧库 → init_db → TEAM 赛事 → 选手 →
  `create_team_entry()` 成功"；迁移后的 DDL 与新建库 DDL 完全一致；重复执行幂等且无 legacy 表残留。
- `backend/tests/test_team_entries.py`：队伍增删改查与全部业务守卫、名单确认三分支、
  "1 人队伍不被当成单打实体播种"等二元假设回归、TEAM 赛事自动分组、退赛队伍不计入名单确认。
- `backend/tests/test_team_domain.py`：赛制校验/快照、生产注册表只含确认过的模板、建盘不创建 Match、
  重建守卫、单打引擎拒绝 TEAM、导出与级联、小组归属不变量（未分组 / 跨组 / 同组 / 跨赛事小组）
  与服务层 + API 层全流程。
- `backend/tests/test_team_format_v1.py`（A5）：生产赛制 `LOCAL_CLASSIC_5_V1` 的注册表边界、
  盘序与中性位置代号、真实建盘 5 盘、Runtime 契约（`target_wins` / `format.*` / `rubbers`）、
  **生产赛制端到端闭环**（打到 3 胜 → 提前结束 → 剩余盘 SKIPPED）、2:2 时第 5 盘仍能正常打、
  快照抗注册表改写/替换/下线、未登记赛制 422、非 TEAM 赛事拒绝、重复建盘与开赛后禁止换赛制、
  API 层真实 `/rubber-skeleton` 全流程。
- `backend/tests/test_team_runtime.py`（A4.1）：完整 E2E（阵容 → 开始 → 录分 → 累计 → 达标结束 →
  剩余 SKIPPED）、target_wins 来自快照、全部状态机失败场景与错误码、权限矩阵、候选阵容规则、
  非法比分、"两盘同时 PLAYING"的防御、PR #19 旧库升级运行态列、导出运行态且只读。
- `backend/tests/test_team_group_ties.py`（A6.1）：4 队单组 6 场 / 两个 4 队组 12 场且不跨组 /
  3 队 3 场 / 5 队 10 场、**逐场比对落库结果与 `round_robin()` 输出**（round / match_index / 配对）、
  未分组队伍整批拒绝且 0 条新增、非 TEAM 409、赛事不存在 404、重复生成 409 且不翻倍、
  手工对抗存在时 409 且不补齐不覆盖、淘汰赛对抗不阻塞小组生成、退赛队伍不参与生成、
  并发双生成"一个成功 + 一个 409"（多轮，含 read-check-write 竞态路径）、写锁争用返回可读 409、
  生成不改 stage / 不建 Match / 不建盘骨架、**自动生成的对抗继续跑 LOCAL_CLASSIC_5_V1 →
  骨架 → 阵容 → start → 录分**，以及 API 层契约用例。
- `backend/tests/test_round_robin_domain.py`（A6.1）：单循环算法的通用不变量（n=2…12）——
  场数 `n(n-1)/2`、每个 unordered pair 恰好一次、无自己打自己、每轮每队至多一次、
  偶数/奇数轮数结构、奇数队伍每轮恰好一支轮空、确定性（重复运行完全一致）。
- `backend/tests/test_tournament_delete_reliability.py`：团体赛级联删除用例。
