/**
 * 手机录分路由（D 轨 Day 3）。
 *
 * 路由：`/admin/t/:tid/score/:matchId`
 *
 * ## 为什么是 `/admin/...`
 *
 * D 轨 Day 1 已冻结：手机录分**不是** PUBLIC 页面，它属于 EVENT_ADMIN 权限域。
 * 把录分放进 `/admin/` 命名空间有两个后果，这里都显式处理：
 *
 * 1. 它必须能被 C/A 轨的 `RequireAuth → RequireTournamentAccess` 直接包住
 *    （见下面的 `AdminScoreGuardBoundary`）；
 * 2. 它与 `/public/t/:tid/...` 完全分离：公开端不出现任何录分入口。
 *
 * ## 与 Day 2 相同的 tid 解析约束（PR #44 P1 的教训）
 *
 * `useParams()` 只能读到**当前组件已经处于的**匹配 Route 及祖先 Route 的参数。
 * 因此：
 *
 * - ❌ 在 `MobileScoreRoutes()` 顶层调用 `useParams()` 会得到 `undefined`；
 * - ✅ 只有作为 `/admin/t/:tid/score/:matchId` 的 element 渲染的组件
 *   （下面的 `AdminScoreAdapter`）才在匹配上下文内。
 *
 * 非法 / 缺失 param **不等于**“换一场比赛”：adapter 一律不渲染录分页，
 * 因此页面永远不会回退到 `?tid=` 或 `localStorage.activeTournamentId`。
 *
 * ## 本文件是 D 轨在 App.tsx 中的唯一入口
 *
 * 与 `PublicRoutes.tsx` 同样的做法：`App.tsx` 只增加一个提前返回分支，
 * 具体路由收敛在这里，减少与 A/C 轨争抢同一段代码。
 */

import { Route, Routes, useParams } from 'react-router-dom'
import MobileScorePage from './pages/MobileScorePage'
import { parseRouteMatchId, parseRouteTournamentId } from './routeParams'

/** 非法 / 缺失路由参数时的轻量提示（不回退到任何别的赛事或比赛）。 */
function AdminScoreInvalidLink() {
  return (
    <div className="ms-shell">
      <div className="ms-message" role="alert">
        <h1>链接不可用</h1>
        <p>这个录分地址里没有有效的赛事编号或比赛编号。</p>
        <p>
          正确格式形如 <code>/admin/t/12/score/345</code>，请向赛事组织者索取完整地址。
        </p>
      </div>
    </div>
  )
}

/**
 * ## 认证接线边界（Day 3 明确状态）
 *
 * 截至本 PR 的基线 `master`（含 PR #41/#43/#44）：
 *
 * - 后端**没有**任何 auth router / session / `/auth/me` / 权限依赖：
 *   `backend/app/main.py` 只注册了业务 routers，没有 auth 相关依赖项；
 * - C 轨的 `AdminLayout`、`LoginPage`、`AccessStatePage` 等**展示层**已合入，
 *   但 PR #42（A2.1/A2.2 数据模型与 Session 服务）与 C 轨开放 PR
 *   `feat/v03-admin-auth-routing`（A2.3 Auth API + AuthContext/Guard）**都还没有进入 master**。
 *
 * 因此这里**不实现**：token、localStorage 登录态、临时用户系统、第二套权限判断。
 * 那会造出一个与 A 轨正式契约冲突的“假认证”，比暂时不接线危险得多。
 *
 * 本组件就是未来 AuthGuard 的**唯一**接线点，语义已经按最终形态固定：
 *
 * ```tsx
 * // A 轨 contract 合入 master 后，本 PR 内就地替换为（不改动 MobileScorePage 的 props）：
 * <RequireAuth>
 *   <RequireTournamentAccess tid={tid}>
 *     <MobileScorePage tid={tid} matchId={matchId} />
 *   </RequireTournamentAccess>
 * </RequireAuth>
 * ```
 *
 * 需要满足的三个前置条件（缺一不可，否则接线是错的）：
 *
 * 1. `GET /auth/me` 与其 401/403/404 错误 DTO 已在 master；
 * 2. `RequireAuth` / `RequireTournamentAccess` 组件已在 master（C 轨）；
 * 3. 录分 API 本身在服务端拒绝了未授权调用（**前端 Guard 只改善 UX，
 *    服务端才是唯一安全边界** —— 这一点在接线时必须一起确认）。
 */
function AdminScoreGuardBoundary({ tid, matchId }: { tid: number; matchId: number }) {
  return <MobileScorePage matchId={matchId} tid={tid} />
}

/**
 * `/admin/t/:tid/score/:matchId` 的 route element。
 *
 * 只有它处于已匹配的 route context 内，因此只有它能读取 path param。
 *
 * 导出供测试复用：`src/__tests__/MobileScoreRouteRace.test.tsx` 要在**同一个
 * MemoryRouter 内**真实切换 `:tid` / `:matchId` 才能复现“旧请求晚返回覆盖新比赛”，
 * 而录分页本身刻意不含任何跳转链接。该测试直接复用这个真实 adapter（不复制路由实现），
 * 只把记录接口与导航探针注入测试自己的 route element。
 */
export function AdminScoreAdapter() {
  const { tid, matchId } = useParams<{ tid: string; matchId: string }>()
  const tournamentId = parseRouteTournamentId(tid)
  const targetMatchId = parseRouteMatchId(matchId)

  if (tournamentId === null || targetMatchId === null) return <AdminScoreInvalidLink />

  return <AdminScoreGuardBoundary matchId={targetMatchId} tid={tournamentId} />
}

/**
 * 手机录分路由表。
 *
 * 注意：本组件**不读取** `:tid` / `:matchId`（它们在下面声明的 descendant Route 里）。
 */
export default function MobileScoreRoutes() {
  return (
    <Routes>
      <Route element={<AdminScoreAdapter />} path="/admin/t/:tid/score/:matchId" />
      {/* 未知 /admin/* 子路径：给出可读提示，而不是白屏或误落到别的赛事 */}
      <Route element={<AdminScoreInvalidLink />} path="/admin/*" />
    </Routes>
  )
}
