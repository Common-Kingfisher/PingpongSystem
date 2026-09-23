# D4B 赛制处理器与抽签规则执行记录

## 已冻结的实现边界

- `ROUND_ROBIN`、`SINGLE_ELIMINATION` 与既有 `GROUP_KNOCKOUT` 通过同一 Handler 契约解析。
- 循环赛只创建全体单循环 Match，不生成淘汰赛；单淘汰直接从 ACTIVE Entry 建签，不读取小组排名。
- 单淘汰扩展到下一个 2 的幂签位；BYE 使用既有 `WALKOVER + 0:0 + FINISHED` 兼容存储，并由既有胜者传播链推进。
- 抽签硬约束是签表合法性、种子槽位、BYE；以成员 `college` 聚合的单位集合仅为同等候选间的软规避。
- `rule_config` 当前只接受单淘汰的整数 `draw_seed`；未知键和错误类型报 `FormatHandlerError(422)`。旧顶层规则字段不复制进入该对象。
- `validate_config()` 只校验赛事/项目/配置语义；至少两名 ACTIVE Entry 是生成比赛时的 readiness 门禁，因此空名单赛事可先保存赛制配置。
- 循环赛排名保留退赛 Entry 的历史成绩。完成后缺少必要小分为 `RANKING_DATA_INSUFFICIENT`；小分齐全但仍无法区分为 `RANKING_UNRESOLVED`，不按 id 或随机数强拆。
- 单位规避对最多八个可调签位枚举全局最小首轮碰撞；更大签表使用严格降碰撞的交换启发式。种子和 BYE 槽位始终不可移动。

## A 轨联调边界

当前 `master` 尚未包含 `rule_config` 字段。Handler 以 `tournament.get("rule_config")` 兼容字段缺失；A 轨落库后可直接调用 `validate_rule_config()`，并将 `draw_seed` 传入单淘汰生成，无需修改抽签核心。D4B 不修改数据库、Migration、Schema、Router 或 OpenAPI，也不建立正式 Affiliation 模型。

循环赛完成态仍由 Handler 查询，且始终无副作用。`sync_round_robin_stage()` 仅在比分事实写入的同一事务内运行：兼容读取 `tournament.get("format_code")`，只处理已持久化为 `ROUND_ROBIN` 的赛事。`COMPLETED` 将阶段同步为 `FINISHED`；若改分后变成 `RANKING_DATA_INSUFFICIENT` 或 `RANKING_UNRESOLVED`，已完成赛事会回退到 `GROUP_STAGE`。字段尚未存在的 B standalone 环境自动 no-op。

## 2026-09-22 第二轮 A/B 联调记录

- B 侧同步入口只修改 `formats.py`、`scores.py` 与 `entries.py`：覆盖 `record_score()`、`revise_score()` 的逐局小分补录与常规改分路径，以及 `withdraw_from_tournament()` 的自动判负路径；入口本身不提交事务。
- 不复制循环赛排名或完成态算法；同步只消费 `RoundRobinHandler.get_completion_state()`。`GROUP_KNOCKOUT`、`SINGLE_ELIMINATION`、TEAM、旧赛事和 `format_code` 为空的赛事均为 no-op。
- B standalone 回归使用 `repo.get_tournament()` 的测试替身补充 `format_code`，因此不修改 A 轨 Migration、Repository、Schema、Router 或 OpenAPI。
- 临时组合环境：A `aa5cfb558d7c76ed35a41f9aa0d2e0b5a556afdd` + 上轮 B `2494185277c19fe34b314d48b549f1c39e1d8c9b`，仅本地 `local/D4AB-integration`；真实持久化 `format_code=ROUND_ROBIN` 的三人循环赛最后一场录分后，Handler 为 `COMPLETED` 且 `Tournament.stage=FINISHED`。
- 组合定向：`117 passed, 0 failed`；组合后端全量：`934 passed, 20 skipped, 0 failed`（A 配置持久化 + B Handler/录分/改分/退赛）。
- B 后端全量：`909 passed, 20 skipped, 4 warnings`；`python export_openapi.py --check` 与 `git diff --check` 均通过。

## 2026-09-22 返工验证记录

- 后端全量：`900 passed, 20 skipped, 4 warnings`（155.14 秒）。4 条均为既有 Starlette/HTTPX 弃用警告。
- `python export_openapi.py --check`：通过。
- `pnpm install --frozen-lockfile`：通过（修复一个损坏的本地 Vite 生成依赖缓存后执行）。
- `pnpm build`：通过。
- `pnpm contract:check`：未通过。命令生成的 `src/generated/openapi.d.ts` 与当前 `master` 已提交快照存在认证/赛事管理员 API 差异；该生成文件已恢复，未纳入 D4B。该快照漂移需由 OpenAPI 契约 Owner 单独同步，不能作为本 PR 的前端改动混入。
- `git diff --check`：通过。
