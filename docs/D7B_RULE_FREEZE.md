# V0.3 D7B 规则冻结说明

状态：Release Candidate 冻结候选

范围：B 轨（个人赛规则／比赛引擎）
基线：`master` 的 `31c7922`；D7B 测试分支 `test/d7b-rule-freeze-regression`

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
| 弃权、缺席、判负、取消资格 | 以 `FORFEIT`、`NO_SHOW`、`WALKOVER`、`DISQUALIFIED` 等异常结果记录；不得携带或伪造 `GameScore`。 |
| BYE | 是签表中的 `WALKOVER` 自动推进，不是正常比赛或伪造比分。 |

异常结果需要明确指定负方；小组赛按规则写入胜负局，淘汰赛只表达胜者推进，均不生成逐局小分。

## 改分影响

| 下游状态 | 冻结行为 |
| --- | --- |
| 不存在或尚未开始 | 胜者改变时重置受影响的等待分支并传播新胜者；胜者未变时保留其排台和比赛状态。 |
| 任一下游为 `PLAYING` 或 `FINISHED` | 拒绝上游改分，保持上游与下游原子不变，交由人工处理。 |
| 小组赛已经生成淘汰签 | 拒绝小组成绩改分，避免静默改写出线者或历史。 |

系统不会在已开始或已完成的下游比赛中静默替换参赛者。

## 赛制、签表与抽签

- 循环赛按轮生成，每对参赛者恰好一次；奇数人数通过轮空轮次保证对阵不重复、不遗漏。
- 纯淘汰支持 2、4、8、16 人及非 2 幂规模。非 2 幂签表以空签／`WALKOVER` 表达 BYE，保证每个有效 Entry 只有一条晋级路径。
- 小组加淘汰只在排名数据充足且出线无歧义时推进；典型 16 人、4 组、每组前 2 的闭环由 Handler 覆盖。
- 抽签优先级固定为：赛制合法性 > 种子保护 > affiliation 软规避 > 组／签区均衡 > 随机性。
- affiliation 为软约束：能规避时优先规避，不能破坏种子或签表合法性；双打任意成员 affiliation 相交即视为碰撞。

## 排名与数据不足

排名使用真实已录入数据。普通同分按既有 tie-break 处理；若判定或出线需要逐局小分而数据不足，Handler 返回数据不足或未决状态，停止自动晋级。系统不得猜测排名、随机选择出线者、按无关字段排序，或因数据不足崩溃。人工裁定仍须通过资格裁定流程显式完成。

## 自动化回归矩阵

| 冻结域 | 主要回归测试 |
| --- | --- |
| 比分一致性、逐局分、异常结果 | `backend/tests/test_scores.py` |
| 改分影响、下游保护、幂等 | `backend/tests/test_d6b_rule_stress.py`、`test_knockout_flow.py`、`test_knockout_dependency_contract.py` |
| 循环赛、三类 Handler 与完成状态 | `backend/tests/test_round_robin.py`、`test_format_handlers.py` |
| 非 2 幂、BYE、淘汰链 | `backend/tests/test_d6b_rule_stress.py`、`test_knockout.py` |
| 种子与 affiliation | `backend/tests/test_draw_rules.py`、`test_seeds.py`、`test_groups.py` |
| 排名、同分、资格裁定与退赛 | `backend/tests/test_ranking.py`、`test_qualification_decisions.py`、`test_entry_withdrawal.py` |

## 明确不支持

V0.3 不在本次冻结中支持 Swiss、双败淘汰、完整团体赛规则、通用规则 DSL，或以 LAN／地址配置影响比赛规则。新增这类能力必须另立需求和测试，不能作为 RC 冻结阶段的附带修改。
