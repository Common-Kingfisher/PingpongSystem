# D4B 赛制处理器与抽签规则执行记录

## 已冻结的实现边界

- `ROUND_ROBIN`、`SINGLE_ELIMINATION` 与既有 `GROUP_KNOCKOUT` 通过同一 Handler 契约解析。
- 循环赛只创建全体单循环 Match，不生成淘汰赛；单淘汰直接从 ACTIVE Entry 建签，不读取小组排名。
- 单淘汰扩展到下一个 2 的幂签位；BYE 使用既有 `WALKOVER + 0:0 + FINISHED` 兼容存储，并由既有胜者传播链推进。
- 抽签硬约束是签表合法性、种子槽位、BYE；以成员 `college` 聚合的单位集合仅为同等候选间的软规避。
- `rule_config` 当前只接受单淘汰的整数 `draw_seed`；未知键和错误类型报 `FormatHandlerError(422)`。旧顶层规则字段不复制进入该对象。

## A 轨联调边界

当前 `master` 尚未包含 `rule_config` 字段。Handler 以 `tournament.get("rule_config")` 兼容字段缺失；A 轨落库后可直接调用 `validate_rule_config()`，并将 `draw_seed` 传入单淘汰生成，无需修改抽签核心。D4B 不修改数据库、Migration、Schema、Router 或 OpenAPI，也不建立正式 Affiliation 模型。
