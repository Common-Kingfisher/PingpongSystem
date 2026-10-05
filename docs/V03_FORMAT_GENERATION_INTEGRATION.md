# V0.3 三赛制生成链路：把 Format Handler 接到正式产品入口

状态：已完成，PR #68 review 返工已完成（本文件只记录事实与边界，不引入新赛制或新算法）。
Review 返工记录见 [V03_FORMAT_GENERATION_REVIEW_REWORK.md](V03_FORMAT_GENERATION_REVIEW_REWORK.md)。

## 1. 问题

`ROUND_ROBIN` / `SINGLE_ELIMINATION` / `GROUP_KNOCKOUT` 三个 `FormatHandler.generate_matches()`
在 master 上**早已存在且有自动化回归**（见 [D7B 规则冻结说明](D7B_RULE_FREEZE.md)），
但 HTTP / UI 产品链只真正接通了 `GROUP_KNOCKOUT`：

```text
规则能力存在 + Handler 契约存在 + 前端赛制设置存在
- 正式 HTTP 生成入口
= 三赛制没有真正闭环
```

`DrawPage` 因此只能对另外两个赛制显示"等待单循环生成接口""首轮淘汰签仍等待当前赛制专用的生成接口"。

本轮**只**补这一段接线，不重新实现任何比赛算法。

## 2. 新增统一入口

```http
POST /api/tournaments/{tournament_id}/generate-matches
```

语义：读取赛事当前保存的 `format_code` → `resolve_format_handler(format_code)`
→ `handler.generate_matches(conn, tournament_id)` → 返回既有
`schemas.GenerateMatchesResult`（`matches_generated` / `per_group` / `tournament`）。

- 路由放在既有 `backend/app/routers/matches.py`，没有为一个 endpoint 新建 router；
- 没有新增 DTO：`per_group` 对 `ROUND_ROBIN` / `SINGLE_ELIMINATION` 天然是 `{}`；
- router 只做 dispatch 与错误映射，**不含任何赛制分支**：

```text
if ROUND_ROBIN: 自己生成循环赛        ← 禁止
if SINGLE_ELIMINATION: 自己写 bracket ← 禁止
if GROUP_KNOCKOUT: 再写一遍小组赛生成  ← 禁止
```

### 2.1 唯一事务边界（PR #68 review Finding #1）

生成是"读 → 判断 → 写"。FastAPI 每个请求一条独立连接，因此必须整段持有写锁，
否则两个管理员 / 两个标签页 / 两个 HTTP 请求可以同时通过校验并双写。
两个入口最终都进入 `backend/app/services/formats.py::_run_generation`：

```text
BEGIN IMMEDIATE                              ← write_transaction（既有唯一实现）
  → 重新读取 tournament                       ← 锁内，不是调用方传入的快照
  → 读取已提交的 format_code
  → resolve_format_handler(format_code)
  → Handler 的全部 invariant 检查
  → 检查已有 Match
  → 生成完整赛程 / bracket
  → 更新 tournament stage
COMMIT
```

关键点：

1. **`format_code` 必须在取得写锁之后重新读取**。router 不再先读赛制再交给 service，
   否则仍存在"读到旧赛制 → 等锁 → 用旧 Handler 生成"的竞态；
2. 生成实现拆成 `transaction owner + locked implementation`
   （`matches._generate_*_locked` / `knockout._generate_single_elimination_locked`）：
   locked 实现**不 begin / 不 commit / 不 rollback**，因此外层写锁不会在
   invariant → generation → stage update 走完之前被释放；
3. 统一入口已持有写事务时，public wrapper 走 `write_transaction` 的 **SAVEPOINT** 分支，
   仍然不会提前提交；
4. 中途异常整体回滚：Match = 0、stage 未推进、没有半套签表。

## 3. 前端接线

| 赛制 | DrawPage 行为 |
| --- | --- |
| `ROUND_ROBIN` | 「单循环编排」+「生成循环赛」→ `api.generateMatches(tid)` → 「已生成 X 场循环赛。」 |
| `SINGLE_ELIMINATION` | 保留单打种子编辑 →「生成单淘汰签」→ `api.generateMatches(tid)` → 「已生成 X 场淘汰赛。」 |
| `GROUP_KNOCKOUT` | **不改主链**：确认名单 → 生成分组 → 生成小组比赛（继续走 legacy 端点） |

`frontend/src/api.ts` 只新增 `generateMatches(tournamentId)`，返回类型继续来自
`frontend/src/generated/openapi.d.ts`，没有手写第二套 transport contract。

前端只做明显的 UX guard（`busy` / `stage` / `roster_confirmed`）：
名单未确认或已离开 `REGISTRATION` 时按钮禁用并给出说明。
参赛位数量、重复生成与合法性**一律由后端判定**，前端不推导。

## 4. 兼容性与边界

### 4.0 两个入口的冻结契约（PR #68 review Finding #3）

**Canonical endpoint**

```http
POST /api/tournaments/{tournament_id}/generate-matches
```

定义：**"根据赛事当前已持久化的 `format_code`，生成该赛制首阶段比赛的正式
format-aware API。"**

| 赛事状态 | 行为 |
| --- | --- |
| `GROUP_KNOCKOUT` | 按小组淘汰 Handler 生成小组赛 |
| `ROUND_ROBIN` | 按循环赛 Handler 生成单循环 |
| `SINGLE_ELIMINATION` | 按单淘汰 Handler 直接建主签 |
| `format_code = null` | **422**，0 Match，阶段不变；**不**默认成 `GROUP_KNOCKOUT` |
| 未知 / 非法 code | **422**（`UnsupportedFormatError`） |
| `TEAM` | 拒绝，不生成任何普通 Match |

**Legacy compatibility endpoint**

```http
POST /api/tournaments/{tournament_id}/generate-group-matches
```

定义：**"兼容旧版 `GROUP_KNOCKOUT` / 历史未登记 `format_code` 的小组赛链路。"**
**不得**称为新的正式赛制入口；OpenAPI 中已标记 `deprecated: true`，但**不删除**
（既有前端主链、D6D harness 与历史测试仍依赖它）。

| 赛事状态 | 行为 |
| --- | --- |
| `GROUP_KNOCKOUT` | compatibility supported（200） |
| `format_code = null` | 保留历史兼容语义（200） |
| `ROUND_ROBIN` | **409**，不得借端点名生成小组赛 |
| `SINGLE_ELIMINATION` | **409**，同上 |
| `TEAM` | 拒绝（409，由既有 service 给出） |

两个入口都不是"平行实现"：它们共用 §2.1 的同一个事务边界，因此
**canonical 与 legacy 并发时只会有一个成功**，已由
`backend/tests/test_format_generation_concurrency.py` 锁定。

### 4.0.1 错误契约的形态

两个入口的错误体继续使用仓库既有的 `detail: string` 形态。
`{detail: {code, message}}` 目前只属于 A 轨 auth / system / tournament_admins，
`matches` / `formats` 业务域从来是字符串；为一个 Low finding 单独引入第二种全仓
error model 会扩大范围，因此改为把语义写进 OpenAPI 描述（见下一节）。

OpenAPI（`docs/openapi-v0.2.json`）现在可以读出：

```text
canonical  POST /generate-matches        200 / 404 / 409 / 422
           （422 同时保留 FastAPI 校验错误 schema，并在描述中说明业务 422 的两种来源）
legacy     POST /generate-group-matches  200 / 404 / 409 / 422（422 为 FastAPI 默认）
           deprecated: true
```

### 4.1 legacy `/generate-group-matches` 保留

既有端点、既有前端主链、既有测试与 D6D harness 全部继续可用。
本轮为它补了一个**最小**赛制守卫（上表 4.0），并把它与统一入口收敛到同一事务边界。

### 4.2 `format_code = null` 的两个入口语义**不同**

| 入口 | `format_code = null` |
| --- | --- |
| `POST /generate-matches`（新） | **422 显式拒绝**，0 Match，阶段不变。未设置赛制不得生成任何比赛，也不默认成 `GROUP_KNOCKOUT`。 |
| `POST /generate-group-matches`（legacy） | 维持历史行为可用。D4A 冻结约束的是"不推断赛制"，而不是改写这个入口过去一直服务的未登记赛制赛事；大量既有测试与 fixture 依赖它。 |

新入口的守卫与新前端不会让 `null` 赛事走到生成，因此不存在"默认成小组淘汰"的新路径。

### 4.3 TEAM 硬边界

`TEAM` 赛事不能写入个人赛 `format_code`（`PUT /format` 返回 409，
`GroupKnockoutHandler.validate_config` 明确拒绝），因此：

```text
TEAM → 不生成普通 Match → 不进入个人赛 Handler
```

`TeamTie` / `TeamRubber` 没有被转换成普通 Match，也没有新增第二套团体判断算法。

### 4.4 `SINGLE_ELIMINATION` 不是 `GROUP_KNOCKOUT` 的第二阶段

```text
REGISTRATION --generate-matches--> KNOCKOUT
```

不经过 `auto-group` / `generate-group-matches` / 小组排名 / `generate-knockout`。
`/generate-knockout` 的语义不变，仍只属于"小组赛完成 → 晋级 → 淘汰阶段"。
非 2 幂人数（如 6 人）的 BYE / `WALKOVER` / 胜者传播继续由既有
`knockout_service._persist_main_bracket` 负责。

## 5. 验证

最终数据在 PR #68 review 返工后的 FINAL HEAD 上重新采集，见
[V03_FORMAT_GENERATION_REVIEW_REWORK.md](V03_FORMAT_GENERATION_REVIEW_REWORK.md) §6。

后端新增 `backend/tests/test_format_generation_integration.py` 覆盖
`ROUND_ROBIN` 正向 / 重复生成 / `SINGLE_ELIMINATION` 正向 / 非 2 幂 BYE /
`GROUP_KNOCKOUT` 走统一入口 / `format_code = null` / `TEAM` / legacy 跨赛制守卫 / 404 / OpenAPI 契约。
前端新增 `frontend/src/__tests__/DrawFormatGeneration.test.tsx` 锁定
"只调用 `api.generateMatches`，不调用 `generateGroupMatches` / `generateKnockout`"与 UX guard。
返工轮新增 `backend/tests/test_format_generation_concurrency.py` 锁定并发与事务边界。

真实浏览器验收（`backend/v03_format_gen_fixture.py` + `backend/v03_format_gen_browser_check.mjs`，
Chrome CDP）：

```text
A. ROUND_ROBIN         /settings → /draw「生成循环赛」→ /console 待进行比赛（15）
B. SINGLE_ELIMINATION  /settings → /draw 设种子 →「生成单淘汰签」→ /knockout 8强赛/决赛
                       → /console 待进行比赛（5，2 场 BYE 已自动晋级）
C. GROUP_KNOCKOUT      /settings → /draw「生成分组」→「生成小组比赛」→ /console 待进行比赛（12）
```

并检查浏览器未捕获异常 = 0、除 `api.ts` 既定 `[api]` 失败请求诊断外 console.error = 0。

## 6. 明确不做

新增赛制（Swiss / 双败 / 积分赛）、团体赛重构、排名 / seed / BYE / affiliation 算法改动、
数据库表与 migration、新增 Tournament stage、auth 体系、`DrawPage` 重构、router 架构升级、
React Query / Redux / Zustand / WebSocket。

## 7. 相关记录

本文落地了 [V03_C_D4_ADMIN_IA.md](V03_C_D4_ADMIN_IA.md) 中"跨轨待办 → B 轨"的前两条：
按当前 `format_code` 的统一生成入口，以及 `ROUND_ROBIN` 正式编排入口。
