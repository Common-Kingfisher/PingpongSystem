# V0.3 C 轨 D4：管理端信息架构与契约接入

## Closeout 结论

C-D4 closeout 已完成。管理端参赛名单、抽签与编排、赛事设置的信息架构已经以当前 OpenAPI 契约为边界收口；尚未落地的能力保持只读、禁用或明确等待状态，不在前端伪造成功。

后续 A/B/D 轨待办属于跨轨契约或公共展示建设，不阻塞 C 轨进入 D5。

## C-D4 已完成

- `/players` 只负责名单录入、修改、导入、报名确认与整体名单确认。
- `/draw` 只负责抽签与编排，并按赛事 `format_code` 展示适用能力。
- `/settings` 保持五个分类：基本信息、赛制与规则、报名设置、公开与展示、高级操作。
- 所有写操作只调用当前 OpenAPI 已存在的接口；缺少后端契约的能力保持只读或等待状态。
- 赛事导出、删除、名单确认后的写保护均沿用真实后端契约。
- 小组出线人数在抽签页只读展示后端 `qualify_count`，不再由该页面承担规则编辑。
- 小组操作使用“生成分组 / 重新生成分组”的真实语义；当前调用会直接生成并保存，正式抽签审计与重抽记录等待 Draw Revision 契约。

## 已接入的真实契约

- `PUT /api/tournaments/{tid}/format`
- `PUT /api/tournaments/{tid}/registration`
- `GET /api/tournaments/{tid}/registrations`
- `POST /api/tournaments/{tid}/registrations/{registration_id}/confirm`
- `GET/PUT /api/tournaments/{tid}/organization`
- `GET/PUT /api/tournaments/{tid}/venue`
- `GET /api/tournaments/{tid}/export`
- `DELETE /api/tournaments/{tid}`
- 既有名单、种子、分组生成、分组清空、小组比赛生成与退赛接口

前端 DTO 继续从 `frontend/src/generated/openapi.d.ts` 派生，未手写第二套 transport contract。

## 按赛制呈现

| format_code | 当前页面能力 |
|---|---|
| `GROUP_KNOCKOUT` | 主裁判人工设置种子顺序、生成/清空分组、只读查看各组出线人数、生成小组比赛 |
| `ROUND_ROBIN` | 只展示循环赛流程与准备状态；不显示种子和小组晋级，等待正式编排 API |
| `SINGLE_ELIMINATION` | 可保存当前种子名单；正式单淘汰种子落位规则等待后端契约，不宣称已实现 ITTF 落位 |
| `null` | 要求先在设置页选择并保存赛制，不默认成小组淘汰 |

## 参赛名单与 CSV 语义

所属单位是推荐填写的抽签信息，用于后续同单位规避。当前后端仍兼容历史缺失单位的数据，因此前端提示推荐填写，但不伪造尚未存在的服务端必填校验。

运动员积分可以留空；后端可能使用兼容默认值 `1000`，该值不代表运动员真实水平。

推荐模板：

```csv
姓名,所属单位,运动员积分
张三,信息学院,1200
李四,自动化学院,
```

后端 legacy import parser 仍可能接受“种子序号”。本阶段未修改解析算法，也未在名单页面创建第二个种子入口；正式种子只在“抽签与编排”中设置。

## PR #61 后的名单写边界

`roster_confirmed` 不只是前端按钮的禁用条件。后端已在同一写事务内强制以下规则：

- 单打/双打名单确认后，新增、修改、删除、导入或生成演示选手均返回 409。
- 已确认名单后，待审报名不得再确认入赛，不得重复确认名单，不得重新生成双打配对。
- 已确认名单或已开赛时，不得重新开启线上报名；关闭操作始终允许，用于清理历史原始开关。
- 前端报名设置与公开展示页面使用“原始开关 + REGISTRATION 阶段 + 名单未确认”计算有效状态，不再显示虚假的“报名开放”。

种子顺序仍保留既有的名单确认后同步能力：该服务会同步更新单打 Entry 种子，不会造成 Player/Entry 静默失配，因此本次不将它并入“禁止修改运动员”的锁定范围。

## 跨轨待办

### A 轨

- 统一 Rules Settings API：小组数、晋级数、局制、每局分数、季军与名次规则目前只读。
- 基本信息修改 API：赛事名称、日期和项目目前只读。
- `public_enabled`、动态球台与 `DISABLED` 状态。
- `Registration.REJECTED`、单位服务端必填和 nullable 积分契约。

### B 轨

- 按当前 `format_code` 的统一生成入口。
- `ROUND_ROBIN` 正式编排入口。
- `SINGLE_ELIMINATION` 正式种子校验与落位入口。
- 服务端可审计的 draw seed、重抽签原因与 Draw Revision。

### D 轨

- PR #58 截至 2026-09-24 仍处于打开状态；本次 C-D4 closeout 不修改其 Public 页面代码。
- 管理端只提供稳定 URL `/public/t/{tid}/live`。
- 后续 `public_enabled` 合入后，Public 可见性继续由后端契约和 Public capabilities 决定。

## 验证

本次只修改前端页面、前端测试与本文档，不修改后端或 OpenAPI 契约。要求执行：

```text
pnpm test
pnpm exec tsc --noEmit
pnpm build
pnpm contract:check
git diff --check
```

实际执行结果以本次 PR 的验证记录为准；不得通过删除测试或降低断言使检查通过。
