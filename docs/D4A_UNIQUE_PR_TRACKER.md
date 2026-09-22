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

当前基线只注册了 `GROUP_KNOCKOUT` Handler。实现阶段将：

- 对真实存在的 `GROUP_KNOCKOUT` 完成持久化与解析接线。
- 对其余尚未进入基线的 Handler 保持显式拒绝，不伪造 B4 算法。
- 不绕过 B 的 validator 自建第二套规则校验。
- 对任何无法经受 B 侧校验的非空 `rule_config`，不得静默入库。

以下联调项在 B4 到位前保持阻塞：

- `ROUND_ROBIN` Handler 端到端接线。
- `SINGLE_ELIMINATION` Handler 端到端接线。
- 任意候选 `rule_config` 的 B 侧 schema 校验。

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
- [ ] 非法配置在入库前被 B validator 拒绝。（B 侧 schema validator 未到位，见 §4）
- [x] 更新操作原子，发生 Match 或 TeamTie 后受保护。
- [x] 权限边界正确。
- [x] TournamentOut 与导出包含赛制配置。
- [x] OpenAPI 已同步。
- [x] 定向测试 0 failed。
- [x] 全量 pytest 0 failed。
- [x] `git diff --check` 通过。
- [ ] 非作者完成赛制与 Schema 复核。
- [ ] 无越权、数据丢失、错误赛制解析等 P0。

## 七、唯一 PR 声明

本阶段唯一 PR：

- PR：https://github.com/Common-Kingfisher/PingpongSystem/pull/47
- 分支：`feat/D4A赛制配置落库`

后续修改继续提交到本分支和本 PR。若需要同步 `master`，一律使用 merge，不使用 rebase。
## 八、当前验证记录（2026-09-22）

- `py_compile`：8 个 D4A 源码与测试文件通过。
- OpenAPI：`backend/export_openapi.py` 生成成功，`--check` 返回 `OpenAPI snapshot is up to date`。
- 定向测试：6 个测试文件，`40 passed`，0 failed。
- 全量测试：在 `backend` 目录运行，收集 908 项，`884 passed / 24 skipped / 0 failed`。
- 静态检查：`git diff --check` 通过。
- 测试警告：仅有既有 FastAPI/Starlette 依赖弃用 warning，无功能失败。

当前尚未提交：11 个已修改文件和 1 个未跟踪测试文件，全部保留在工作区供人工审核。
