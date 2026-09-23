# V0.3 D7B 规则冻结说明

状态：Release Candidate 冻结候选

范围：B 轨（个人赛规则／比赛引擎）
冻结前代码基线：`master @ 31c7922`

本文只记录当前实现及自动化回归已覆盖的行为，不引入新赛制、规则 DSL、部署逻辑或大规模重构。

## 支持范围与统一入口

支持的个人赛赛制为 `ROUND_ROBIN`、`SINGLE_ELIMINATION` 和
`GROUP_KNOCKOUT`。三者通过 Format Handler 的统一边界收敛：

```text
validate_config()
generate_matches()
calculate_ranking()
advance_participants()
handle_bye()
get_completion_state()
```

`ROUND_ROBIN` 没有下一淘汰阶段；`SINGLE_ELIMINATION` 由既有胜者链推进；
`GROUP_KNOCKOUT` 只有在小组排名及出线无歧义时才生成淘汰签。完成状态由 Handler
给出，不能由 API 或前端另行推断。

## 比分与异常赛果

| 情形 | 冻结行为 |
| --- | --- |
| 正常比赛 | 大比分必填且必须有唯一胜方；只录大比分合法。 |
| 提交逐局小比分 | 必须完整、每局合法、可得到比赛胜方，并与大比分完全一致。 |
| 不完整或不一致逐局分 | 服务端以 422 拒绝，写入前不改变比赛、逐局分、审计或请求幂等状态。 |
| 人工提交的异常赛果 | 当前枚举为 `FORFEIT`、`NO_SHOW`、`WALKOVER`、`DISQUALIFIED`；必须明确指定实际失方，且不得携带或伪造 `GameScore`。 |
| 系统 BYE | 一侧为空签时，淘汰服务自动记为 `WALKOVER` 并推进现有参赛者；不要求人工指定失方，也不生成 `GameScore`。 |

人工异常赛果在小组赛按规则写入胜负局，在淘汰赛只表达胜者推进；两种路径均不生成逐局小分。系统 BYE 不是真实比赛结果，单独遵循签表自动推进路径。

## 改分影响

| 改分情形 | 冻结行为 |
| --- | --- |
| 胜者未改变 | 允许修改本场比分事实；下游参赛者、比赛状态和球台保持不变，即使下游已经开始。 |
| 胜者改变，且全部受影响下游尚未开始 | 重置受影响的等待分支并传播新胜者。 |
| 胜者改变，且任一受影响下游为 `PLAYING` 或 `FINISHED` | 拒绝改分；上游与下游保持原子不变，转人工处理。 |
| 小组赛已经生成淘汰签 | 拒绝小组成绩改分，避免静默改写出线者或历史。 |

系统不会在已开始或已完成的下游比赛中静默替换参赛者。

## 赛制、签表与抽签

### ROUND_ROBIN

循环赛按轮生成，每对参赛者恰好一次；奇数人数使用轮空占位参与轮转计算，但轮空本身不生成真实比赛，保证真实对阵不重复、不遗漏。

### SINGLE_ELIMINATION

纯淘汰支持 2、4、8、16 人及非 2 幂规模。非 2 幂人数扩展到下一档 2 的幂签位，空签通过系统 `WALKOVER` 自动推进，不伪造正常比赛比分。

单淘汰的冻结约束为：

1. 签表容量合法；
2. 已设置的种子进入固定种子槽位；
3. BYE 接收者及其空对手位置固定；
4. Affiliation 仅在不移动种子和 BYE 固定位置的其余可移动签位中作为软约束优化；
5. 多个候选具有相同合法性和 Affiliation 碰撞结果时，允许使用随机选择；配置 `draw_seed` 时结果可复现。

Affiliation 不得破坏签表容量、种子位置或 BYE。双打 Entry 聚合两名成员的所属单位，任一单位相交即视为 Affiliation 碰撞。

当前单淘汰实现不存在独立的“组／签区均衡”优先级阶段，因此本冻结不声明该规则。

### GROUP_KNOCKOUT

小组加淘汰只在小组比赛结束、排名数据充足且出线无歧义或已有有效人工裁定时推进；16 人、4 组、每组前 2 的小组到冠军闭环由 D7B 发布验收测试覆盖。

当前 V0.3 正式冻结并有直接自动化验证的 GROUP_KNOCKOUT 首轮规则为：

- 2 组 × 每组前 2：`A1-B2`、`B1-A2`；
- 4 组 × 每组前 2：`A1-D2`、`C1-B2`、`B1-C2`、`D1-A2`；
- 8 组 × 每组前 2：继续使用第 i 组第 1 名与倒数第 i 组第 2 名的首尾交叉原则。

在上述不需要 BYE 的已验证配置中：

- 同组两名出线者分处不同半区；
- 1/2 号种子分处不同半区。

这些半区保证不扩展到需要 BYE 的 GROUP_KNOCKOUT 配置。

以下配置当前可能由确定性的 compatibility implementation 形成可运行签表，但**不属于 V0.3 正式冻结赛制规则**：

- 偶数组 × 每组前 2，但总晋级人数不是 2 的幂、因此需要 BYE 的配置，例如 6 组 × 每组前 2；
- 上述场景中的具体 BYE 接收者与 BYE 签位分布；
- 上述场景中的同组成员半区分布；
- 3 / 5 / 7 等奇数组；
- 每组晋级人数不是 2；
- 各组晋级人数不一致；
- `_extended_first_pairs()` 提供的其它扩展配对 fallback。

这些 compatibility behavior 只表示当前实现可以生成确定性签表，不构成正式或国际赛制承诺。

`GROUP_KNOCKOUT` 不使用 `SINGLE_ELIMINATION` 的 Affiliation 优化或随机抽签算法，因此本冻结不对 `GROUP_KNOCKOUT` 声明 Affiliation／随机抽签优先级。

## 排名与数据不足

排名只使用真实已录入数据。系统不得猜测排名、随机选择出线者、按无关字段排序，或因数据不足崩溃。

### ROUND_ROBIN

- 缺少打破同分所需逐局小分时，完成状态为 `RANKING_DATA_INSUFFICIENT`。
- 小分已经完整但仍无法拆分同分时，完成状态为 `RANKING_UNRESOLVED`。
- 排名确定后，完成状态为 `COMPLETED`。

### GROUP_KNOCKOUT

- 各组 ranking DTO 的 `needs_point_scores` 标记是否缺少必要逐局小分。
- 出线仍有歧义时，DTO 的 `ambiguous_qualification=true`，Handler 完成状态为 `QUALIFICATION_UNRESOLVED`。
- 人工裁定必须通过既有 qualification decision 流程显式完成，未决时停止自动晋级。

## 自动化回归矩阵

| 冻结域 | 主要回归测试 |
| --- | --- |
| 比分一致性、逐局分、异常结果 | `backend/tests/test_scores.py` |
| 改分影响、下游保护、幂等 | `backend/tests/test_d6b_rule_stress.py`、`backend/tests/test_knockout_flow.py`、`backend/tests/test_knockout_dependency_contract.py` |
| 循环赛、三类 Handler 与完成状态 | `backend/tests/test_round_robin.py`、`backend/tests/test_format_handlers.py` |
| 16 人、4 组、每组前 2 的发布验收 | `backend/tests/test_d7b_rule_freeze.py` |
| 非 2 幂、BYE、淘汰链 | `backend/tests/test_d6b_rule_stress.py`、`backend/tests/test_knockout.py` |
| SINGLE_ELIMINATION 种子、BYE、Affiliation 与可复现抽签 | `backend/tests/test_draw_rules.py`、`backend/tests/test_seeds.py` |
| GROUP_KNOCKOUT 已冻结的 2/4/8 组首尾交叉与无 BYE 半区约束，以及扩展兼容边界 | `backend/tests/test_knockout.py`、`backend/tests/test_d7b_rule_freeze.py` |
| 小组阶段分组／Affiliation | `backend/tests/test_groups.py` |
| 排名、同分、资格裁定与退赛 | `backend/tests/test_ranking.py`、`backend/tests/test_qualification_decisions.py`、`backend/tests/test_entry_withdrawal.py` |

## 明确不支持

V0.3 不在本次冻结中支持 Swiss、双败淘汰、完整团体赛规则、通用规则 DSL，或以 LAN／地址配置影响比赛规则。新增这类能力必须另立需求和测试，不能作为 RC 冻结阶段的附带修改。
