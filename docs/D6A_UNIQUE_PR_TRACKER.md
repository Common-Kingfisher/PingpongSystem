# D6A 唯一 PR 执行跟踪

> 本文件用于声明 D6A 阶段只使用一个 PR，并冻结目标、边界、可靠性实施范围、验证证据与完成门槛。
> 本 PR 创建后，D6A 的后续代码、测试、文档和修改报告全部提交到本 PR，不新增第二个 D6A PR。

## 一、当前基线

- 本分支从最新 `origin/master` 创建，分支：`fix/D6A-concurrency-transaction-backup-restore`。
- 创建本 PR 时 `master`：`14577ee9d34f054658867de30059c9f00b080b03`（即 D6A 开工基线）。
- 本 tracker 回填时 `origin/master` 仍为 `14577ee9d34f054658867de30059c9f00b080b03`；`origin/master` 已是本分支祖先，无需再补 merge。
- D6B PR #55 已合并，规则压力与边界测试已进入主线。
- A5 PR #51 已合并，Registration / Organization / Venue / `registration_enabled` 已进入主线；本分支基于合并后的 master，无遗留共享文件冲突。
- D6A 当天只使用本分支与 PR #57，不新增第二个 D6A PR。
- 当前工作区为“已实现、已测试、尚未提交”：修改与新增文件见文末“工作区状态”。

### 环境与运行参数

| 项目 | 实测值 |
|---|---|
| Python | 3.12.14 |
| SQLite | 3.53.1 |
| Node.js | v24.14.1 |
| pnpm | 11.19.0 |
| 默认 DB path | `backend/data/demo.db` |
| DB path 优先级 | `PINGPONG_DB_PATH` > `DEMO_DB_PATH` > 默认路径 |
| 连接配置 | `sqlite3.connect(..., check_same_thread=False)` + `PRAGMA foreign_keys = ON` |
| `connection timeout` | 未显式设置，沿用 Python sqlite3 默认值（5 秒） |
| WAL / `busy_timeout` | 未启用、未写入代码；仅有证据支持才调整 |

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
- 同步主线不使用 rebase。

## 五、可靠性测试矩阵

| 风险 | 场景 | 正确结果 | 自动化状态 |
|---|---|---|---|
| 双写 | 两设备同时提交同一比分 | 只形成一个业务事实 | 已覆盖通过 |
| 幂等冲突 | 同 `request_id` 不同 payload | 稳定 409，不污染账本 | 已覆盖通过 |
| 球台抢占 | 两比赛同时抢一球台 | 只一个成功 | 已覆盖通过 |
| 报名确认 | 两管理员同时确认同一 Registration | 只生成一个 Player | 已覆盖通过 |
| 名单锁定竞态 | confirm roster 与迟到报名同时发生 | 不出现确认后偷偷加人 | 已覆盖通过 |
| 改分竞态 | 两人同时改同一已结算比赛 | 不丢更新 / 不静默覆盖 | 已覆盖通过 |
| 退赛/弃权 | 多表同时更新 | 不出现半更新 | 已覆盖回滚通过 |
| 人工裁定 | 多表晋级状态更新 | 不出现半事务 | 已覆盖通过 |
| 审计原子性 | score / ledger / audit 同时写入 | 三者同成或同败 | 已覆盖通过 |
| lock/busy | 多连接同时写 SQLite | 稳定可解释，不无限 hang | 定向 10 轮无 locked |
| 重启恢复 | 写入后应用重启 | 已提交数据可读且一致 | 已覆盖通过 |
| 备份恢复 | 备份、校验、停服恢复 | 失败不覆盖当前库，恢复后完整可用 | 已覆盖通过 |

## 六、实施清单

### A6.0 基线与审计

- [x] 记录真实 `master` SHA、工作区状态、Python / SQLite / Node / pnpm 版本。
- [x] 确认当前 DB path 配置与 `PINGPONG_DB_PATH` 生效方式（优先级见基线表）。
- [x] 运行真实后端、contract check、TypeScript 检查和生产构建（详见第八、九节）。
- [x] 审计当前 SQLite 连接配置、事务边界、lock/busy 行为（未显式配置 timeout，未启用 WAL / busy_timeout）。
- [x] 将真实结果写入本 tracker，不引用 D6B 历史结果充当 D6A 基线。

### A6.1 并发与事务

- [x] 建立 5–6 并发连接的测试框架（`ThreadPoolExecutor` + `threading.Barrier`，每 worker 独立 `db.connect()`）。
- [x] 覆盖比分并发、相同 `request_id` 相同/不同 payload、不同 `request_id` 同时写同一 Match。
- [x] 覆盖改分并发及其下游事务一致性。
- [x] 覆盖球台抢占。
- [x] 覆盖 Registration confirm 并发与 confirm roster / late registration 竞态。
- [x] 覆盖赛事创建、退赛/弃权、人工晋级裁定事务与名单确认事务。
- [x] 覆盖审计与 request ledger 原子性。
- [x] 覆盖失败注入与回滚（报名确认、改分、赛事创建、退赛）。
- [x] 审计长事务；关键“读-判断-写”链路已纳入统一写事务，未发现跨请求事务或外部 IO 长事务。

### A6.2 lock / busy

- [x] 真实复现 lock/busy：5–6 并发写场景下未出现 `database is locked`；并发定向测试连续 10 轮稳定通过。
- [x] 评估 `connection timeout` / `busy_timeout`：未发现需要调整的证据，保持 Python sqlite3 默认 timeout，不启用 `busy_timeout`。
- [x] 评估 WAL：无复现证据，不启用。
- [x] 统一可解释的 busy 错误：`transaction.py` 仅把 locked/busy 映射为 `TransactionBusyError`（409），其余内部错误不再伪装为 409，无边界重试或长时间 hang。

### A6.3 备份与恢复

- [x] 冻结数据库级备份最小方案：SQLite 整库 snapshot backup + 停服 restore（运维 CLI，不暴露 HTTP API）。
- [x] 实现备份工具，并确保备份文件可执行完整性检查（`backup_database` 使用 SQLite backup API，备份后 `integrity_check` + `foreign_key_check`）。
- [x] 实现停服 restore；restore 失败不得覆盖当前 DB（恢复前自动 pre-restore backup，临时库校验后 `os.replace` 原子替换，失败可回滚）。
- [x] 恢复后执行 `foreign_key_check`。
- [x] 验证旧 migration 备份的升级路径（`test_old_migration_backup_is_upgraded_without_data_loss`）。
- [x] 验证恢复后应用可启动、赛事数据可读、migration 可正常继续。
- [x] 明确 backup 目录边界及 `.gitignore` 要求（`<db-parent>/backups/`，`.gitignore` 忽略 `*.db-wal` / `*.db-shm` / `*.db-journal` 与 `backend/data/backups/`）。
- [x] 明确 Tournament export 与数据库级备份的分工：export 用于可读归档/交接，DB backup 用于灾难恢复，二者不互相替代。

### A6.26 Tournament Export 数据完整性（D5 补口）

- [x] Registration 已进入赛事归档导出（`registrations`）。
- [x] Organization 已进入导出（`organizations`）。
- [x] Venue 已进入导出（`venues`）。
- [x] `score_audits` 已进入导出，并把 before/after 快照解析回 JSON 对象。
- [x] 修复人工裁定导出缺陷：`_decision_rows` 原先按 `tournament_id` 查询 `group_id` 过滤的仓库函数，多组赛事会漏裁定；现遍历赛事全部 group，并新增多组回归测试证明旧代码会失败。
- [x] 导出契约同步更新：`docs/openapi-v0.2.json` 与 `frontend/src/generated/openapi.d.ts` 已重新生成，`export_openapi.py --check` 通过；`contract:check` 待提交后复验。

## 七、证据要求

并发测试记录：

```text
worker 数：2 / 5 / 6
场景：比分并发、request_id 幂等/冲突、球台抢占、报名确认、名单锁定、
      改分并发、人工裁定并发
成功数：各场景按断言校验唯一成功或全部合法成功
冲突数：冲突请求均返回稳定 409，无 500
最终 DB 状态：最终事实唯一，无半事务、无双写、无重复 Player
```

备份恢复记录：

```text
source DB：临时测试库 / 默认 backend/data/demo.db 路径规则
backup file：pingpong-backup-YYYYMMDD-HHMMSS.db
integrity_check：ok
restore：需显式 --service-stopped，临时库校验后原子替换
migration：旧版本备份可升级到当前 schema
post-restore tests：FK / 关键表 / 当前 schema 版本 / 应用启动均校验通过
```

## 八、验证证据

### 并发与定向测试

- `tests/test_d6a_concurrency.py`：`15 passed`，覆盖 2 / 5 / 6 worker。
- D6A 定向组合（`test_d6a_concurrency.py` + `test_database_backup_restore.py` + `test_restart_persistence.py` + `test_tournament_export.py`）：`32 passed, 2 warnings`，退出码 0（并发 15 + 备份恢复 8 + 重启 1 + 导出 8）。
- 并发文件连续 10 轮：每轮 `15 passed`，失败轮数 `0/10`，无 hang、无 `database is locked` 直接 500。
- 导出专项：`tests/test_tournament_export.py` `8 passed`，含新增的多组裁定、D5 字段、score_audits 覆盖。

### 备份 / 恢复 / 重启

- `tests/test_database_backup_restore.py`：空库、REGISTRATION 阶段、比赛进行中、FINISHED、损坏备份拒绝且不覆盖原库、强制停服确认、旧 migration 升级、原子替换失败保留原库，全部通过。
- `tests/test_restart_persistence.py`：写入后关闭连接并 `init_db()` 重启，User / Tournament / Player / Entry / Registration / Match / Score / MatchGame / Table / audit / ranking 可恢复，通过。

### 后端全量回归

- 命令：`python -m pytest -o addopts= -q --disable-warnings --tb=short`
- 结果：`1022 passed, 4 warnings in 238.81s`，退出码 0，0 failed。

### Contract / Build Gate

- `python backend/export_openapi.py --check`：`OpenAPI snapshot is up to date`。
- `pnpm contract:generate`：已重生成 `frontend/src/generated/openapi.d.ts`，内容包含新增字段。
- `pnpm contract:check`：当前工作区因生成文件尚未提交，其内部 `git diff --exit-code` 必然返回 1；这是“未提交”而非“生成内容不一致”，提交后应无差异（待 commit 后复验）。
- `pnpm exec tsc --noEmit`：退出码 0。
- `pnpm build`：退出码 0（vite 构建成功）。

### 事务边界与 pragma

- 未新增或修改 SQLite pragma；连接仍为 `check_same_thread=False` + `PRAGMA foreign_keys=ON`，未启用 WAL / `busy_timeout`。
- `transaction.py` 支持嵌套/已存在事务时使用随机 `SAVEPOINT`，避免“事务内再开事务”报错。
- `scores.py` / `scheduling.py` / `entries.py` / `tournaments.py` / `qualification_decisions.py` 的关键“读-判断-写”链路纳入统一写事务，失败整体回滚。
- 未新增业务 HTTP API；restore 仅提供 CLI 且必须显式确认停服。

## 九、P0 收口门槛

> 说明：下列条目是“风险仍存在”的清单，保持未勾选表示 D6A 范围内未发现该风险。
> 但 D/E 现场复验与 E 最终签字尚未执行，因此本节不能由 A 轨单方面宣布 P0=0。

- [ ] 同一比分双写。（自动化覆盖通过）
- [ ] 同一 Registration 生成两个 Player。（6 worker 覆盖通过）
- [ ] 两场比赛占同一 table。（并发覆盖通过）
- [ ] roster 锁定后仍插入 Player。（竞态覆盖通过）
- [ ] score 成功但 audit 丢失。（事务原子性覆盖通过）
- [ ] audit 成功但 score 回滚。（事务原子性覆盖通过）
- [ ] MatchGame 与 Match 大比分不一致。（改分并发覆盖通过）
- [ ] 改分失败但 downstream 已变化。（失败注入回滚通过）
- [ ] withdrawal 半更新。（失败注入回滚通过）
- [ ] backup 文件损坏却报告成功。（integrity_check 覆盖）
- [ ] restore 失败覆盖原库。（损坏备份/替换失败用例覆盖）
- [ ] restore 后 FK 断裂。（foreign_key_check 覆盖）
- [ ] restore 后 migration 不可启动。（旧备份升级用例覆盖）
- [ ] database locked 直接 500 且无稳定处理。（10 轮无 locked；busy 映射 409）
- [ ] 事务 hang / deadlock-like 长时间不返回。（定向 10 轮无 hang）

## 十、最终完成门槛

- [x] 5–6 并发写场景有自动化证据。
- [x] 同一业务事实不会双写。
- [x] table 不会重复占用。
- [x] Registration confirm 不会重复 Player。
- [x] roster lock 与 late registration 无竞态漏洞。
- [x] score / request ledger / audit 原子。
- [x] revise / downstream 原子。
- [x] withdrawal 多表更新原子。
- [x] lock / busy 不导致不可解释 500。
- [x] 无无限重试 / hang。
- [x] 服务重启数据不丢。
- [x] 有真实数据库级 backup。
- [x] backup 可 integrity check。
- [x] restore 不破坏当前 DB。
- [x] restore 后 foreign_key_check 通过。
- [x] restore 后 migration 正常。
- [x] restore 后应用可启动。
- [x] Tournament export 与 DB backup 定位清楚。
- [x] backend full 0 failed。
- [x] 契约快照与生成类型已同步，TypeScript 检查与生产构建通过；`contract:check` 待提交后复验。
- [ ] D/E 现场复验无 A 轨 P0（待 D/E 反馈）。
- [x] 未引入 Day6 之外新功能。
- [ ] 最终由 E 确认相关 P0 已清零（待 E 独立复审/签字）。

## 十一、工作区状态（提交前）

本轮已修改（未提交）：

```text
.gitignore
backend/app/repository.py
backend/app/schemas.py
backend/app/services/entries.py
backend/app/services/qualification_decisions.py
backend/app/services/scheduling.py
backend/app/services/scores.py
backend/app/services/tournament_export.py
backend/app/services/tournaments.py
backend/app/services/transaction.py
backend/tests/test_tournament_export.py
docs/openapi-v0.2.json
frontend/src/generated/openapi.d.ts
```

本轮新增（未跟踪）：

```text
backend/app/services/database_backup.py
backend/backup_db.py
backend/restore_db.py
backend/tests/test_d6a_concurrency.py
backend/tests/test_database_backup_restore.py
backend/tests/test_restart_persistence.py
```

既有未跟踪内容（不得删除或覆盖）：`$null`、`tmp_apply_patch_probe.txt`、`辅助生成文件/`。

## 十二、唯一 PR 声明

- 分支：`fix/D6A-concurrency-transaction-backup-restore`。
- 分支名使用 UTF-8 安全的 ASCII 字符，不直接使用中文。
- PR：#57，标题 `fix(A轨-D6)：加固并发事务与备份恢复`。
- D6A 当天只使用本分支和本 PR。
- 后续代码、测试、文档和修改报告全部追加到本 PR，不新增第二个 D6A PR。
- 不直接修改 `master`。
- 同步主线只使用 merge，不使用 rebase。
- commit、push、comment、merge 分别等待明确授权；merge 必须等待独立复审。

## 十三、最终完成定义

> 在单机 SQLite + 5–6 台现场终端的 V0.3 目标规模下，所有关键写链路都具备可证明的并发与事务一致性；失败不会留下半状态，重复请求不会产生双写；数据库可以安全备份、停服恢复、重启和迁移，并且恢复失败不会破坏当前赛事数据。
