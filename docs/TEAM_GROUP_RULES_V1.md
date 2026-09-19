# 团体小组排名规则 V1（Team Group Standings）

状态：**A6.2 冻结**。实现位置：`backend/app/domain/team_standings.py`、
`backend/app/services/team_standings.py`。
本文件是团体小组排名的**唯一业务规则源**：代码不得根据"常见乒乓球规则"、个人赛
`domain/ranking.py` 的排序口径或任何未写入本文的惯例自行补规则。**改规则先改本文。**

> 关于"冻结"的诚实说明：本文由 A6.2 开发任务书（§ 4–§ 12）逐条固化而成。
> 任务书未明确的极小歧义已在 §9「待 Reviewer 确认」逐条列出并给出了 V1 采取的取值，
> **这些取值需要 Reviewer 确认后才能视为正式冻结**；确认后应把对应条目移入正文并去掉标记。

## 0. 适用范围与边界

- 只看**团体小组赛**（`team_ties.stage = 'GROUP'`）。淘汰赛对抗不参与小组排名。
- 只提供**排名事实**，不写入任何晋级结果：A6.2 **不做** qualification 写入、
  **不做**人工裁定 API、**不做**抽签、**不做**淘汰赛。
- 排名**不持久化**（没有 `team_standings` 表）：每次查询都从真实的
  `team_ties` / `team_rubbers` 事实重新计算，避免第二真相源。
- 规则里**没有** "points ratio"（得失分比率）：V1 在 Step 3 之后即判定并列。

## 1. 输入事实

| 事实 | 来源 | 用途 |
|---|---|---|
| 参赛队伍 | `entries(entry_type='TEAM')`，按 `id` 升序 | 排名行的身份与稳定顺序；`status` 决定参赛资格 |
| 团体对抗 | `team_ties`（`stage='GROUP'`、`group_id = 本组`） | 比赛积分、盘/局统计 |
| 单盘 | `team_rubbers`（属于上述对抗） | 盘 W/L、局 W/L |

## 2. 统计口径

### 2.1 参与统计的对抗

- **只有 `TeamTie.status == 'FINISHED'` 且带胜者（`winner_entry_id`）的对抗**参与统计。
- 未完成对抗（`WAITING` / `PLAYING`）**既不计比赛积分，也不计入**
  `ties_played` / `ties_won` / `ties_lost`；它只影响 §6 的 provisional 判定。
- 跨组对抗不参与本组统计（组内统计只累加"双方都在本组"的对抗）。

### 2.2 参与统计的盘

- **只有同一场已完成对抗内 `TeamRubber.status == 'FINISHED'` 的盘**参与盘/局统计。
- `SKIPPED`（一方达到获胜盘数后未打的盘）**完全忽略**；
  `PENDING` / `READY` / `PLAYING` 同样不参与。
- 盘胜负来源：`team_rubbers.winner_entry_id`。

## 3. Step 0：比赛积分（match points）

| 情形 | 胜方 | 负方 |
|---|---|---|
| 正常完成（`FINISHED`） | **2** | **1** |
| 未完成 | 不计入 | 不计入 |

- **禁止**使用 `win = 1 / loss = 0` 或任何"未完成按 0 分"的近似——那是另一套积分制度。

## 4. Step 1–3：同分拆分（tie-breaking）

记 `T` = 当前**比赛积分完全相同**的队伍集合。

> **子集（subset）**：当前正在比较的那批队伍。初始 subset = `T`。
> 所有比率与积分都在 **subset 内部重新计算**：只累加"双方都在 subset 内"的对抗。

对当前 subset 依次执行：

1. **Step 1 —— 子集内比赛积分（subset match points）**
   按 §3 的同一套 2/1 规则，但**只统计 subset 内部之间的对抗**。
2. **Step 2 —— 盘 W/L 比率（Rubber W/L ratio）**
   按 §2.2 统计，即 `rubber_wins / rubber_losses`。
3. **Step 3 —— 局 W/L 比率（Games W/L ratio）**
   按 §5 统计，即 `games_won / games_lost`。
4. **Step 4 —— 仍不可分**：V1 **不存在**下一个 ranking key（没有 points ratio），
   subset 内所有队伍**并列**，名次用区间表示（§7），交由 A6.3 / 人工裁定处理。

### 4.1 部分区分（partial resolution）必须"重算 + 重启"

若某个 key 把 subset 拆成了多个子组：

- 每个子组**缩小 subset 后从 Step 1 重新开始**（连同"子集内积分"一起重算）；
- **禁止**"直接从下一个 ranking key 继续比较"（那等价于把点数比率当成全局键，会得出错误名次）；
- 若某个 key **不可用**（见 §4.2），跳过该 key，使用下一个；所有 key 都不可用则判并列。

### 4.2 比率比较：不比较浮点，且区分"不可用"与"相等"

比较 `wins_a / losses_a` 与 `wins_b / losses_b` 使用**交叉乘法**（整数，无浮点误差）：

```
wins_a * losses_b   vs   wins_b * losses_a
```

分母为 0 的两种特殊情形：

| 情形 | 含义 | 结果 |
|---|---|---|
| `wins > 0, losses == 0` | 全胜 → 比率 **+∞** | 大于任何有限比率与 0/0；两侧同为 +∞ 则相等 |
| `wins == 0, losses == 0` | **没有数据**（没打过） | 与**同为 0/0** 的一方**无法比较**（该 key 对这一对不可用）；与**有数据**的一方则按普通数学比较（有数据方要么全胜要么全负，大小确定） |

- "不可用"与"相等"**必须区分**：不可用时该 key 对这一对队伍不产生任何结论，
  既不能判定谁前谁后，也不能判定并列。
- 三队及以上时，subset 内只要存在**一对不可比较**，该 key 对整个 subset 即为不可用
  （不给出部分结论，避免自相矛盾的排序）。

## 5. 局 W/L（Games W/L）

直接使用既有 `team_rubbers.home_score` / `team_rubbers.away_score`（该对抗的 A 队 / B 队视角）：

- 某盘 A 队 `3:1` B 队 → A 队 `games_won += 3`、`games_lost += 1`；B 队相反；
- **只统计 FINISHED 的盘**（§2.2）；
- **不得新增** `MatchGame` / `TeamGame` / 任何逐局小分表：A6.2 不需要数据库迁移。

## 6. Provisional 与参赛资格

### 6.1 provisional

只要本组**还存在任何未完成的 TeamTie**（无论涉及 ACTIVE 还是 WITHDRAWN 队伍），则：

- `provisional = true`
- `automatic_qualification_allowed = false`

V1 **不做结果可能性分析**（不推断"某队是否已锁定出线"），只回答"是否已经全部打完"。

### 6.2 退赛（WITHDRAWN）

- 退赛队伍**已经完成的比赛继续计入**排名（成绩不抹掉）。
- 退赛队伍 `eligible_for_qualification = false`。
- 若该组所有 TeamTie 都已完成 → 排名可以是 **final**（`provisional = false`），
  但退赛队伍的 `eligible_for_qualification` 仍为 `false`。
- 若退赛队伍仍有未完成的 TeamTie → 按 §6.1，**整个小组**的
  `automatic_qualification_allowed = false`（不只是那一支队伍）。
- 退赛队伍**仍然占用名次区间**（按其竞技成绩正常参与排名），只是不能晋级。

## 7. 并列名次表示（ambiguous rank range）

- **绝不按 id 打破同分**。
- 并列的一组队伍**共享同一个名次区间** `rank_start` / `rank_end`：

  例：B/C/D 三者完全不可分，占第 2–4 名 → 三者都是 `rank_start=2`、`rank_end=4`、
  `ambiguous=true`。**不得**输出 B=2 / C=3 / D=4。

- `rank_start == rank_end` 表示名次唯一（`ambiguous=false`）。
- 行内**展示顺序**在同一并列区间内按 `entries.id` 升序（确定、可测试），
  这只是展示顺序，**不是名次**。

## 8. 输出字段

小组级：`group_id`、`group_name`、`provisional`、`ambiguous`、
`automatic_qualification_allowed`、`qualify_count`、`standings[]`。

每行：`team_entry_id`、`team_name`、`status`、`match_points`、
`ties_played`、`ties_won`、`ties_lost`、`rubber_wins`、`rubber_losses`、
`games_won`、`games_lost`、`rank_start`、`rank_end`、`ambiguous`、
`eligible_for_qualification`、`qualification_position_state`。

- **不提供** `qualified: true/false`——晋级写入属于 A6.3。
- `qualification_position_state` 只是"名次相对晋级线的事实描述"，不推进任何晋级，取值：
  - `RESOLVED`：排名非 provisional、非 ambiguous，且该队名次区间完全落在晋级线内；
  - `UNDECIDED`：排名 provisional 或 ambiguous（含跨晋级线并列）；
  - `ELIGIBLE_ONLY`：已确定名次但落在晋级线外（或本身 `eligible_for_qualification = false`）；
  - `UNKNOWN`：并列区间横跨晋级线且部分在内（此时一定是 `UNDECIDED`），保留给未来扩展。
- `qualify_count` 取 `groups.qualify_count`，为空时回退赛事 `tournaments.qualify_per_group`
  （与个人赛 `/rankings` 同一口径，不新增规则）。

## 9. 待 Reviewer 确认（V1 采用的取值）

以下条目在 A6.2 任务书中未明确，V1 的取值如下（**已实现并有测试**），确认后移入正文：

1. `ties_played` / `ties_won` / `ties_lost` 只统计 `FINISHED` 的 TeamTie
   （与 §2.1「未完成不作为正常完赛结果计入」一致）。
2. 盘/局统计只取 **FINISHED TeamTie 内**的 FINISHED 盘（不对未完成对抗中的已打完盘做半场统计）。
3. 退赛队伍**仍出现在** standings 中（保留其已完成成绩），只是不可晋级。
4. 退赛队伍**仍占用名次区间**，不特殊插入到末尾。
5. 两队都"没打过任何盘"（`0/0` 对 `0/0`）时，盘比率 key 判**不可用**，继续看局比率；
   局比率同样不可用则并列。
6. `qualify_count` 为空时回退 `qualify_per_group`（沿用个人赛口径）。

## 10. 明确未实现（后续批次）

- **A6.3 qualification**：晋级写入、出线名单、并列人工裁定 API。
- **A6.4 Team knockout**：团体淘汰赛结构与对阵。
- **人工裁定**（个人赛已有 `/qualification-decision`，团体赛没有）。
- **points ratio**（得失分比率）：V1 在 Step 3 后即并列。
- **Scheduler / ETA**：团体赛不参与排程与预计时间。
- **TEAM 阶段推进**（`Tournament.stage`）。
