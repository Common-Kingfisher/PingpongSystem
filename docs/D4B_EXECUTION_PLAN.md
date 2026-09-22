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

纯循环的 Handler 完成态已可查询；由于当前 `master` 尚未持久化 `format_code`，最后一场比分写入时不能安全地判定是否应把赛事阶段回写为 `FINISHED`。该同步必须由 A #47 落库后的 A/B 集成在比分服务的单一写入路径接线，不能由查询方法隐式写库。

## 2026-09-22 返工验证记录

- 后端全量：`900 passed, 20 skipped, 4 warnings`（155.14 秒）。4 条均为既有 Starlette/HTTPX 弃用警告。
- `python export_openapi.py --check`：通过。
- `pnpm install --frozen-lockfile`：通过（修复一个损坏的本地 Vite 生成依赖缓存后执行）。
- `pnpm build`：通过。
- `pnpm contract:check`：未通过。命令生成的 `src/generated/openapi.d.ts` 与当前 `master` 已提交快照存在认证/赛事管理员 API 差异；该生成文件已恢复，未纳入 D4B。该快照漂移需由 OpenAPI 契约 Owner 单独同步，不能作为本 PR 的前端改动混入。
- `git diff --check`：通过。
