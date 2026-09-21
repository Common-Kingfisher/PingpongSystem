# V0.3 D1B 规则冻结与现况基线

状态：Day 1 冻结稿（实现前契约）  
负责人：B 轨｜规则／比赛引擎  
开工时间：2026-09-21（Asia/Shanghai）  
预计停止时间：未提供；到截止时停止扩展、优先验证与交接。

本文是 V0.3 个人赛规则的 Day 1 边界。它不改变已经发布的 V0.2 / TEAM runtime
契约，也不把旧版 B 现场 UI 工作线当作新版 B 规则引擎工作。

## 1. Git 与现况

| 项目 | 结果 |
| --- | --- |
| 仓库／远程 | `Common-Kingfisher/PingpongSystem`／`origin` |
| 本地基线 | `master` 与本地 `origin/master` 都是 `5f198ea` |
| 工作分支 | `test/v03-rule-engine-day1-skeleton` |
| 工作树 | 建分支前干净；未覆盖任何现有修改 |
| 开工时上游抓取 | 本机 Git 凭据不可用，未完成 fetch；PR base 与当前远端 `master` 均为 `5f198ea` |

| 规则 | 当前实现位置与行为 | V0.3 差距／后续修改面 |
| --- | --- | --- |
| 比分 | `services/scores.py`：大比分校验；首次录分只接受大比分；小组赛已结束后可通过改分补录小比分 | V0.3 要求合法小比分可与大比分同时提交；需调整 score service、API 与测试 |
| 改分 | `services/scores.py`：淘汰赛下游 `PLAYING`/`FINISHED` 时阻断；小组赛一旦生成淘汰签即整体阻断 | 需要对“下游已生成未开赛”进行显式影响分析与确认，不可静默换人 |
| 排名 | `domain/ranking.py`、`services/rankings.py`：真实数据实时重算；同分缺小分时返回并列及 `needs_point_scores` | 保持数据不足为显式状态；人工裁定边界继续由 qualification decision 承接 |
| 分组／单位 | `services/groups.py`：按 affiliation 重叠做软避让 | 双打 affiliation 集合与确定性抽签契约尚未冻结 |
| 淘汰／BYE | `domain/knockout.py`、`services/knockout.py`：非 2 幂签表与 WALKOVER 已存在 | BYE 的通用 Format 职责与种子优先级仍需统一接口承载 |
| Format | 团体赛已有 `TeamFormatSpec`，个人赛无统一 Handler/Strategy | 新增个人赛的轻量 Handler 契约，不复用或污染 TEAM runtime |

## 2. 比分与异常结果

1. 大比分为必填；逐局小比分可选。
2. 没有逐局小比分时，合法大比分可完成比赛。
3. 提交逐局小比分时，局列表必须完整；每局可判胜负；局胜负汇总必须与大比分完全一致。
4. 所有校验以服务端为准，前端只能增强体验。
5. 异常结果（弃权、缺席、判负、取消资格、BYE）不得伪造正常逐局比分。BYE 是签表状态，非普通比赛比分。

## 3. 改分影响规则

| 下游状态 | 冻结行为 |
| --- | --- |
| 未生成或不存在依赖 | 可正常修改。 |
| 已生成但未开赛 | 先返回影响范围；仅在操作者明确确认重算后更新下游参与者。 |
| 已开始或已完成 | 禁止自动换人，转人工处理。 |

无论哪种情况，系统不得把上游胜者变化静默传播为下游参赛人替换。

## 4. Format Handler（个人赛）契约

V0.3 采用 Handler／Strategy 边界，不引入通用规则 DSL。每个个人赛 Handler 应提供：

```text
validate_config()
generate_matches()
calculate_ranking()
advance_participants()
handle_bye()
get_completion_state()
```

| 方法 | 负责 | 不负责 |
| --- | --- | --- |
| `validate_config` | 人数、组数、晋级数及必要配置的合法性 | UI 提示、持久化 |
| `generate_matches` | 由确定 Entry 生成合法结构，遵守种子、BYE、单位约束 | 录分 |
| `calculate_ranking` | 有排名阶段时计算；数据不足时返回不可完成状态 | 为纯淘汰虚构排名 |
| `advance_participants` | 由当前阶段确定下一阶段参赛者 | 静默覆盖已开始下游 |
| `handle_bye` | 非 2 幂 BYE 的签表结构 | 伪造正常比分 |
| `get_completion_state` | 判断赛制完成与能否继续晋级／生成下一阶段 | UI 状态推断 |

只保证 `ROUND_ROBIN`、`SINGLE_ELIMINATION`、`GROUP_KNOCKOUT`；不实现双败、Swiss、团体赛或复杂规则 DSL。

## 5. 抽签优先级

```text
赛制合法性 > 种子保护 > 同单位／同队伍规避 > 组人数／签区均衡 > 随机性
```

- BYE 为签表结构，非 2 幂人数（例如 12 人）必须合法表达；其下一轮依赖必须正确。
- 种子保护高于单位规避，不能为减少同单位碰撞破坏种子硬规则。
- affiliation 是软约束。单打同 affiliation 为一次碰撞；双打任一成员 affiliation 相交即为碰撞；缺失 affiliation 不制造冲突。
- 抽签随机性必须可通过固定随机种子复现。

## 6. 排名数据不足

系统只用真实存在的数据排名。若同分判定需要小分且相关场次未录小分，必须返回“数据不足，需要补录小分或人工裁定”。禁止猜测、补造、随机或按录入顺序决定名次。

## 7. Day 1 测试入口与非目标

`backend/tests/test_v03_rule_engine_contract.py` 建立了比分、改分依赖、Format、BYE／种子／单位与排名的 32 个可收集测试场景。它们目前均为明确跳过的未来实现契约，避免 Day 1 为追求全绿而提前实现 Day 2–Day 4 功能。

Day 1 不实现三种赛制的完整流程、移动端录分、登录／报名、LAN 打包、Organization/Venue、Swiss、双败、复杂团体赛或规则 DSL；也不修复与 D1B 无关的既有失败。

## 8. 验证记录

### D1B 契约测试

```powershell
cd backend
python -m pytest tests/test_v03_rule_engine_contract.py -q -p no:cacheprovider
```

结果：

- 32 skipped
- 0 failed

32 个场景均为 Day 1 显式跳过的未来实现契约，不代表相应 V0.3 功能已经完成。

### 后端完整回归

```powershell
cd backend
python -m pytest -q -p no:cacheprovider
```

结果：

- 仍存在已知基线失败：`tests/test_team_group_ties.py::test_generated_tie_continues_into_production_runtime`。
- D1B 新增测试未引入新的失败。
- 该团体赛失败不属于 D1B 范围，本 PR 不顺手修复。
