# D6A 唯一 PR 执行跟踪

> 本文件用于声明 D6A 阶段只使用一个 PR，并冻结目标、边界、可靠性实施范围、验证证据与完成门槛。
> 本 PR 创建后，D6A 的后续代码、测试、文档和修改报告全部提交到本 PR，不新增第二个 D6A PR。

## 一、当前基线

- 本分支从最新 `origin/master` 创建。
- 创建本 PR 时 `master`：`14577ee9d34f054658867de30059c9f00b080b03`。
- D6B PR #55 已合并，规则压力与边界测试已进入主线。
- A5 PR #51 已合并，Registration / Organization / Venue / `registration_enabled` 已进入主线。
- 当前尚未发现其他 D6A PR；本 PR 是 D6A 当天唯一 PR。
- 本文件提交时尚未执行 D6A 基线测试、并发复现、代码修复或备份恢复实现。

## 二、一句话目标

在不扩展新业务功能的前提下，证明并修复 V0.3 在 5–6 台现场终端并发写入、关键多表事务、应用重启和数据库备份恢复下不会出现双写、半事务、锁死、数据丢失或不可恢复状态。

## 三、A6 主责范围

- SQLite 并发可靠性。
- 写事务原子性。
- 失败回滚。
- lock / busy 行为。
- 请求并发冲突时的稳定错误。
- 数据库级备份。
- 数据库级恢复。
- 重启后数据完整性。
- migration + restore 兼容性。
- 与 D/E 现场模拟暴露问题的 A 侧修复。

## 四、明确不做

- 不扩展新业务功能。
- 不重写 B 轨排名、晋级、BYE、种子、Affiliation 抽签、同分算法、改分业务裁决或异常结果业务裁决。
- 不承担 D 轨 5–6 台真手机操作脚本、断网 UI、刷新 UX、大屏 UI 或 LAN 展示。
- 不替代 E 轨全流程验收、P0/P1 清单、独立回归或发布 Gate 判定。
- 不进行无复现证据的 WAL、`busy_timeout` 或连接层大改造。
- 不把 Tournament export 宣称为可恢复数据库备份。
- 不同步主线时使用 rebase。

## 五、可靠性测试矩阵

| 风险 | 场景 | 正确结果 |
|---|---|---|
| 双写 | 两设备同时提交同一比分 | 只形成一个业务事实 |
| 幂等冲突 | 同 `request_id` 不同 payload | 稳定 409，不污染账本 |
| 球台抢占 | 两比赛同时抢一球台 | 只一个成功 |
| 报名确认 | 两管理员同时确认同一 Registration | 只生成一个 Player |
| 名单锁定竞态 | confirm roster 与迟到报名同时发生 | 不出现确认后偷偷加人 |
| 改分竞态 | 两人同时改同一已结算比赛 | 下游原子回滚或一致更新 |
| 退赛/弃权 | 多表同时更新 | 不出现半更新 |
| 人工裁定 | 多表晋级状态更新 | 不出现半事务 |
| 审计原子性 | score / ledger / audit 同时写入 | 三者同成或同败 |
| lock/busy | 多连接同时写 SQLite | 返回稳定、可解释结果，不无限 hang |
| 重启恢复 | 写入后应用重启 | 已提交数据可读且一致 |
| 备份恢复 | 备份、校验、停服恢复 | 恢复失败不覆盖当前 DB，恢复后完整可用 |

## 六、实施清单

### A6.0 基线与审计

- [ ] 记录真实 `master` SHA、工作区状态、Python / SQLite / Node / pnpm 版本。
- [ ] 确认当前 DB path 配置与 `PINGPONG_DB_PATH` 生效方式。
- [ ] 运行真实后端基线、contract check、TypeScript 检查和生产构建。
- [ ] 审计当前 SQLite 连接配置、事务边界、lock/busy 行为。
- [ ] 将真实结果写入本 tracker，不引用 D6B 历史结果充当 D6A 基线。

### A6.1 并发与事务

- [ ] 建立 5–6 并发连接的测试框架。
- [ ] 覆盖比分并发、相同 `request_id` 相同/不同 payload、不同 `request_id` 同时写同一 Match。
- [ ] 覆盖改分并发及其下游事务一致性。
- [ ] 覆盖球台抢占。
- [ ] 覆盖 Registration confirm 并发与 confirm roster / late registration 竞态。
- [ ] 覆盖赛事创建、名单确认、退赛/弃权、人工晋级裁定事务。
- [ ] 覆盖审计与 request ledger 原子性。
- [ ] 覆盖失败注入与回滚。
- [ ] 审计长事务，仅在有明确证据时修复。

### A6.2 lock / busy

- [ ] 先真实复现 `database is locked` 或 busy 行为。
- [ ] 评估 `connection timeout` / `busy_timeout`，不先拍脑袋启用。
- [ ] 只有在证据充分时才评估 WAL。
- [ ] 统一可解释的 busy 错误，禁止无边界重试或长时间 hang。

### A6.3 备份与恢复

- [ ] 冻结数据库级备份最小方案。
- [ ] 实现备份工具，并确保备份文件可执行完整性检查。
- [ ] 实现停服 restore；restore 失败不得覆盖当前 DB。
- [ ] 恢复后执行 `foreign_key_check`。
- [ ] 验证旧 migration 备份的升级路径。
- [ ] 验证恢复后应用可启动、赛事数据可读、migration 可正常继续。
- [ ] 明确 backup 目录边界及 `.gitignore` 要求。
- [ ] 明确 Tournament export 与数据库级备份的分工。

## 七、证据要求

并发测试必须记录：

```text
worker 数
场景
成功数
冲突数
最终 DB 状态
```

备份恢复必须记录：

```text
source DB
backup file
integrity_check
restore
migration
post-restore tests
```

## 八、P0 收口门槛

以下任一存在都不能收口：

- [ ] 同一比分双写。
- [ ] 同一 Registration 生成两个 Player。
- [ ] 两场比赛占同一 table。
- [ ] roster 锁定后仍插入 Player。
- [ ] score 成功但 audit 丢失。
- [ ] audit 成功但 score 回滚。
- [ ] MatchGame 与 Match 大比分不一致。
- [ ] 改分失败但 downstream 已变化。
- [ ] withdrawal 半更新。
- [ ] backup 文件损坏却报告成功。
- [ ] restore 失败覆盖原库。
- [ ] restore 后 FK 断裂。
- [ ] restore 后 migration 不可启动。
- [ ] database locked 直接 500 且无稳定处理。
- [ ] 事务 hang / deadlock-like 长时间不返回。

## 九、最终完成门槛

- [ ] 5–6 并发写场景有自动化证据。
- [ ] 同一业务事实不会双写。
- [ ] table 不会重复占用。
- [ ] Registration confirm 不会重复 Player。
- [ ] roster lock 与 late registration 无竞态漏洞。
- [ ] score / request ledger / audit 原子。
- [ ] revise / downstream 原子。
- [ ] withdrawal 多表更新原子。
- [ ] lock / busy 不导致不可解释 500。
- [ ] 无无限重试 / hang。
- [ ] 服务重启数据不丢。
- [ ] 有真实数据库级 backup。
- [ ] backup 可 integrity check。
- [ ] restore 不破坏当前 DB。
- [ ] restore 后 foreign_key_check 通过。
- [ ] restore 后 migration 正常。
- [ ] restore 后应用可启动。
- [ ] Tournament export 与 DB backup 定位清楚。
- [ ] backend full 0 failed。
- [ ] contract check / build 通过。
- [ ] D/E 现场复验无 A 轨 P0。
- [ ] 未引入 Day6 之外新功能。
- [ ] 最终由 E 确认相关 P0 已清零。

## 十、唯一 PR 声明

- 分支：`fix/D6A-concurrency-transaction-backup-restore`。
- 分支名使用 UTF-8 安全的 ASCII 字符，不直接使用中文。
- 建议标题：`fix(A轨-D6)：加固并发事务与备份恢复`。
- D6A 当天只使用本分支和本 PR。
- 后续代码、测试、文档和修改报告全部追加到本 PR。
- 不新增第二个 D6A PR。
- 不直接修改 `master`。
- 同步主线只使用 merge，不使用 rebase。
- merge 必须等待独立复审和明确授权。

## 十一、最终完成定义

> 在单机 SQLite + 5–6 台现场终端的 V0.3 目标规模下，所有关键写链路都具备可证明的并发与事务一致性；失败不会留下半状态，重复请求不会产生双写；数据库可以安全备份、停服恢复、重启和迁移，并且恢复失败不会破坏当前赛事数据。