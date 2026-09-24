# PingpongSystem V0.3 — C 轨 D5 现场运行收口

状态：Phase 1 已实现，待评审

基线：`master@09b2211`（包含 PR #62）

工作分支：`feat/v03-c-d5-dashboard`

## 1. D5 总目标

D5 不继续横向堆叠页面，而是把已经存在的比赛能力收口为主裁判可顺序操作、可辨认现场状态、网络异常时不误导的运行系统。

## 2. Phase 1：赛事总览与现场状态入口

根页面现在有清晰的两种状态：

- 没有有效当前赛事：显示赛事创建与赛事列表；
- 有有效单打或双打赛事：显示真实赛事总览；
- 团体赛事：保持独立队伍、对抗和单盘链路，不使用普通 Match Dashboard 伪装团体赛统计。

创建或选择单打、双打赛事后进入 `/?tid={id}`；TEAM 继续进入既有团体名单入口。active tournament 仍统一由 `activeTournament.ts` 管理。

## 3. Dashboard 数据来源

Dashboard 不定义第二套 transport DTO，全部沿用 generated OpenAPI 类型和现有 `api.ts` wrapper：

- `GET /api/tournaments/{id}/dashboard`：赛事、比赛统计、球台状态、后端推荐比赛编号；
- `GET /api/tournaments/{id}/preflight`：阻断、注意、通过数量；
- players / entries / groups：参赛规模；
- organization / venue：已配置时展示赛事描述，404 作为“尚未配置”省略；
- 其他 organization / venue 错误按正常加载错误处理。

阶段名称只是 format-aware 展示映射：`ROUND_ROBIN + GROUP_STAGE` 显示“循环赛阶段”，`GROUP_KNOCKOUT + GROUP_STAGE` 显示“小组赛阶段”。前端不据此推进赛事状态。

“关键操作”只提供赛前检查、比赛控制、赛程与秩序、排名和淘汰赛导航。页面没有 `next_action` 推断，也不会根据分组、签表或比赛数量决定下一项业务操作。

球台摘要展示全部 OCCUPIED 球台，再按稳定顺序补最多两张 FREE 球台。`recommended_match_id` 只读展示；Dashboard 不读取 `next_playable` 计算推荐，不调用排台接口。

## 4. 自动同步与 stale 语义

- 首次进入正常显示 loading；核心数据失败时显示错误和重试；
- 成功后每 10 秒静默读取最新 Dashboard、Preflight 和参赛规模；
- 页面隐藏时暂停计时器；恢复可见后立即刷新并恢复 10 秒周期；
- 刷新失败保留最近一次成功快照，并明确显示“当前显示可能不是最新状态”；
- 下一次成功后自动清除 stale 提示并更新最近同步时间；
- 页面卸载时清理计时器和 visibility listener。

旧数据不会在网络错误时被清零，Preflight 也不会被伪装成 READY。

## 5. Public 与 TEAM 边界

Phase 1 只链接当前 `master` 已存在的：

- `/public/t/{tid}/live`
- `/public/t/{tid}/schedule`

PR #58 仍处于打开状态。本分支未修改 `PublicRoutes.tsx`、`RegisterPage`、`publicUrls` 或 RegistrationQr 相关文件，也未接管 D 轨公开报名业务。

普通 Dashboard 的 `stats`、`tables` 来源是 Match 体系。TEAM 使用 team ties / team rubbers，因此本 Phase 仅提供诚实的团体管理入口，不创建 TEAM Dashboard 新业务、不把 team ties 转成 Match。

## 6. 后续 Phase 冻结范围

### Phase 2：Console 现场操作 + 5 秒同步

- 后端有 `recommended_match_id` 时可直接展示推荐；
- 没有推荐时，主裁从后端合法 `next_playable` 中手动选择；
- 前端不自行挑选“最优比赛”；
- 球台固定按编号排列；
- 高频动作直出，低频动作进入“更多”；
- Console 使用 5 秒 polling。

### Phase 3：赛程与秩序 + A4 打印

- 系统实时赛程与官方秩序册是两个概念；
- 默认展示实时赛程；
- 官方秩序册无文件时显示“暂未关联”；
- 官方秩序册永远不是运行数据库事实来源；
- 打印采用简洁 A4 实时赛程表 / 赛事运行表，保留生成时间和快照状态，不冒充官方秩序册。

### Phase 4：16 人 / 6 台现场 E2E + D5 Closeout

标准 fixture 为 16 人、6 台，覆盖从赛前检查到现场比赛推进的主裁流程。

## 7. Cross-track 依赖

本 Phase 未新增后端契约。后续如需官方秩序册文件、球台禁用、公开开关或可审计的统一 next action，必须由对应轨道先提供真实契约；C 轨不会在前端伪造。
