# PingpongSystem 开发交接

最近维护：2026-09-18（A6.3 / A6.4）。当前集成分支：`develop/field-demo-v02`；精确基线以该分支最新提交为准。

维护规则：每个功能 PR 必须同步更新相关 Markdown、OpenAPI 快照（接口变化时）和 `CHANGELOG.md`；不再把文档集中留到最后补写。

## V0.3 D7B 个人赛规则冻结

新版 B 轨（规则／比赛引擎）已进入 Release Candidate 冻结候选，覆盖 `ROUND_ROBIN`、`SINGLE_ELIMINATION`、`GROUP_KNOCKOUT`、比分与逐局分一致性、异常赛果、改分保护、BYE、种子、Affiliation、同分与人工裁定边界。精确规则与自动化回归入口见 [D7B 规则冻结说明](D7B_RULE_FREEZE.md)。

`WORKSTREAM_B.md` 记录的是已结束的 V0.2／旧 Dev B 现场 UI 工作线，**不等同于**新版 B 轨。

## 先看结论

当前版本已具有“报名 → 确认名单 → 分组 → 小组比赛 → 排名 → 单淘汰 → 季军/排位 → 冠军展示”的主要链路，是可以继续联调的 Demo 基线，**不是已经通过完整现场验收的 V0.2 发布版**。下一步优先修复规则边界和改分保护，再完善现场调度、秩序册和大规模验证。

正式开发目录为 `pingpong_plantform`。`teammate-draft/pingpong_plantform` 是旧副本；`frontend-demo` 是早期独立视觉原型，不是当前应用入口。交接前，正式目录与 `teammate-draft/pingpong_plantform` 的 95 个源码、配置和文档文件内容一致，依赖、数据库和缓存未参与比较。今后只在正式目录开发，避免双副本漂移。

仓库：[Common-Kingfisher/PingpongSystem](https://github.com/Common-Kingfisher/PingpongSystem)。当前新增 120 人规模验收数据与自动化闭环测试，详见 [120 人规模验收数据](SCALE_VALIDATION_120.md)。

## 阅读顺序

1. 本文：接手、运行、模块和验证情况。
2. [V0.2 对比](V02_COMPARISON.md)：原稿要求、后续确认、当前差距。
3. [开发路线](DEVELOPMENT_ROADMAP.md)：优先级、风险、责任边界和验收门槛。
4. [团体赛领域基础与边界](TEAM_DOMAIN.md)：TEAM 数据模型、赛制规格、接口清单、
   小组循环对阵生成（A6.1）、团体小组排名（A6.2）与"刻意没做"的部分。
5. [团体小组排名规则 V1](TEAM_GROUP_RULES_V1.md)：团体小组排名的**唯一业务规则源**
   （比赛积分、同分子集重算、盘/局比率、并列区间、provisional 与退赛口径）。
6. [团体晋级与淘汰签规则 V1](TEAM_QUALIFICATION_KNOCKOUT_V1.md)：团体**晋级判定**与**淘汰签生成**的
   唯一业务规则源（晋级线并列处理、人工确认校验、相邻组交叉配对、复用的数据模型）。
7. [Team Runtime Contract](TEAM_RUNTIME_CONTRACT.md)：A/B 消费契约（运行态字段、状态机、权限、错误码）。
8. [V0.3 D7B 规则冻结说明](D7B_RULE_FREEZE.md)：个人赛 Release Candidate 的规则边界与回归入口。
9. `PingpongSystem_交接与开发路线.docx`：面向队友的综合阅读版；精确字段和命令以本目录 Markdown、Pydantic 与 OpenAPI 为准。

若文档与代码冲突，以 Pydantic/OpenAPI 和已通过的测试为准，并在同一 PR 修正文档，不能长期保留已知过期说明。

## 已确认的产品范围

- 保留 React + TypeScript + Vite + FastAPI + SQLite，不搬回 Next.js 原型。
- 单打和双打；双打按运动员积分相近进行随机配对，不等于“强弱搭配使各队实力均衡”。
- 比赛第一次上台记录开赛时间，第一次完赛记录结束时间；赛后改分不覆盖这两个事实时间。
- 比分修改必须填写操作人与修改理由，系统保存修改前后完整快照和不可覆盖的操作历史。
- 默认三局两胜、每局 11 分；创建赛事时可在三局两胜 / 五局三胜 / 七局四胜与每局目标分之间选择；常规只录大比分，输入初值为 0。
- 种子按赛事隔离：可在选手页手工排序，也可「按积分生成种子」（单打，积分降序、同分按选手编号）；选手种子与 Entry 种子在每次修改后同步，分组与签表按同一份种子执行。双打种子规则尚未冻结，不套用该规则。
- 比赛时间（A2）：`matches.called_at` = 最近一次安排上球台的时间；`started_at` = 当前有效进行中比赛的开始时间（下球台后置空，重新安排时重写）；`finished_at` = 当前有效比赛产生结果的时间（改分不改动）。三者统一为 UTC SQLite 时间戳 `YYYY-MM-DD HH:MM:SS`，只由 `repository.mark_match_playing / mark_match_waiting / mark_match_finished` 写入；系统轮空不写时间（派生结果）；未排台直接录分只写 `finished_at`，不伪造开始时间。
- 真实耗时与典型耗时（A2）：只有"有开始与结束时间 + 结果类型 NORMAL"的比赛进入耗时样本；系统轮空、未排台直接录分、弃权/未到/取消资格都不计入。赛事典型耗时取中位数，样本不足 3 场时使用按赛制定义的冷启动估算值（技术估算参数，未来可配置）。
- 预计上场时间（A2，`GET /api/tournaments/{id}/schedule-estimates`）：只读模拟，复用自动排台同一套规则（硬约束 → 组台亲和 → 组间进度公平 → 连续上场软惩罚 → 稳定顺序），进行中的比赛按"最大(下限, 典型时长 − 已进行)"推进；签位未定的后续轮次与超出模拟范围的比赛返回 null。
- 团体赛（A3）当前范围：这是**领域地基，不是可用的团体赛功能**，详见 [团体赛领域基础与边界](TEAM_DOMAIN.md)。
  - `EventType` 增加 `TEAM`；旧库启动时自动迁移 **`tournaments.event_type` 与 `entries.entry_type` 两张表**的 CHECK（SQLite 不能直接改 CHECK，需要重建；数据、id、退赛审计列与子表外键都保留，幂等）。只迁移前者会让旧库"能建 TEAM 赛事、一建队伍就 500"。
  - 队伍即参赛实体（`entries.entry_type='TEAM'`），队员即 `entry_members`；**不新建 `teams` / `team_members` 表**。队伍人数只有下限"至少 1 人"，具体人数规则属于赛制（未冻结）。
  - 新增 `team_ties`（一场"A 队 vs B 队"对抗，含赛制快照与预留时间字段）与 `team_rubbers`（盘骨架：单打/双打 + 每边所需出场位置代号）。
  - 小组归属不变量：`GROUP` + 指定小组时，双方队伍的 `entries.group_id` 必须都等于该小组，否则 409；`GROUP` + 不指定小组仍是允许的通用对抗；`KNOCKOUT` 不得挂小组（422）。避免 `team_ties.group_id` 与 `entries.group_id` 互相矛盾。
  - 赛制（`domain/team_formats.py`）：`TeamFormatSpec` + 校验 + 快照 + 骨架构建。生产注册表只登记
    组织者确认过的版本化模板——A3 时为空，**A5 起为 `LOCAL_CLASSIC_5_V1`**（见下条）。
    未登记的赛制建盘一律 422，系统不臆造"经典赛制"，也不会退回任何"默认赛制"；
    测试用赛制（`TEST_ONLY_*`）仅存在于测试进程内，不进生产注册表。
  - **一盘不是一场 Match**：A3 不创建任何 `matches` 行，`team_rubbers.match_id` 恒为 NULL（原因：`entry_members` 对 player 全局唯一，且 `_match_member_ids()` 会把整队成员标记为占用）。盘 ↔ 比赛的映射、球台占用与兼项校验留给 A4。
  - 未实现：正式 TEAM 前端入口（队伍名单界面）、**出线与晋级写入**（团体小组排名已由 A6.2 完成）、
    团体淘汰赛、团体赛排程/ETA、队伍种子、Demo 模拟（对 TEAM 明确 409）。
  - 阶段门禁现状：TEAM 赛事目前没有任何接口能把 `stage` 从 `REGISTRATION` 推进（生成小组赛/淘汰赛对 TEAM 直接 409），因此对抗创建不挂 stage 门禁；队伍编辑仍锁定在 `REGISTRATION`。
  - 与整项退赛（`#14`，同批基线）的口径一致：已退赛队伍不计入"至少 2 支在赛队伍"，也不能加入新对抗；但"先建对抗、后队伍退赛"不会被 A3 自动判负（需要 A4 的比分层），对抗与盘骨架保持原样。
- 团体赛 Runtime（A4.1，`docs/TEAM_RUNTIME_CONTRACT.md`）：一场对抗现在可以完整跑完。
  - 状态机：一盘 `PENDING →(提交合法阵容) READY →(start) PLAYING →(score) FINISHED`；对抗被一方提前结束时，未打的 `PENDING/READY` 盘 → `SKIPPED`（`FINISHED` 的盘不动）。
  - 阵容落在盘上（`team_rubbers.home_player_ids_json / away_player_ids_json`），人数按盘型校验（单打 1 / 双打 2），只允许本队队员；不实现"最多打一盘 / 不能兼项 / 必须一单一双 / 强制盘序"等未冻结规则。
  - 盘只记大比分，复用个人赛同一套规则（`scores.validate_aggregate_score`）；不建逐局小比分，不做异常结果与改分（`can_revise_score` 恒 false）。
  - 对抗总分由后端按 `FINISHED` 的盘重算，没有"直接提交对抗比分"的接口；`target_wins` 只从赛制快照读取，达到后自动 `FINISHED`（写胜者与结束时间）。
  - **串行执行**：同一对抗同时最多一盘 `PLAYING`；不接 scheduler / ETA，`team_rubbers.match_id` 仍恒为 NULL。
  - 旧库升级：`team_rubbers` 运行态列走 `_add_column_if_missing`，不需要删库重建。
  - 读取与写操作统一返回 `TeamTieRuntimeOut`（含 `permissions`）；前端按钮直接消费权限字段，不自行推断。
  - **名单冻结与阵容失效（PR #20 复审补强）**：队伍有对抗进入 PLAYING/FINISHED 后禁止改队员（改名/积分不受影响）；
    开始一盘时原子重校验已保存阵容（队员被移出名单 / 队伍退赛 → 409，可重新提交），运行态给出 `lineup_valid`。
  - **并发安全（PR #20 复审补强）**：写操作 = `BEGIN IMMEDIATE` 写事务 + 带预期旧状态的条件更新 + rowcount 检查；
    跨行不变量（最多一盘 PLAYING）在任何写入之前校验。并发双 start / 双 score 都有回归测试（两个独立连接）。
  - **建盘骨架的写事务（PR #22 复审补强）**：`build_rubber_skeleton()` 与 Runtime 共用
    `services/transaction.py::write_transaction`；原先它在事务外 read-check-write，两个并发建盘请求都能读到
    "还没有盘"、后提交者撞 `UNIQUE (team_tie_id, sequence)` 变成 500，现在稳定 409 且只留一套盘。
    `register_format_spec()` 同时改为拒绝覆盖已登记的 format code（不再静默改写已发布版本）。
- 团体赛生产赛制 V1（A5，`docs/TEAM_DOMAIN.md` 的「Production Team Format V1」）：
  生产注册表现在**不再为空**，登记了平台第一版模板 `LOCAL_CLASSIC_5_V1`（version 1，
  显示名「经典五盘三胜团体赛」，5 盘、先赢 3 盘、`SINGLES/SINGLES/DOUBLES/SINGLES/SINGLES`，
  位置代号为中性 `HOME_R*` / `AWAY_R*`）。
  - 当前真实能力链路：**TEAM 赛事 → 队伍 → 确认名单 → `TeamTie` → 生产 `TeamFormat` →
    5 盘 rubber skeleton → Runtime（阵容 → 开始 → 录分 → 累计 → 3 胜结束 → 剩余盘 SKIPPED）**，
    **不再需要 `TEST_ONLY_*` 赛制**。
  - **不宣称官方规则**：这是平台自己的第一版生产模板，不等同于任何一届 ITTF / 奥运会 / 中国乒协规程；
    刻意不使用 `ITTF_*` / `OLYMPIC` / `NATIONAL_STANDARD` 这类名字。组织者给出正式规程后
    **新增**版本化 `TeamFormatSpec`（例如 `..._V2`），不覆盖已创建的赛事快照。
  - **只冻结驱动 Runtime 的最低必要信息**（盘数、盘类型顺序、获胜所需盘数）。仍未冻结：
    选手角色映射（A/B/C/X/Y/Z）、谁打一单/二单、双打组合与提交时机、最多打几盘、兼项、
    替补规则与时机、排阵提交时间、严格盘序、团体小组积分规则。
  - 快照即历史真相：Runtime 只从 `format_snapshot` 读 `rubbers_to_win`，不重读注册表；
    改写 / 替换 / 下线 V1 都不会改变已创建的对抗。
  - 防重复与防换制：已有骨架再建 → 409；`replace=true` 只在"全部盘仍 PENDING 且对抗未进入 Runtime"时成立；
    对抗只要有盘 READY/PLAYING/FINISHED/SKIPPED，换赛制或重建骨架**永久** 409。
  - 仍然**没有**：正式 TEAM 前端入口（`TeamTiePage` 仍是占位、`HomePage` 入口继续禁用）、
    团体小组排名、出线/晋级、淘汰晋级、排程与 ETA、`team_rubbers.match_id` 仍为 NULL。
- 团体小组循环对阵生成（A6.1，`docs/TEAM_DOMAIN.md` 的「团体小组循环对阵生成」）：
  已分好组的 TEAM 赛事可以**自动生成组内单循环的全部对抗**，不再需要手工一场一场建立。
  - 新接口 `POST /api/tournaments/{id}/team-ties/generate-group-ties`，返回最小 DTO
    `{ties_generated, per_group}`（例如 8 队 2 组 → `12 / {A组:6, B组:6}`）。
  - 编排复用个人赛同一份 `domain/round_robin.py`（**没有**为 TEAM 复制第二份算法，
    也没有为了复用去重构个人赛）：输入按 `entries.id` 升序稳定排序；`round` 从 1 开始；
    `match_index` 是**轮内**从 1 开始的稳定场序；4 队 → 6 场 3 轮，5 队 → 10 场 5 轮。
    奇数队伍的轮空**不落库**（不会出现 `队伍 vs NULL` 这种假对抗）。
  - 生成前守卫（全部在 service 层，router 只做参数解析 / 调 service / 错误映射）：
    赛事不存在 → 404；不是 TEAM 项目 → 409；还没有小组 → 409；
    **有 `ACTIVE` 队伍未分组 → 409 且整批拒绝**（不会只给已分组的队伍生成一部分赛程）；
    **已有任何 `stage=GROUP` 对抗（手工建立的也算）→ 409**，不补齐 / 不覆盖 / 不重新生成。
  - 生成是**一个写事务**（复用 `services/transaction.py::write_transaction`，`BEGIN IMMEDIATE`）：
    写锁内重新读取赛事/小组/队伍/已有对抗，再做最终判断与全部写入；两个并发生成请求恰好一个成功，
    另一个拿到可读的 409（不会出现两套赛程，也不会把 SQLite 锁错误漏成 500）。
  - **不推进 `Tournament.stage`**（TEAM 的 REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED
    必须与团体排名、晋级、排程一起设计），也**不批量生成 rubber skeleton**（建盘是另一个业务动作，
    且有自己的事务与安全契约）；生成后仍走既有链路：选 `LOCAL_CLASSIC_5_V1` → 建盘 → Runtime。
  - 退赛口径沿用既有规则（`WITHDRAWN` 队伍不参与生成，不新增另一套退赛语义）；
    退到只剩 1 支在赛队伍的小组生成 0 场。
  - **仍然没有**：出线/晋级写入、团体淘汰赛、团体 Scheduler/ETA、
    安全撤销/重建团体小组赛、`round`/`match_index` 的数据库层唯一约束。
    （注：**团体小组排名已由 A6.2 完成**，见下条。）
- 团体小组排名（A6.2，规则源 `docs/TEAM_GROUP_RULES_V1.md`）：TEAM 赛事的小组现在可以查看
  **只读**的团体排名。
  - 新接口：`GET /api/tournaments/{id}/team-groups/standings`（全部小组，可按 `group_id` 过滤）、
    `GET /api/tournaments/{id}/team-groups/{group_id}/standings`（单个小组）。
    **为什么用 `/team-groups` 前缀**：`team-ties` 命名空间下已有 `{tie_id}` 动态段，
    再塞 `/team-ties/standings` 会与它冲突（只能靠声明顺序规避，很脆弱）；
    而"小组下的资源"在仓库里已有先例（`/groups/{group_id}/qualification`）。
  - 排序（严格按规则文档）：比赛积分（正常完赛胜 2 / 负 1，未完成对抗不计入）
    → 同分时**只保留同分队伍之间的对抗并重算子集积分** → 盘胜负比 → 局胜负比
    → 仍不可分则**并列**。比率用交叉乘法比较，并区分"+∞（全胜）"与"0/0（没数据，不可比较）"。
  - **并列用名次区间表示**（`rank_start` / `rank_end` + `ambiguous`），**绝不按 id 打破同分**；
    `qualify_count` 组级值优先、否则回退赛事默认值（与个人赛 `/rankings` 同一口径）。
  - **不落库**：没有 `team_standings` 表，每次查询从真实 `team_ties` / `team_rubbers` 重算；
    **不新增逐局表**：局 W/L 直接用 `team_rubbers.home_score` / `away_score`；
    `SKIPPED`（提前结束后未打的盘）与未完成对抗都不进入统计。
  - **只给事实、不给结论**：DTO **没有** `qualified`，只有 `eligible_for_qualification` 与
    `qualification_position_state`（RESOLVED / UNDECIDED / ELIGIBLE_ONLY）。
    组内还有任何未完成对抗（含涉及退赛队伍的）→ `provisional=true` 且
    `automatic_qualification_allowed=false`（V1 不做结果可能性分析）。
    退赛队伍保留已完成成绩并占用名次区间，但 `eligible_for_qualification=false`。
  - **仍然没有**：A6.3 qualification（晋级写入 / 出线名单 / 人工裁定）、A6.4 团体淘汰赛、抽签、
    points ratio、团体 Scheduler/ETA、TEAM 阶段推进、正式 TEAM 前端入口。
    （注：**A6.3 与 A6.4 已由后续批次完成**，见下面两条。）
- 团体晋级确认（A6.3，规则源 `docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`）：
  - 新接口：`GET /api/tournaments/{id}/qualification`（只读：每组候选、是否需人工处理、
    是否可确认、已确认名单）、`POST /api/tournaments/{id}/qualification/confirm`（人工确认，
    全量替换）。
  - 规则：每组按 `qualify_count` 取前 N；**`rank_start <= N < rank_end` 即跨晋级线并列** →
    `requires_manual_resolution = true`，系统**不给任何推荐**（绝不按 id / 顺序 / 随机打破）；
    组内未打完（provisional）→ 409 禁止确认；已退赛队伍不可晋级、不在候选内。
  - 校验：重复队伍 / 每组数量不符 / 跨线并列取舍不正确 → 422；队伍不属于本赛事 → 404。
  - **只存"谁晋级"**：`team_qualifications`（`tournament_id` / `team_entry_id` / `group_id` /
    `status` / `confirmed_at`），**不保存** rank / 积分 / 排名快照——排名事实永远由 A6.2 现算。
  - 确认是**全量替换**且在一个 `BEGIN IMMEDIATE` 写事务内完成（并发只一个成功）。
- 团体淘汰签（A6.4）：
  - 新接口：`POST /api/tournaments/{id}/team-knockout/generate`、
    `GET /api/tournaments/{id}/team-knockout`（未生成时 `generated=false`）。
  - 种子 = **小组顺序 + 组内晋级名次**；**相邻组交叉配对**：
    4 组 → `QF1=A1-B2, QF2=B1-A2, QF3=C1-D2, QF4=D1-C2`；2 组 → `A1-B2, B1-A2`。
    无随机、不按 id 排序、不做稳定排序兜底。
  - **复用 `team_ties`**：`stage='KNOCKOUT'`、`group_id` 恒为 NULL；
    **不新建** `team_knockout_ties`、**不创建任何 `matches` 行**。
    淘汰赛 TeamTie 与小组赛同构，可直接用 `LOCAL_CLASSIC_5_V1` 建盘进入 A4.1 Runtime。
  - 守卫：重复生成 409（不补齐 / 不覆盖 / 不重新生成）；未确认晋级 409；
    已确认队伍退赛 409；规模不受支持（奇数组 / 每组晋级数 ≠ 2 / 非 2 的幂）409。
  - **本批次最明显的边界**：生成只建立**首轮**对抗；后续轮次在读取时按签表几何补全为
    "待定槽位"（`rounds[i].match_count` 给应有场次数、`matches` 为空）。
    原因：`team_ties.entry_a_id/entry_b_id` 是 NOT NULL 且没有 `prev` 依赖列，
    预建空对抗只会留下无法消费的空行。**淘汰签的胜者晋级尚未实现**，
    需要先做 `team_ties` 表迁移（允许待定槽位 + 上游依赖，对齐个人赛 `matches` 的
    `prev_match_*` 设计）。
  - **仍然没有**：胜者晋级传播、Scheduler / 自动排台 / ETA、实时运行态 UI、
    高级种子算法（rating / 历史积分 / 跨赛事排名）、自动处理并列晋级、
    轮空与奇数组配置、淘汰签撤销 / 重建、TEAM 阶段推进、正式 TEAM 前端入口。
- 淘汰赛交叉对阵的冻结范围（A1 复审确认）：
  - 正式冻结：2 组 × 每组前 2（A1-B2、B1-A2）；4 组 × 每组前 2（A1-D2、C1-B2、B1-C2、D1-A2）；偶数组 × 每组前 2 的"首尾交叉"原则（第 i 组第 1 名 ⇄ 倒数第 i 组第 2 名），同组两人与 1/2 号种子分处不同半区。
  - 未正式冻结：需要轮空时的具体轮空落位（例如 6 组 = 12 人进入 16 签）、3/5/7 等奇数组、每组出线人数 != 2 或各组出线人数不一致。
  - 上述未冻结部分当前保留一套确定性的兼容实现（deterministic compatibility implementation），只保证流程可跑完，**不得描述为正式或国际赛制**；以后按真实赛事规程确认。所有这些都属本项目自有规则，不宣称等同于官方/国际赛制。
- 淘汰签表可在尚未开始时撤销（`POST /api/tournaments/{id}/knockout/undo`）：删除主签与名次排位并回到 `GROUP_STAGE`，修正小组比分后重新生成；已开赛（有进行中比赛或已录结果）返回 409，不静默删除真实结果。
- 赛事数据可结构化导出（`GET /api/tournaments/{id}/export`，只读）：用于归档、交付组委会以及删除赛事前的人工备份。
- 小组正常完赛场次可补录/修改小比分，用于同分排名；淘汰赛 UI 仍只录大比分。
- “本场弃权”只判当前场负；“退出赛事”作用于整个 Entry，保留既往赛果，把正在进行和后续可确定场次判负，并排除后续晋级资格。双打按整个组合退赛。
- 小组排序已确认前缀：胜场数 → 净胜局 → 赛事积分（胜 2、正常负 1、弃权负 0）。后续同分细则仍须专项确认，不宣称已完整实现 ITTF 官方算法。
- 小组出线数可配置；各组不同人数的组合仍有后端限制，见风险 R03。
- 不做双败。所谓败者组是争夺较低名次的排位赛，不会返回主签争冠军。
- 创建赛事选择季军赛或并列季军；完整排位支持 4 / 8 / 16 人无轮空标准签。非标准人数仍可完成冠军主签，但不会虚构无法由比赛确定的低位名次。
- 名单确认后的过场动画、比赛球台视觉、从下到上的冠军之路继续保留。
- 秩序册先用浏览器打印/保存 PDF，后续接组委会官方模板。

## 当前功能和入口

| 模块 | 现有能力 | 主要代码 |
|---|---|---|
| 赛事首页 | 创建、选择、删除赛事；单/双打、球台、小组、出线数、季军与排位配置 | `frontend/src/pages/HomePage.tsx` |
| 赛前检查 | 面向主裁聚合名单、参赛位、分组、赛程、球台、晋级和规则状态；只读检查，不替主裁自动决策 | `PreflightPage.tsx`；`services/preflight.py` |
| 报名与导入 | 在线报名、增删改选手、积分/单位、种子；CSV/XLSX 预览后确认；预览全部行。导入是正式能力，LIVE 与 DEMO 赛事都可用；只有「生成演示选手」等 Demo 功能限 DEMO | `RegisterPage.tsx`、`PlayersPage.tsx`；`services/import_players.py` |
| Entry 与双打 | 单打 1 人、双打 2 人；近积分候选随机配对；未配齐不能确认名单 | `services/entries.py`、`routers/entries.py` |
| 团体赛（A3 领域基础） | 队伍 = `entry_type='TEAM'` 的 Entry；队伍增删改查与队员唯一归属校验；`team_ties` / `team_rubbers` 对抗与盘骨架；赛制规格校验与快照（生产注册表只含确认过的版本化模板）；**无界面、不进排程** | `services/teams.py`、`services/team_ties.py`、`domain/team_formats.py`、`routers/teams.py`、`routers/team_ties.py` |
| 团体赛 Runtime（A4.1） | 阵容绑定（按盘型校验人数、只允许本队队员）、盘状态机（PENDING→READY→PLAYING→FINISHED，提前结束后未打的盘 SKIPPED）、盘大比分录入（复用赛事局制规则）、对抗总分自动累计、达到获胜盘数自动结束并写胜者；统一返回运行态与 permissions；**串行执行、不接排程、不创建 Match** | `services/team_runtime.py`、`routers/team_ties.py`、`docs/TEAM_RUNTIME_CONTRACT.md` |
| 团体赛生产赛制 V1（A5） | `LOCAL_CLASSIC_5_V1`：5 盘、先赢 3 盘、单/单/双/单/单；真实 TEAM 赛事可直接建盘并进入 Runtime（不依赖测试赛制）；快照版本化不可变；开赛后禁止换赛制/重建骨架；**不声明官方规则、无排名/晋级/排程** | `domain/team_formats.py`、`services/team_ties.py`、`docs/TEAM_DOMAIN.md` |
| 团体小组循环生成（A6.1） | 已分组 TEAM 赛事一键生成组内单循环全部 `TeamTie`（4 队组 6 场 / 两组 12 场 / 3 队 3 场 / 5 队 10 场）；复用个人赛 `domain/round_robin.py`；`round`/`match_index` 确定性；未分组或已有小组对抗一律 409（整批拒绝、不补齐）；一个写事务、并发下一个成功一个 409；**不改 stage、不建盘、不做排名/晋级** | `services/team_ties.py::generate_group_ties`、`domain/round_robin.py`、`routers/team_ties.py`、`docs/TEAM_DOMAIN.md` |
| 团体小组排名（A6.2） | 只读团体排名：比赛积分(胜2/负1) → 同分子集**重算** → 盘胜负比 → 局胜负比 → **并列名次区间**；交叉乘法比较、0/0 视为不可比较；`SKIPPED` 与未完成对抗不计入；不落库（无 `team_standings` 表）、不新增逐局表；`provisional` / `ambiguous` / `automatic_qualification_allowed` / `eligible_for_qualification` 只给事实；**没有 `qualified`、不写晋级、不改 stage** | `domain/team_standings.py`、`services/team_standings.py`、`routers/team_standings.py`、`docs/TEAM_GROUP_RULES_V1.md` |
| 团体晋级确认（A6.3） | 每组按 `qualify_count` 取前 N；**跨晋级线并列 → 必须人工确认**（不按 id/顺序/随机打破）；provisional 禁止确认；已退赛不可晋级；确认全量替换、写事务内完成；只记"谁晋级"（`team_qualifications`），不保存 rank/积分/快照 | `domain/team_qualification.py`、`services/team_qualification.py`、`routers/team_qualification.py`、`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md` |
| 团体淘汰签（A6.4） | 种子 = 小组顺序 + 组内名次；相邻组交叉配对（A1-B2/B1-A2/C1-D2/D1-C2）；**复用 `team_ties`（`stage='KNOCKOUT'`）**、不新建表、不创建 Match；重复生成/未确认/规模不受支持一律 409；**只建首轮**，后续轮次为待定骨架（胜者晋级尚未实现） | `domain/team_knockout.py`、`services/team_knockout.py`、`routers/team_knockout.py`、`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md` |
| 分组 | 种子分散、人数均衡、同单位软回避；解除分组；配置各组出线数 | `services/groups.py`、`routers/groups.py` |
| 录分与排名 | 大比分默认 0；小组小分补录；改分强制操作人/理由并保存前后快照；读取结果重算排名、提示出线歧义 | `ScoreSheet.tsx`、`RankingsPage.tsx`；`services/scores.py`、`domain/ranking.py` |
| 现场控制台 | 真实 API 球台卡、批量/手动排台、下台、比分/弃权；待赛横向换行；已结束场次改分。自动排台优先级＝硬约束 → 组台亲和 → 组间进度公平 → 连续上场惩罚 → 稳定顺序（服务端给出每台建议，前端只展示），更完整的 V1 设计见 `docs/SCHEDULING_V1_DESIGN.md` | `ConsolePage.tsx`、`LiveTableCard.tsx`、`services/scheduling.py` |
| 人工晋级裁定 | 只处理晋级线并列，记录选择、理由、主裁判和时间；相关数据变化后自动失效 | `services/qualification_decisions.py`、`qualification_decisions.py` |
| 淘汰赛与结果 | 主签胜者晋级、轮空、季军或并列季军、4/8/16 人递归完整排位、最终名次；淘汰赛尚未开始时可用「撤销签表」（`POST /api/tournaments/{id}/knockout/undo`）删除主签与排位并回到 `GROUP_STAGE`，修正小组比分后重新生成，已开赛返回 409 | `KnockoutPage.tsx`；`services/knockout.py` |
| 数据导出与删除保护 | `GET /api/tournaments/{id}/export` 导出结构化赛事数据（`schema_version` + 落库数据 + 排名/冠军/名次推导 + 小分 + 人工裁定快照 + 比分写入审计），只读；删除正式赛事须输入完整赛事名，建议删除前先导出备份 | `services/tournament_export.py`、`routers/tournaments.py` |
| 展示与输出 | 大屏、名单过场、冠军路径高亮、秩序册打印 | `BigScreenPage.tsx`、`RosterLaunch.tsx`、`ChampionJourneyPage.tsx`、`OrderBookPage.tsx` |

规模验收数据位于 `docs/demo-data/realistic_players_120.csv` 和 `.xlsx`；24 组×5 人、15 台、每组前 2 的验证命令见 `backend/tests/test_scale_120.py`。

新建赛事默认 `operation_mode=LIVE`；只有显式 `DEMO` 赛事可以调用演示数据接口。正式赛事删除需要完整名称确认。比分写入支持可选 `request_id`，前端默认生成并在网络失败时用同一编号重试一次。

表中前端短文件名均位于 `frontend/src/pages/`，组件位于 `frontend/src/components/`；后端短路径均位于 `backend/app/`。存在页面不代表所有 V0.2 要求都已满足，特别是 Schedule 页面不是完整计划时间引擎。

## 架构与字段契约

请求路径：页面/组件 → `frontend/src/api.ts` → FastAPI router → service/domain → repository → SQLite。

- `backend/app/schemas.py`：请求与响应 Pydantic 定义。
- `backend/app/models.py`：枚举；`backend/app/db.py`：数据库结构及启动时兼容迁移。
- `backend/app/repository.py`：持久化与旧 Player / 新 Entry 的兼容映射。
- `docs/openapi-v0.2.json`：OpenAPI 快照；本轮确认与 `app.openapi()` 相等。
- `frontend/src/api.ts`：手写请求封装；`frontend/src/generated/openapi.d.ts` 为 OpenAPI 生成类型，接口改动时必须同步刷新。

| 字段/实体 | 正确理解 | 接手注意 |
|---|---|---|
| Player | 自然人，含 `rating_points`、`college` | 运动员积分不是赛事排名积分 |
| Entry + entry_members | 一次参赛单位及成员 | 比赛业务应逐步统一使用 Entry ID |
| Entry.status | ACTIVE / WITHDRAWN | 退赛保留 Entry 和既往赛果；操作者、原因、时间记录在 Entry 上 |
| Match.entry_a_id / entry_b_id | 对阵双方 Entry | 不要与 Player ID 混用 |
| player_a_score / player_b_score | 保留旧名称的大比分，即胜局数 | 2:0 表示赢两局，不是单局得分 |
| MatchGame | `game_no`、双方单局得分、胜者 | 缺小分不等于实际得 0 分 |
| started_at / finished_at | 首次上台与首次完赛的事实时间 | 释放重排、改分和补录小分均不覆盖 |
| score_audits | RECORD/REVISE 前后快照、操作者、原因、时间、请求标识 | 历史只追加不覆盖；旧比分可能没有历史审计 |
| winner_entry_id / winner_id | 新旧兼容字段 | 淘汰树 `player_a.id` 与排名 `player_id` 可能实际承载 Entry ID；见 service 映射 |
| result_type | NORMAL、FORFEIT、WALKOVER、NO_SHOW、DISQUALIFIED | 没有完整 CANCELLED 流程 |
| qualify_count | 组级覆盖值；否则用赛事 `qualify_per_group` | 能保存不代表签表支持所有组合 |
| qualification_decisions | 人工补足晋级线名额的审计记录 | 不改写比赛结果和算法 rank；只使用 active 且排名快照匹配的记录 |
| bronze_mode | BRONZE_MATCH / JOINT_BRONZE | 决定 3、4 名是否真的再打一场 |
| placement_mode | OFF / COMPLETE / TIERED | COMPLETE 支持最多 16 人无轮空标准签；TIERED 仍为预留枚举 |
| team_ties / team_rubbers | 团体赛（A3）新增：一场对抗 + 对抗中的盘骨架 | `match_id` 恒为 NULL（A3 不创建 Match）；盘只记录"每边需要几个出场位置"，不是选手 id；生产赛制注册表只含确认过的版本化模板（A5 起为 `LOCAL_CLASSIC_5_V1`）；A6.1 起小组对抗可由 `generate-group-ties` 按组内单循环批量生成（`round` 组内轮次、`match_index` 轮内场序，数据库层**没有**唯一约束）；A6.2 的团体小组排名**只读**这两张表并每次重算，不落 standings 表、也不新增逐局表 |

当前赛事状态：REGISTRATION → GROUP_STAGE → KNOCKOUT → FINISHED。比赛状态：WAITING → PLAYING → FINISHED；下台回 WAITING。尚无独立 Event/Stage 表和通用 MatchSlot 依赖解析器。当前 `EventType` 有 SINGLES / DOUBLES / TEAM 三个取值；TEAM 赛事**不会**进入这条 stage 链路（生成小组赛/淘汰赛对它直接 409，A6.1 的 `generate-group-ties` 只生成对抗、A6.2 的排名接口只读，**都不推进 stage**），团体赛的阶段推进要与晋级、淘汰赛与团体赛排程一起设计。

## 队友如何启动

推荐在新文件夹 clone，不要覆盖已有同名目录：

```powershell
git clone https://github.com/Common-Kingfisher/PingpongSystem.git
cd PingpongSystem
python -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
pnpm -C frontend install --frozen-lockfile
```

`pingpong_plantform` 是当前机器上的目录名；clone 后的 `PingpongSystem` 就是同一仓库根目录，无需再进入同名子目录。

需要 Python 3.10+、Node.js 和 pnpm。核查机使用 Node 24.13.0、pnpm 11.19.0；这只是本次环境记录，不是长期版本推荐。后端依赖目前使用最低版本范围，没有完全锁定。前端 package 与 FastAPI 应用版本仍标为 `0.1.0`；本报告中的 V0.2 指需求对比目标，不代表已发 V0.2 版本。

开两个终端，均从仓库根目录启动：

```powershell
# 终端一：后端
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

```powershell
# 终端二：前端
pnpm -C frontend dev
```

打开 `http://localhost:5173`；健康检查 `http://127.0.0.1:8000/api/health`；API 文档 `http://127.0.0.1:8000/docs`。环境装齐后也可双击 `start_demo.bat`。

端口占用先确认是不是已经启动了本项目；检查进程身份后再关闭自己的旧终端，不要盲目结束所有 Python/Node 进程。现有启动脚本只检查 `node_modules` 目录存在，不保证其中链接完整；遇到模块缺失先重新执行锁文件安装。

数据库默认 `backend/data/demo.db`，不上传 GitHub。运行服务前先确认路径；升级或清理前停止服务并单独备份。测试使用独立临时库，不能对真实比赛库运行重置/造数脚本。仓库附有虚构的 16 人 CSV/XLSX，路径 `docs/demo-data/`。

## 建议的首次演示

创建单打赛事：4 小组、每组前 2、4 台、季军赛、完整排位。导入 16 人示例 → 确认名单 → 分组/生成比赛 → 排台 → 按赛事配置录入大比分（默认三局两胜时为 2:0 / 2:1）→ 查看排名 → 小组全部完成且出线明确后生成淘汰赛 → 打完八强 → 查看 5–8 排位 → 打完半决赛后查看季军赛 → 完成全部主签和排位 → 查看冠军之路、打印秩序册。若要验收 16 人淘汰主签，需产生 16 个晋级 Entry，并完成 1–16 名所有排位场次。

本次演示先使用各组一致的出线数，不在正式比赛中试验已知改分风险。每组可先让固定顺序的高位选手全胜以得到无歧义排名。循环同分另建测试赛事，不要修改正在使用的演示数据来凑名次。双打建议另建 8 或 16 名运动员的赛事，注意 8 名运动员只有 4 个 Entry。

## 本轮验证记录

| 验证 | 结果与边界 |
|---|---|
| 正式目录后端现有测试 | 157 项通过；使用旧副本中现成的 Python 虚拟环境运行正式目录代码，已核实模块实际加载路径 |
| 前端类型检查与生产构建 | `pnpm run build` 通过（包含 `tsc`，Vite 5.4.11，50 modules） |
| 依赖完整性 | 正式目录原有链接损坏；已按锁文件重装，锁文件和业务代码未改 |
| OpenAPI | 快照与当前应用生成结构一致；自动 TS 类型生成仍缺失 |
| 额外隔离诊断 | 复现非法比分校验不足、不等额出线拒绝、半决赛改分不更新季军参与者、淘汰生成后仍可改小组结果 |
| Git 发布前检查 | 21 个历史提交范围内，未发现已跟踪依赖目录/数据库/私钥文件或常见 Token 特征；这不是完整安全审计 |
| 本轮未执行 | 浏览器完整 E2E、120 人/15 台闭环、并发录分、目标机器安装演练、完整规则符合性认证 |
| A3 团体赛领域基础（PR #19 复审修正后） | 后端 432 项测试通过（含 #14 退赛、#17 赛前检查与本批次团体赛用例）；`pnpm exec tsc --noEmit` 与 `pnpm build` 通过；OpenAPI 快照与 `app.openapi()` 一致、`contract:check` 无漂移；旧库（`tournaments.event_type` + `entries.entry_type` 双表 CHECK）迁移后 `PRAGMA foreign_key_check` 为空且无 legacy 表残留；已合并最新 `develop/field-demo-v02`（8ccf627，含 #17）并重新生成契约；本轮未做浏览器端团体赛操作验证（界面仍为占位，`TeamTiePage` 明确标注未开放） |
| A4.1 团体赛 Runtime | 后端 474 项测试通过（含本批次 42 项 runtime 用例：完整闭环、状态机失败场景、权限矩阵、并发双 start/双 score、名单冻结与阵容失效、PR #19 旧库升级、导出只读）；`tsc --noEmit`、`pnpm build`、`export_openapi.py --check`、`contract:check` 全部 exit 0；本轮未做浏览器端操作验证（B 的团体赛界面仍在独立分支推进） |
| A5 生产团体赛赛制 V1 | 后端 503 项测试通过（本批次新增 `backend/tests/test_team_format_v1.py`：生产注册表边界、盘序与中性位置代号、真实建盘 5 盘、Runtime 契约、生产赛制端到端闭环与提前结束、2:2 时第 5 盘、快照抗注册表改写/替换/下线、422/409 拒绝路径、API 层全流程）；`export_openapi.py --check`、`contract:check`、`tsc --noEmit`、`pnpm build` 全部 exit 0；未新增 API/DTO，OpenAPI 快照无结构变化；仍未开放 TEAM 前端入口（B 的界面在独立分支推进） |
| A6.1 团体小组循环生成 | 后端 **612 项测试通过**（本批次新增 `backend/tests/test_team_group_ties.py` 19 项 + `backend/tests/test_round_robin_domain.py` 74 项：4 队/两组 4 队/3 队/5 队生成、逐场比对落库与 `round_robin()` 输出、未分组整批拒绝 0 新增、非 TEAM 409、赛事不存在 404、重复生成 409 不翻倍、手工对抗不补齐不覆盖、退赛不参与、并发双生成"一成功一 409"（多轮，含 read-check-write 竞态路径）、写锁争用可读 409、不改 stage/不建 Match/不建盘、自动生成的对抗继续跑生产赛制骨架 → 阵容 → start → 录分、API 层契约）；`export_openapi.py --check` 与 `pnpm contract:check` exit 0（快照与生成类型已按新接口刷新）、`tsc --noEmit` exit 0、`pnpm build` exit 0（57 modules）；本轮未做浏览器端操作验证（TEAM 界面仍为占位，B 工作线在独立分支推进） |
| A6.2 团体小组排名 | 后端 **649 项测试通过**（本批次新增 `backend/tests/test_team_standings.py` 37 项：域层 Fixture A–E（无同分 / 直接交锋 / 盘比率 / 局比率 / 并列区间）、部分区分与"子集内统计重算"（子集结论与全局结论相反）、比率交叉乘法与 0/0 语义、`_resolve` 输出必须是队伍的一个划分、SKIPPED 与未打完的盘不计入、局分真正读取 `home_score`/`away_score`、跨组隔离、provisional（WAITING / PLAYING）、退赛（成绩保留 + 不可晋级 + 有未完赛则整组禁止自动晋级）、并列区间共享、非 TEAM 409 / 小组不存在 404 / 跨赛事 404、每次查询从数据库事实重算、A6.1 生成 → Runtime 真打完 → standings 端到端、API 层 DTO 契约与错误码）；`export_openapi.py --check` 与 `pnpm contract:check` exit 0（OpenAPI 快照与生成 TS 类型已按新接口刷新，均为追加）、`tsc --noEmit` exit 0、`pnpm build` exit 0；新增 `docs/TEAM_GROUP_RULES_V1.md`（唯一规则源，含"待 Reviewer 确认"小节）；本轮未做浏览器端操作验证（TEAM 界面仍为占位，B 工作线在独立分支推进） |
| Word | 使用系统设计模板，完成结构校验；本机缺 LibreOffice，未完成逐页渲染视觉验收 |

测试命令（配置好自己的后端环境后）：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
pnpm -C frontend run build
```

测试通过不表示所有规则正确：当前测试未覆盖本轮发现的若干反例。具体修复顺序及待确认事项见开发路线。

## 交接协作方式

你负责页面、组件、交互、打印样式与 UI 验收；队友负责赛制、排名、数据迁移、接口和服务层；集成/复核职责须明确指定，可轮流承担，但修改者不能独自宣布核心规则通过。

从本次基线开始使用功能分支、小批 PR。每次字段变更同时更新 Pydantic、OpenAPI、前端消费类型、测试与文档。不要复制整个 `node_modules`、`.venv`、`.pnpm-store` 来交接；GitHub 上传代码不等于网站已部署上线。
