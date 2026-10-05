# PR #68 Review 返工记录：生成事务边界与两个入口的契约收口

PR：[#68 feat(B/C): connect format-aware match generation](https://github.com/Common-Kingfisher/PingpongSystem/pull/68)
返工前 head：`9523ebed9c3bcd2b7ed8493867be9e7f517ec443`
合并的 master：`56e10e8ba66a975f07475208e91434160fa2d7bd`（已含 PR #69 现场修复）
分支：`feat/v03-format-generation-integration`（未 rebase、未 force push、未建新 PR）

本文件只记录本轮返工的事实与边界；产品链路的原始设计见
[V03_FORMAT_GENERATION_INTEGRATION.md](V03_FORMAT_GENERATION_INTEGRATION.md)。

## 1. Finding #1（High）生成缺少事务级并发保护

### 1.1 根因

原实现的生成流程是跨请求的 `read → check → write`，**没有从第一条 invariant 开始持有
server-side write lock**：

```text
router: get_tournament → 读 format_code → resolve_format_handler
service: 读赛事/分组 → 判断阶段与"是否已生成" → 写 Match → 更新 stage → conn.commit()
```

FastAPI 每个请求一条独立 SQLite 连接，因此两个管理员 / 两个标签页 / 两个 HTTP 请求
可以同时看到 `count_matches == 0`，然后都开始生成。前端 `busy` 标志完全无法覆盖
多标签页、多终端与两个独立请求。

同时存在 stale handler 风险：router 先读 `format_code`，另一个请求改赛制，
generation 仍按旧 Handler 执行。

### 1.2 更深的坑：内层 `conn.commit()`

只把外层包一层是不够的，因为既有生成实现**自己提交**：

```text
matches.generate_group_matches()            → conn.commit()   （旧行 87）
matches.generate_round_robin_matches()      → conn.commit()   （旧行 119）
knockout.generate_single_elimination()      → conn.commit()   （旧行 231）
```

外层 `BEGIN IMMEDIATE` + 内层 `conn.commit()` 会让事务被提前提交，
**写锁在 invariant → generation → stage update 走完之前就释放**，修复即失效。

### 1.3 修复：transaction owner + locked implementation

沿用仓库既有的 `_locked` 模式（`scheduling.py` / `scores.py` 已在用）：

| 层 | 职责 |
| --- | --- |
| `matches._generate_group_matches_locked()` | 只做 校验 → 生成 → 推进阶段；**不 begin / 不 commit / 不 rollback** |
| `matches._generate_round_robin_matches_locked()` | 同上 |
| `knockout._generate_single_elimination_locked()` | 只做 校验 → 建签 → 推进阶段；同上 |
| `matches.generate_*()` / `knockout.generate_single_elimination()` | public wrapper：`write_transaction` 包住 locked 实现，保留既有独立调用行为 |
| `formats._run_generation()` | **统一编排 + 唯一事务边界** |

统一编排（`formats.py`）的实际时序：

```text
BEGIN IMMEDIATE                       ← write_transaction（仓库唯一实现）
  → repo.get_tournament()             ← 锁内重新读取，不是调用方快照
  → tournament["format_code"]         ← 锁内读取已提交赛制
  → resolve_format_handler(...)
  → handler.generate_matches(...)     ← 全部 invariant + 检查已有 Match + 生成
  → （Handler 内部）update_tournament_stage
COMMIT
```

- **没有**新增第四套 `BEGIN IMMEDIATE` helper，没有 `threading.Lock`，没有换数据库，
  没有 Redis，没有"SELECT 后再 commit"假装原子；
- 已经持有写事务时，public wrapper 走 `write_transaction` 的 **SAVEPOINT** 分支
  （`conn.in_transaction` 为真），仍然不会提前提交；
- `TransactionBusyError` 由编排层映射为业务 409；既有生成守卫
  （阶段不允许 / 未分组 / 已生成）也在编排层归一成带 `code` 的业务错误，
  使服务层调用方看到的契约一致（HTTP 状态码与文案完全不变）。

### 1.4 两个入口共用同一边界（Finding #1.5）

legacy `/generate-group-matches` 不再有自己的"先读赛事再交给 service"路径，
而是走 `formats.generate_group_matches_compat()` —— 与 canonical 共用
`_run_generation()`，因此 **canonical 与 legacy 并发时只有一个成功**。
legacy 的跨赛制拒绝也移进了锁内（否则并发改赛制时可能绕过）。

### 1.5 并发回归（`backend/tests/test_format_generation_concurrency.py`，12 用例）

全部使用**独立 sqlite3 连接 + `threading.Barrier` 同步起跑**（不是同一连接顺序调用两次）：

| # | 场景 | 结果 |
| --- | --- | --- |
| A | ROUND_ROBIN canonical × 2 | 恰好 1 成功 / 1 个 409；15 场、15 个唯一对阵、stage=GROUP_STAGE |
| A' | GROUP_KNOCKOUT canonical × 2 | 恰好 1 成功 / 1 个 409；12 场、12 个唯一对阵 |
| B | SINGLE_ELIMINATION × 2（8 人） | 7 场、round 分布 4/2/1、签位无重复 |
| B' | SINGLE_ELIMINATION × 2（6 人，非 2 幂） | 轮空恰好 2 场，无重复登记 |
| C | canonical vs legacy（GROUP_KNOCKOUT） | 恰好 1 成功 / 1 个 409；只有一套 12 场小组赛 |
| D1 | 先生成 → 后改赛制（确定性顺序） | 改赛制 409「已产生比赛」，`format_code` 不变 |
| D2 | 先改赛制 → 后生成（确定性顺序） | 按**新** Handler 生成：7 场 KNOCKOUT、0 场 GROUP |
| D3 | 生成 vs 改赛制（真并发） | 只允许两种 serialized 结果；绝不出现"赛制已改、却按旧赛制生成" |
| E1 | 循环赛中途注入异常 | Match = 0、stage 保持 REGISTRATION |
| E2 | 建签中途注入异常 | 无半套 bracket、stage 未推进；回滚后可重新正常生成 |
| F1 | 结构性断言 | 三个 locked 实现源码内不得出现 `conn.commit()` / `conn.rollback()` / `BEGIN IMMEDIATE` |
| F2 | 写锁覆盖范围 | 生成过程中从**独立连接**尝试 `BEGIN IMMEDIATE` 必然失败（锁确实被持有） |

## 2. Finding #2（Medium）同步最终 master 并在最终 HEAD 上重新验证

- `git merge origin/master`（**非** rebase、非 force push、无 `reset --hard`）；
- 合并结果：无冲突（PR #68 与 master 改动文件不重叠），merge commit
  `1926f67 Merge remote-tracking branch 'origin/master' into feat/v03-format-generation-integration`；
- 合并后 `behind master = 0`；
- master 带来的 PR #69 现场能力已逐项复核仍在（见 §5）；
- 旧 PR body 里的 `1082 backend / 274 frontend / 26 browser` 全部作废，
  §6 的数据全部在 FINAL HEAD 上重新采集。

### 2.1 返工期间发现的既存 flaky 测试（已修）

`backend/tests/test_format_generation_integration.py::test_single_elimination_six_entries_produce_bye_walkovers`
断言"第二轮两场都恰好只填一侧"，但 `draw_seed = None` 时
`domain.draw.build_single_elimination` 使用 `random.Random(None)`（系统熵）抽签，
BYE 落在哪个半区是随机的 —— 只有两个 BYE 分处不同半区时断言才成立。

在**返工前的 HEAD（1926f67，未含本轮任何修改）**上单独重复执行该用例：

```text
20 次：16 passed / 4 failed
```

因此这是 PR #68 自带的不稳定断言，不是本轮引入的回归；但它会让"最终 gate"失去可信度，
所以本轮一并修掉：固定 `draw_seed=20261005`，并把断言改成与抽签落位无关的真实不变量
（两个轮空胜者必须都进入第二轮签位）。修复后重复执行 15 次：**0 failed**。

## 3. Finding #3（Medium）canonical / legacy 契约收口

冻结语义（详见 [V03_FORMAT_GENERATION_INTEGRATION.md](V03_FORMAT_GENERATION_INTEGRATION.md) §4.0）：

**Canonical** `POST /api/tournaments/{tid}/generate-matches`
= "根据赛事当前已持久化的 `format_code`，生成该赛制首阶段比赛的正式 format-aware API。"
支持三赛制；`format_code = null` → **422**（不默认成 `GROUP_KNOCKOUT`）；
未知 code → 422；`TEAM` → 拒绝，不生成普通 Match。

**Legacy compatibility** `POST /api/tournaments/{tid}/generate-group-matches`
= "兼容旧版 `GROUP_KNOCKOUT` / 历史未登记 `format_code` 的小组赛链路。"
**不**称为新的正式赛制入口；OpenAPI 标记 `deprecated: true`；**不删除**端点
（既有前端主链、D6D harness 与历史测试仍依赖）。
`GROUP_KNOCKOUT` → 200；`null` → 保留历史语义；`ROUND_ROBIN` / `SINGLE_ELIMINATION` → 409；`TEAM` → 拒绝。

### 3.1 OpenAPI

`docs/openapi-v0.2.json` 现在可以读出：

```text
canonical  /generate-matches        200 / 404 / 409 / 422
           422 同时保留 FastAPI 校验错误 schema，并在描述中说明它有两种来源
           （请求体校验 / 业务：未设置赛制或赛制不受支持）
legacy     /generate-group-matches  200 / 404 / 409 / 422（FastAPI 默认）
           deprecated: true
```

- 通过 FastAPI `responses=` + 端点 docstring 表达，没有新增 DTO、没有新增错误体系；
- canonical 的 422 **显式带上** `HTTPValidationError` schema，避免"为了写业务说明而丢掉
  机器可读的校验契约"；
- 重新生成并校验：`python backend/export_openapi.py` → `--check` 输出
  `OpenAPI snapshot is up to date`；`pnpm contract:generate` 后 `pnpm contract:check` 通过；
  `frontend/src/generated/openapi.d.ts` **由生成器产出**，没有手改。

## 4. Finding #4 / #5（Low）

### 4.1 fixture 隔离（#4）

`backend/v03_format_gen_fixture.py` + `backend/v03_format_gen_browser_check.mjs`：

| 旧问题 | 现在 |
| --- | --- |
| 口令硬编码在 fixture，并被 checker 当默认值 | 只能来自 `PINGPONG_E2E_ADMIN_PASSWORD`；缺失或 < 12 位**fail closed**（退出码 2），无任何默认口令 |
| 每轮创建同名赛事 | 每轮唯一 `RUN_ID`（UTC 时间戳 + 短随机后缀）；账号名与三个赛事名都带它 |
| checker 扫描赛事列表找"第一个同名" | 删除 `findTournamentId`；tid / 账号名一律来自 fixture 输出的 JSON |
| 无法把 fixture 结果交接给 checker | fixture 写出 `FIXTURE_JSON`（默认系统临时目录，不落进仓库），并校验 `base_url` 一致 |

没有引入测试框架重构，也没有改动共享的 `day3_auth_client.py`
（它被十余个既有 harness 使用，其 bootstrap 口令不属于本次 finding 范围）。

### 4.2 legacy 跨赛制可观测性（#5）

先核对仓库既有约定：结构化 `{detail: {code, message}}` 目前只出现在
`auth.py` / `system.py` / `tournament_admins.py`（A 轨认证与账号管理）；
`matches` / `formats` 业务域一直是 `detail: string`。

因此**没有**为一个 Low finding 单独引入第二种全仓 error model：

- 保持现有 `detail: string` response contract 不变（HTTP 状态码与文案都不变）；
- 把语义写进 OpenAPI `responses` 描述与本文档，使调用方能区分
  canonical 的业务 422 与 legacy 的跨赛制 409；
- 若将来要为业务域统一引入结构化 code，应当是独立一轮的全仓收口，而不是在这里开一个例外。

## 5. PR #69 现场修复回归

合并 master 后逐项复核（真实浏览器，80/80 断言通过，`docs/evidence/pr68-review-rework/pr69-field-regression-results.json`）：

| 能力 | 结果 |
| --- | --- |
| A. 待进行比赛 → 指定球台（Match → FREE 球台） | PASS（含"已占用球台从候选消失"） |
| B. 自动安排下一批比赛 | PASS |
| C. ScoreSheet 360×640 / 390×844 / 768×1024 / 1280×720 / 360×420 全控件可达、0 横向溢出 | PASS（另有 zoom 2） |
| D. revise「修改理由至少 2 个字」提示与字段级错误 | PASS |
| E. KnockoutBracket 移动端滚动 / resize / 横竖屏连线对齐 | PASS（含满签表 + 冠军线） |
| F. 同 Match 双裁判：一人成功、一人 409、失败端权威重载、只发 1 次 POST | PASS |
| G. 不同 Match 并发两者都成功 | PASS |

## 6. 最终验证（FINAL HEAD 上重新采集）

全部在 `merge origin/master` 之后的最终 HEAD 上重新执行，未沿用任何旧数据。

| Gate | 命令 | 结果 |
| --- | --- | --- |
| Backend | `pytest` | **1096 collected / exit 0**（返工前该分支 9523ebe 为 1082） |
| Frontend | `pnpm test` | **22 files / 319 passed** |
| TypeScript | `pnpm exec tsc --noEmit` | exit 0 |
| Build | `pnpm build` | exit 0 |
| Contract（前端） | `pnpm contract:check` | exit 0（生成结果与提交一致） |
| Contract（后端） | `python backend/export_openapi.py --check` | `OpenAPI snapshot is up to date` |
| Git | `git diff --check` | 无输出 |

### 6.1 真实浏览器验收

**三赛制生成链路**（`v03_format_gen_fixture.py` + `v03_format_gen_browser_check.mjs`，
Chrome 154 CDP，27 项断言全部 PASS，`RESULT=PASS`）：

```text
A. ROUND_ROBIN        /settings「全体循环赛」→ /draw「生成循环赛」
                      → 15 场 GROUP/WAITING、stage=GROUP_STAGE → /console 待进行比赛（15）
                      且不出现"生成淘汰赛 / 等待接口 / 小组出线"
B. SINGLE_ELIMINATION /settings「单淘汰」→ /draw 设种子 →「生成单淘汰签」
                      → 主签 7 场、0 场小组赛、stage=KNOCKOUT、2 场 WALKOVER
                      → /knockout 含 8强赛/决赛 → /console 待进行比赛（5）
C. GROUP_KNOCKOUT     /settings「小组赛 + 淘汰赛」→ /draw「生成分组」→「生成小组比赛」
                      → 12 场、stage=GROUP_STAGE → /console 待进行比赛（12）
D1. 浏览器未捕获异常 / 未处理 Promise 拒绝 = 0
D2. 除 api.ts 既定 [api] 失败请求诊断外 console.error = 0
```

原始输出：`docs/evidence/pr68-review-rework/format-generation-browser-check.txt`。

**PR #69 现场回归**（本轮合并 master 后重跑，80 项断言全部 PASS）：

见 §5 与 `docs/evidence/pr68-review-rework/pr69-field-regression-results.json`。

## 7. 明确不做

- 不修 `knockout_service.generate_knockout`（`POST /generate-knockout` 与
  `GroupKnockoutHandler.advance_participants` 走的是"小组赛完成 → 晋级 → 淘汰"阶段链路，
  **不属于**本轮 Finding #1 所指的"首阶段比赛生成"）。它与本轮修好的三个生成实现
  属于同一类 read-check-write，若需要收口应作为独立一轮，避免本轮扩大范围；
- 不改排名 / 种子 / BYE / 赛制算法；
- 不改数据库 schema、认证体系与 deployment 架构；
- 不为一个 Low finding 引入全仓第二种 error model（见 §4.2）。
