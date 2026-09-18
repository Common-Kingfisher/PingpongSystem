# 团体赛（TEAM）领域基础与边界（A3）

最近维护：A3 批次。本文只描述**已经落地**的团体赛领域基础，以及**刻意没做**的部分和原因。
若与代码冲突，以 `backend/app/` 的 Pydantic 契约、SQLite DDL 与测试为准，并在同一 PR 修正本文。

## 一句话结论

A3 交付的是"团体赛领域地基 + 只读/骨架接口"：

- `EventType.TEAM` 成为正式枚举值；旧库自动迁移 **`tournaments.event_type` 与 `entries.entry_type`
  两张表**的 CHECK（只迁移前者会让旧库"能建 TEAM 赛事、一建队伍就 500"）；
- **队伍就是 `entries(entry_type='TEAM')`**，队员就是 `entry_members`，不新建名单表；
- 新增 `team_ties`（一场"A 队 vs B 队"对抗）与 `team_rubbers`（对抗中的一盘）；
- 赛制规格 `TeamFormatSpec` + 校验 + 快照 + **空的生产注册表**；
- 按已冻结赛制生成"盘骨架"（每盘需要几个出场位置），**不创建任何普通比赛**。

它**不是**可用的团体赛赛事功能：没有队伍名单界面、没有任何一条赛制被冻结、没有对阵编排、
没有比分与状态机、不参与排程与预计时间。真正的团体赛比赛能力属于后续 A4 批次。

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
| `home_slots_json` / `away_slots_json` | 每边需要的"位置代号"列表，例如 `["H3","H4"]` |
| `status` | `PENDING` / `READY` / `PLAYING` / `FINISHED` / `SKIPPED`；A3 只产生 `PENDING` |
| `match_id` | **A3 恒为 NULL**，预留给 A4 的"盘 → 比赛"适配器 |

位置代号不是选手 id：把选手填进位置（出场名单 / 兼项校验）属于 A4。

### 旧库迁移（两张表，不只是 tournaments）

旧库的 `tournaments.event_type` 与 `entries.entry_type` 的 CHECK 都只有 `SINGLES/DOUBLES`。
`CREATE TABLE IF NOT EXISTS` 不会修改已有表的 CHECK，所以启动时用同一套安全流程重建这两张表
（`db.py::_rebuild_table_to_allow_team`）：读 `sqlite_master` 判断是否需要迁移（已含 `'TEAM'` 即跳过，
幂等）；`foreign_keys=OFF` + `legacy_alter_table=ON`，使 `entry_members` / `matches` / `team_ties`
等既有子表的 `REFERENCES <表>(id)` 继续指向同名新表；只拷贝"旧列 ∩ 新列"，因此既兼容真正旧库，
也兼容已经带了 #14 退赛审计列的库。新建库 DDL 与迁移 DDL 共用 `TOURNAMENTS_TABLE_SQL` /
`ENTRIES_TABLE_SQL`，并有测试断言两者完全一致。

## 赛制：`backend/app/domain/team_formats.py`

- `TeamFormatSpec(code, version, display_name, rubbers_to_win, rubbers[])`；
- `RubberTemplate(sequence, rubber_type, home_slots, away_slots)`；
- `validate_format_spec()` 只校验**规格自洽**：code 非空、version ≥ 1、盘数 ≥ 1、
  盘序从 1 连续且唯一、单打 1 个位置 / 双打 2 个位置、位置代号非空且同侧不重复、
  `1 ≤ rubbers_to_win ≤ 盘数`。它不假设任何一条真实赛事规则；
- `snapshot_dict / dump_snapshot / load_snapshot`：把规格固化为 JSON（含 `snapshot_version`）。
  赛事进行中即使注册表升级，历史对抗仍按创建时的 `format_code + format_version + format_snapshot` 解释；
- `build_rubber_skeleton(spec)`：生成 `status=PENDING` 的盘骨架；
- **`PRODUCTION_FORMATS = {}` 是故意的**。团体赛赛制差异极大（几单几双、是否必须打满、
  双打能否兼项、决胜盘规则……），必须由赛事组织方确认冻结后才能登记。A3 不臆造
  "奥运赛制 / ITTF 经典赛制"之类的规则，也不在代码里放一个"默认赛制"。
  因此当前生产环境下调用建盘接口一律返回 **422 未知的团体赛赛制**。

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
| GET | `/api/tournaments/{id}/team-ties` | 对抗列表 |
| POST | `/api/tournaments/{id}/team-ties` | 建立对抗（双方必须是同一赛事的 TEAM 队伍；绑定小组时须双方同组） |
| GET | `/api/tournaments/{id}/team-ties/{tie_id}` | 对抗详情（含盘骨架） |
| POST | `/api/tournaments/{id}/team-ties/{tie_id}/rubber-skeleton` | 按已登记赛制建盘；已存在时 409，`replace=true` 且全部盘仍为 PENDING 时可重建 |

队伍接口的业务守卫：赛事不存在 → 404；不是 TEAM 项目 → 409；不在 `REGISTRATION` 阶段 → 409；
队员为空 / 重复 → 422；队员不属于本赛事 → 404；队员已在别处 → 409；队伍重名 → 409；
已被对抗引用 → 409；已退赛的队伍加入新对抗 → 409。全部是业务错误，不会漏成 500。

对抗接口的业务守卫：赛事不存在 → 404；不是 TEAM 项目 → 409；自己打自己 → 422；
赛段非法 → 422；轮次/场序非法 → 422；队伍不存在或不属于本赛事 → 404；不是 TEAM 实体 → 409；
已退赛队伍 → 409；小组不存在或跨赛事 → 404；`KNOCKOUT` 却指定小组 → 422；
绑定小组但双方不同组 → 409。

## 明确未实现（A4+ 待办清单）

1. **队伍名单界面**：前端只有"项目名标签 + 契约薄封装"，没有队伍增删改界面。
2. **赛制冻结**：需要组织者确认后写入 `PRODUCTION_FORMATS` 并定 version；当前注册表为空。
3. **对抗编排**：小组内/淘汰结构的对阵生成（抽签、循环编排、场序唯一）未实现，A3 只允许手工建立对抗。
4. **盘 → 比赛适配器**：`team_rubbers.match_id` 未启用（原因见下节）。
5. **比分与状态机**：对抗比分、盘比分、`PENDING → READY → PLAYING → FINISHED / SKIPPED` 流转未实现。
6. **排程 / 球台 / 预计时间**：团体赛不进入调度器与 ETA。一场对抗是否占一张球台、各盘能否并行、
   兼项选手如何避免撞台——这些问题**尚未冻结**，`services/scheduling.py` 与 `services/eta.py` 未改动。
7. **团体排名与晋级**：`domain/ranking.py` 是单打/双打口径的胜场-净胜局-积分算法，没有团体赛排名。
8. **队伍种子**：团体赛种子规则未冻结；`entries.rating_points` 默认 0，只接受显式传入，
   绝不按队员积分求和或推导；打分赛的「按积分生成种子」对 TEAM / DOUBLES 都返回 409。
9. **Demo 模拟**：`demo/finish-group-stage` 与小组赛/淘汰赛生成接口对 TEAM 一律 409，不伪造团体赛结果。
10. **删除与审计**：删赛事会级联清掉 `team_ties` / `team_rubbers`（有测试）；
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

## 关键决策记录：为什么一盘不是一场 Match

A3 刻意**不**为任何一盘创建 `matches` 行：

1. `entry_members` 对 `player_id` 有全局 `UNIQUE` 约束，一名选手最多属于一个参赛实体。
   一场双打盘需要两名选手同时上场；若把"盘"做成普通 Match，就必须为每一盘再建 Entry、
   把选手从队伍 Entry 里挪出来 → 直接违反唯一约束。
2. `services/scheduling.py::_match_member_ids()` 会把 Entry 的**全部**成员标记为占用。
   若把队伍 Entry 当作比赛一方，排台会把整队人一次性标记为"正在比赛"，明显错误。
3. 比分展示、冲突检测、ETA、名次推导都建立在"一场比赛 = 两个参赛位、最多两名选手"的假设上。

因此 A3 只落"骨架"（第几盘、单打/双打、每边几个位置），把"盘 ↔ 比赛"的映射连同球台占用与
兼项校验一起留给 A4 —— 那需要独立的适配器与新表，而不是把团体赛塞进现有 Match。

## 阶段门禁现状（为什么对抗创建不校验 stage）

TEAM 赛事目前**没有任何接口**能把 `stage` 从 `REGISTRATION` 推进到 `GROUP_STAGE`：
`generate_group_matches()` 与 `generate_knockout()` 对 TEAM 显式 409，`confirm-roster` 只写
`roster_confirmed`，不改 stage。如果 TeamTie 创建要求"必须已开赛"，就等于永久禁止创建对抗。
所以 A3 的对抗创建只校验"赛事是 TEAM 项目 + 双方合法"，阶段门禁与 A4 的团体赛排程一起设计。
队伍编辑仍按既有规则锁定在 `REGISTRATION`（与选手/名单一致）。

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
- `backend/tests/test_team_domain.py`：赛制校验/快照、生产注册表为空、建盘不创建 Match、
  重建守卫、单打引擎拒绝 TEAM、导出与级联、小组归属不变量（未分组 / 跨组 / 同组 / 跨赛事小组）
  与服务层 + API 层全流程。
- `backend/tests/test_tournament_delete_reliability.py`：团体赛级联删除用例。
