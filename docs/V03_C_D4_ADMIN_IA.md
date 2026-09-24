# V0.3 C 轨 D4 Phase 1：管理端信息架构与契约接入

## 本阶段结果

旧的“选手与分组”被拆分为两个管理概念：

- `/players`：参赛名单，只负责名单录入、修改、导入、报名确认和整体名单确认。
- `/draw`：抽签与编排，按赛事 `format_code` 展示适用结构。

赛事设置 `/settings` 保持五个分类：基本信息、赛制与规则、报名设置、公开与展示、高级操作。所有写操作都调用当前 OpenAPI 已存在的接口；缺少后端契约的能力保持只读或等待状态。

## 已接入的真实契约

- `PUT /api/tournaments/{tid}/format`
- `PUT /api/tournaments/{tid}/registration`
- `GET /api/tournaments/{tid}/registrations`
- `POST /api/tournaments/{tid}/registrations/{registration_id}/confirm`
- `GET/PUT /api/tournaments/{tid}/organization`
- `GET/PUT /api/tournaments/{tid}/venue`
- `GET /api/tournaments/{tid}/export`
- `DELETE /api/tournaments/{tid}`
- 既有名单、种子、小组抽签、小组比赛生成与退赛接口

前端 DTO 继续从 `frontend/src/generated/openapi.d.ts` 派生，未手写第二套 transport contract。

## 按赛制呈现

| format_code | 当前页面能力 |
|---|---|
| `GROUP_KNOCKOUT` | 人工种子顺序、小组抽签、各组出线数、小组比赛生成 |
| `ROUND_ROBIN` | 展示循环赛流程与准备状态；等待正式编排 API，不显示种子和小组晋级 |
| `SINGLE_ELIMINATION` | 人工种子顺序；等待正式淘汰签生成 API，不宣称已实现 ITTF 落位 |
| `null` | 要求先在设置页选择并保存赛制，不默认成小组淘汰 |

## 当前阻塞项

### A 轨

- 统一 Rules Settings API：小组数、晋级数、局制、每局分数、季军与名次规则目前只读。
- 基本信息修改 API：赛事名称、日期和项目目前只读。
- 动态球台与 `DISABLED` 状态。
- `public_enabled`、`Registration.REJECTED`、单位必填和 nullable 积分契约。

### B 轨

- 按当前 `format_code` 的统一生成入口尚未暴露为 API。
- `ROUND_ROBIN` 正式编排入口。
- `SINGLE_ELIMINATION` 的 ITTF 风格种子数量校验与落位入口。
- 服务端可审计的 draw seed、重抽签原因与 Draw Revision。

### D 轨

- Public 页面继续由 D 轨维护；管理端只提供稳定 URL `/public/t/{tid}/live`。
- 后续 `public_enabled` 合入后，Public 可见性应继续由后端契约和 Public capabilities 决定。

## CSV / Excel 兼容说明

推荐模板已经改为：

```csv
姓名,所属单位,运动员积分
```

后端 legacy import parser 仍可能接受“种子序号”。本阶段未修改解析算法，也未在名单页面创建第二个种子入口；正式种子只在“抽签与编排”中设置。

## PR #61 复审后的写边界

`roster_confirmed` 不再只是前端按钮的禁用条件。后端已在同一写事务内强制以下规则：

- 单打/双打名单确认后，新增、修改、删除、导入或生成演示选手均返回 409。
- 已确认名单后，待审报名不得再确认入赛，不得重复确认名单，不得重新生成双打配对。
- 已确认名单或已开赛时，不得重新开启线上报名；关闭操作始终允许，用于清理历史原始开关。
- 前端报名设置与公开展示页面使用“原始开关 + REGISTRATION 阶段 + 名单未确认”计算有效状态，不再显示虚假的“报名开放”。

种子顺序仍保留既有的名单确认后同步能力：该服务会同步更新单打 Entry 种子，不会造成 Player/Entry 静默失配，因此本次不将它并入“禁止修改运动员”的锁定范围。

## 验证

变更要求执行：

```text
pnpm test
pnpm exec tsc --noEmit
pnpm build
pnpm contract:check
git diff --check
```

2026-09-24 复审修订已通过：后端完整 pytest、前端 163 个用例、TypeScript + 生产构建、OpenAPI contract check 和 `git diff --check`。
