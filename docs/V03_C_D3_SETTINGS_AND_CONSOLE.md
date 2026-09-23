# V0.3 C 轨 Day 3 第一阶段：赛事设置与 Public 入口

## 范围与边界

本阶段从 `origin/master@81827b3` 建立独立分支，只交付设置页展示骨架、AdminLayout 的 Public 快捷入口和 P-01 部署约束检查。D 轨 PR #45 正在修改 `App.tsx`、`ConsolePage.tsx` 与手机录分，本 PR 不碰这些文件；B 轨负责赛制处理器及抽签算法，C 不复制规则算法。设置页暂不挂路由，等 D #45 合并及 A/C route shell 稳定后接线。

P-01 对 C 的要求：生产代码只使用相对 `/api/...` 和同源页面路径；不得硬编码 `localhost:8000`、固定 LAN IP 或后端主机。Vite 开发代理不属于生产代码。权限不由客户端 LAN IP 判断。

## Public 入口

AdminLayout 在有效赛事 ID 下打开 `/public/t/<tid>/live`，使用新标签页和 `rel="noreferrer"`；无赛事 ID 时保持禁用。旧 `/bigscreen?tid=` 路由仍由现有 App 保留用于 V0.2 兼容，本 PR 不删除。

## 设置页结构

页面内五个 Tab：基本信息、赛制与规则、报名设置、公开与展示、高级操作。第一阶段只有“赛制与规则”呈现真实字段；其他 Tab 清楚说明等待相应后端契约，不显示模拟值。

“赛制与规则”四区：

1. 赛事结构：`event_type`、`group_count`；当前 `TournamentOut` 没有稳定 `format_code`，赛制明确显示“等待赛制接口”，绝不从 `stage` 猜测。
2. 比分规则：真实 `games_to_win`、`points_to_win`，以“先胜 N 局 / 每局 N 分”呈现。
3. 晋级与名次：真实 `qualify_per_group`、`bronze_mode`、`placement_mode`；季军与名次赛选项显示中文。
4. 抽签规则：种子保护、同单位规避等待配置契约；只展示冻结原则“赛制合法性 > 种子保护 > 同单位/同队伍规避 > 均衡 > 随机性”，不计算种子或生成抽签。

页面 props 使用由 generated OpenAPI 派生的 `Tournament` 类型。当前主线仅支持创建与读取赛事，不具备完整 Rules Update API；“取消修改 / 保存设置”保持禁用，没有 fake save、localStorage 规则写入或临时 PATCH。

## 后端权威规则生命周期（待契约，不复制成前端状态机）

| 字段 | 可修改时期 | 锁定条件 |
| --- | --- | --- |
| `event_type` | 空赛事 | 出现首个 Player 或 Entry |
| `group_count` / `format` / draw rules | 正式抽签前 | 正式抽签后；尚未生成比赛可撤销抽签、修改、重抽；生成比赛后普通 UI 不解锁 |
| `games_to_win` / `points_to_win` | 第一场比赛开始前 | 首场 PLAYING 或 FINISHED |
| `qualify_per_group` | 相关小组赛开始前 | 首场相关小组赛开始后 |
| `bronze_mode` / `placement_mode` | 淘汰签生成前 | 淘汰签生成后 |

V0.3 不提供 SYSTEM_ADMIN 强制解锁。C 不通过 `if (stage === ...)` 推导锁定状态，未来只消费服务端 `editable`、`locked_reason` 或等价权威结果。

## 后续保存体验

未来规则编辑采用“取消修改 / 保存设置”，不自动保存。未保存离开时提示“有尚未保存的赛事设置”，选择“继续编辑”或“放弃修改并离开”。成功显示“✓ 赛事规则已保存”；失败保留输入并在对应字段/区域展示服务端错误。本阶段无写接口，因此不实现上述交互的虚拟成功路径。

等待 A/B 权威契约：`format_code` 持久化、`rule_config`、supported formats、`display_name`、`editable`、`locked_reason`、原子设置更新接口与 draw config。PR #47、#48 尚开放，不能把其草稿当作已合入主线契约。

## 第二阶段：比赛控制台

D PR #45、A PR #47 与 B PR #48 已合入主线，第二阶段从 `origin/master@78a8788` 开始，保持 D 轨手机录分页面及异常结果契约不变，只完善桌面主裁判工作流：

- 操作错误按冲突（409）、校验（422）、权限（401/403）、服务异常（5xx）分层展示；具体业务文案仍原样使用服务端 `ApiError.message`，前端不复制比赛规则。
- 修改已结束比赛必须先填写操作人和修改理由，再经过一次显式风险确认。确认区展示旧比分，并说明可能影响排名或后续签位；最终是否合法仍由服务端裁决。
- 比分录入或修改成功后，在控制台显示明确成功反馈。若保存成功但列表刷新失败，提示用户手动刷新，不把已成功的写入误报为失败。
- 比分提交失败时弹窗保持打开，所有已填大比分、小比分、操作人、理由和备注均保留；错误在弹窗内就地显示，避免主裁判关窗后重新录入。
- 桌面端与 MobileScore 继续共享同一 OpenAPI ScoreRequest / ScoreRevisionRequest 和 `ApiError` transport 解析，不创建第二套比分 DTO、合法性算法或异常结果枚举。

第二阶段不修改 MobileScore、Auth、后端比分业务、赛制处理器或抽签算法。
