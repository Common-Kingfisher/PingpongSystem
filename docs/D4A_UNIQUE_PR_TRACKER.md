# D4A 唯一 PR 执行跟踪

> 本文件用于声明 D4A 阶段只使用一个 PR，并记录冻结契约、实施范围、验证门槛与未完成联调点。
> 本 PR 创建后，D4A 的后续代码、测试、文档和修改报告全部提交到本 PR，不新增第二个 D4A PR。

## 一、目标

为 B4 的 Format Handler 提供稳定、向后兼容、可校验、可迁移的 Tournament 级赛制配置持久化与 API 契约，使以下格式可以从赛事数据中可靠解析配置：

- `ROUND_ROBIN`
- `SINGLE_ELIMINATION`
- `GROUP_KNOCKOUT`

A 轨只负责数据模型、迁移、API、事务、权限和验证接线，不实现赛制、抽签、排名或晋级算法。

## 二、冻结契约

### 2.1 持久化字段

- `format_code TEXT`
- `rule_config TEXT`
- `rule_version INTEGER`

历史赛事的新字段保持 `NULL`，不擅自默认成 `GROUP_KNOCKOUT`。

### 2.2 对外读取

- `rule_config IS NULL` 对外映射为 `{}`。
- API 输出的 `rule_config` 必须是 JSON object，不暴露数据库内部 TEXT。
- 数据库中出现非法 JSON 时必须明确报错，不能静默当作 `{}`。

### 2.3 配置权威关系

- 旧顶层字段继续作为既有规则的权威来源，包括但不限于 `games_to_win`、`points_to_win`、`group_count`、`qualify_per_group`。
- `rule_config` 只保存 Handler 新增或特有的配置，不镜像旧字段。
- 不形成第二真相源，不双写同一规则。
- `rule_version` 初始为 `1`，最终语义由 B4 冻结为配置契约版本或算法版本。

### 2.4 更新接口

- 使用 `PUT /api/tournaments/{tournament_id}/format`。
- 权限沿用现有 `require_tournament_write`，不扩展角色矩阵。
- 已产生 Match 或 TeamTie 后，禁止静默更换 format 或关键规则，返回 `409`。
- 更新 `format_code + rule_config + rule_version` 必须是单事务、原子操作。

## 三、明确不做

- BYE 算法。
- Seed 与抽签算法。
- Affiliation 单位规避。
- 排名、晋级与错误结果判定。
- C 轨规则 UI。
- D 轨 Public / LAN。
- Day5 Registration、Organization、Venue。
- 完整 lifecycle、ARCHIVED、解锁和审计日志。
- Swiss、双败和通用规则 DSL。
- 团队、个人赛制的统一重构。
- 将旧 `/api/tournaments/...` 整体迁移到 `/api/v1`。

## 四、B4 联调边界

首轮实现时只注册了 `GROUP_KNOCKOUT` Handler；本轮已接入 B #48
`2494185277c19fe34b314d48b549f1c39e1d8c9b` 联调，当前三个个人赛 Handler 均可解析：

- `ROUND_ROBIN`、`SINGLE_ELIMINATION`、`GROUP_KNOCKOUT` 均可通过 A API 保存。
- `ROUND_ROBIN -> {}`、`GROUP_KNOCKOUT -> {}`。
- `SINGLE_ELIMINATION -> {}` 或 `{"draw_seed": <JSON integer>}`。
- 不绕过 B 的 validator 自建第二套规则校验。
- 对任何无法经受 B 侧校验的非空 `rule_config`，不得静默入库。

以下联调项已经在本轮验证：

- `ROUND_ROBIN` / `SINGLE_ELIMINATION` Handler 的 A API 持久化接线。
- 三格式成功保存与 B 侧 semantic validator 拒绝。
- 语义失败时 `format_code + rule_config + rule_version` 三元组完整回滚。

第二轮 B #48 `34439515baf77220b07a5e93dfacdc206904c423` 已补齐 RR 生命周期同步，A 复核结果：

- 三人 RR 全部录分后，Handler `COMPLETED` 且赛事 `stage=FINISHED`。
- 未结束、缺小分或局分完整但仍无法判定时保持 `GROUP_STAGE`。
- 已完成 RR 改分导致无法判定时回退 `GROUP_STAGE`。
- RR 退赛自动判负、GK / SE no-op 与 SE 退赛完成态均无回归。

## 五、实施清单

- [x] Migration v4：增加 `format_code`、`rule_config`、`rule_version`。
- [x] 同步基础建表 SQL 和 ORM 模型。
- [x] Repository：读取转换、创建参数和原子更新。
- [x] Service：存在性、状态、Match / TeamTie 保护与 Handler 校验。
- [x] Schema：更新请求模型和 Tournament 输出模型。
- [x] Router：新增专用 format 更新接口。
- [x] OpenAPI：导出并执行兼容性检查。
- [x] 测试：迁移、旧库升级、Unicode JSON、非法 JSON、权限、409、未知格式、导出。
- [x] 定向测试、全量 pytest、`git diff --check`。

## 六、完成门槛

- [x] 旧数据库迁移不丢数据，旧赛事可兼容读取。
- [x] 三种 format code 与 B 轨冻结定义一致。
- [x] 未知 format 显式失败，不回退到默认赛制。
- [x] 非法配置在入库前被 B validator 拒绝，且三元组完整回滚。
- [x] RR / SE / GK 成功保存并可从持久化配置解析 Handler。
- [x] 更新操作原子，发生 Match 或 TeamTie 后受保护。
- [x] 权限边界正确。
- [x] TournamentOut 与导出包含赛制配置。
- [x] OpenAPI 已同步。
- [x] 定向测试 0 failed。
- [x] 全量 pytest 0 failed。
- [x] 第一轮 A/B integration 组合测试 0 failed。
- [x] 第二轮 A/B integration 组合测试 0 failed。
- [x] `git diff --check` 通过。
- [ ] 非作者完成赛制与 Schema 复核。
- [ ] 无越权、数据丢失、错误赛制解析等 P0。

## 七、唯一 PR 声明

本阶段唯一 PR：

- PR：https://github.com/Common-Kingfisher/PingpongSystem/pull/47
- 分支：`feat/D4A赛制配置落库`

后续修改继续提交到本分支和本 PR。若需要同步 `master`，一律使用 merge，不使用 rebase。
## 八、提交前验证记录（2026-09-22，首轮实现历史）

- `py_compile`：8 个 D4A 源码与测试文件通过。
- OpenAPI：`backend/export_openapi.py` 生成成功，`--check` 返回 `OpenAPI snapshot is up to date`。
- 定向测试：6 个测试文件，`40 passed`，0 failed。
- 全量测试：在 `backend` 目录运行，收集 908 项，`884 passed / 24 skipped / 0 failed`。
- 静态检查：`git diff --check` 通过。
- 测试警告：仅有既有 FastAPI/Starlette 依赖弃用 warning，无功能失败。

当前尚未提交：11 个已修改文件和 1 个未跟踪测试文件，全部保留在工作区供人工审核。

## 九、第一轮 A/B 联调记录（2026-09-22）

### 9.1 联调基线

- A Head：`9af92e09b30a567c98f015372dd47ead0ad21a95`
- B Head：`2494185277c19fe34b314d48b549f1c39e1d8c9b`
- integration merge：`84edbee793bd413661717c44fe23f45b77bdf9af`
- integration worktree：`辅助生成文件/A轨/D4AB-integration`

### 9.2 A 本轮修改

- 移除旧的 `GROUP_CONFIG={"bracket_size":8,"note":"武汉大学"}` 成功路径预期。
- GK 创建、更新和端到端测试改用 B 冻结的 `{}`。
- RR / SE 由“未注册返回 422”改为“成功持久化”。
- 增加 SE 空配置和 `{"draw_seed":7}` 成功路径。
- 增加 RR / GK 未知 key、SE 非整数或未知 key 的 422 与完整回滚测试。
- 未知格式 `SINGLE_ELIM` 仍显式拒绝。

### 9.3 验证结果

- A/B 定向：100 项收集，`80 passed / 20 skipped / 0 failed`。
- integration backend full：953 项收集，`933 passed / 20 skipped / 0 failed`。
- OpenAPI：`backend/export_openapi.py` 生成成功，`--check` 返回
  `OpenAPI snapshot is up to date`。
- `git diff --check`：通过。
- warning：仅为既有 FastAPI / Starlette / httpx 弃用 warning。

### 9.4 B 侧待处理（历史，第二轮已关闭）

- 临时数据库复现 RR 3 人循环赛全部录分后：
  - 赛事 `stage`：`GROUP_STAGE`。
  - Handler 完成态：`{"state":"COMPLETED","can_advance":false,"completed":true}`。
  - 与联调 Gate 要求的 `FINISHED` 不一致，归属 B 侧 `scores/rules` 生命周期同步。
- 第二轮已由 B #48 `3443951` 修复并通过 A 侧复核，见 §10。

### 9.5 当前工作区边界

- 正式 A worktree 只修改 A 测试与本文档，未改 B 实现、B 测试或算法。
- integration worktree 只临时复制 A 测试文件用于验证，不推送、不创建 PR、不合并。
- 本轮修改尚未执行 `git add / commit / push / GitHub comment`，等待人工审核授权。

## 十、第二轮 A/B 联调记录（2026-09-22）

### 10.1 联调基线

- A Head：`aa5cfb558d7c76ed35a41f9aa0d2e0b5a556afdd`
- B Head：`34439515baf77220b07a5e93dfacdc206904c423`
- integration Head：`ba51da5`
- integration worktree：`辅助生成文件/A轨/D4AB-integration`

### 10.2 复核结果

- 三人 RR 全部录分：Handler `COMPLETED`，赛事 `stage=FINISHED`。
- 未结束与缺小分：保持 `GROUP_STAGE`。
- 补齐小分可解：进入 `FINISHED`。
- 已完成 RR 改分后无法判定：回退 `GROUP_STAGE`。
- 两人 RR 退赛后自动判负：进入 `FINISHED`。
- GK / SE lifecycle no-op、SE 决赛选手退赛完成态无回归。
- 真实 A 持久化字段复现：`ROUND_ROBIN + {}`、3 场、`COMPLETED`、`FINISHED`。

### 10.3 验证数字

- D4AB 定向：`89 passed / 20 skipped / 0 failed`。
- RR 生命周期专项：`10 passed / 0 failed`。
- integration backend full：`942 passed / 20 skipped / 0 failed`，共收集 962 项。
- OpenAPI：`OpenAPI snapshot is up to date`。
- `git diff --check`：通过。

### 10.4 后续边界

- 本轮验证针对 A `aa5cfb5` + B `3443951` 的目标组合，不含之后更新的 `master`。
- 正式推送或最终合并前仍需按 merge 方式同步最新 `master` 并重新执行最终 Gate。
