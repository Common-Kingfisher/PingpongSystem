/**
 * 手机录分路由（D 轨 Day 3）。
 *
 * canonical 路由：`/admin/t/:tid/matches/:matchId/score`
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
 * ## ⚠️ Route ownership：D 轨**只**拥有这一条精确 path
 *
 * `/admin` 命名空间的总体所有权属于 A/C 轨（AdminLayout / Login / AccessState /
 * AuthGuard / RequireTournamentAccess 及其他管理端 route）。
 *
 * 因此本文件：
 *
 * - **只**声明 `/admin/t/:tid/matches/:matchId/score` 一条 route；
 * - **不声明** `/admin/*` catch-all：未知 `/admin/...` 一律交还外层管理端 route tree，
 *   否则 A/C 后续接入的 `/admin/events`、`/admin/login`、`/admin/t/:tid/settings`
 *   等都会被 D 轨截断；
 * - 入口判断（`App.tsx`）使用 `matchPath(..., { end: true })` 做**完整**匹配，
 *   绝不使用 `pathname.startsWith('/admin/')`。
 *
 * ## 与 Day 2 相同的 tid 解析约束（PR #44 P1 的教训）
 *
 * `useParams()` 只能读到**当前组件已经处于的**匹配 Route 及祖先 Route 的参数。
 * 因此：
 *
 * - ❌ 在 `MobileScoreRoutes()` 顶层调用 `useParams()` 会得到 `undefined`；
 * - ✅ 只有作为该 route 的 element 渲染的组件（下面的 `AdminScoreAdapter`）
 *   才在匹配上下文内。
 *
 * 非法 / 缺失 param **不等于**“换一场比赛”：adapter 一律不渲染录分页，
 * 因此页面永远不会回退到 `?tid=` 或 `localStorage.activeTournamentId`。
 *
 * ## 本文件是 D 轨在 App.tsx 中的唯一入口
 *
 * 与 `PublicRoutes.tsx` 同样的做法：`App.tsx` 只增加一个入口分支，
 * 具体路由收敛在这里，减少与 A/C 轨争抢同一段代码。
 */

import { Route, Routes, matchPath, useParams } from 'react-router-dom'
import MobileScorePage from './pages/MobileScorePage'
import { parseRouteMatchId, parseRouteTournamentId } from './routeParams'

/**
 * D 轨拥有的**唯一**路由 pattern。
 *
 * 导出给 `App.tsx` 做入口完整匹配，避免把路径字符串写两遍而出现漂移。
 */
export const MOBILE_SCORE_ROUTE_PATH = '/admin/t/:tid/matches/:matchId/score'

/**
 * 入口判定：该 pathname 是否命中 D 轨拥有的那条精确 route。
 *
 * `App.tsx` 与 route ownership 测试**共用这一个**判断，测试因此能在真正生效的
 * 决策表上验证，而不是验证测试自己复制的一份逻辑。
 *
 * 用 react-router 自己的 `matchPath(..., { end: true })` 做**完整**匹配
 * （不自写字符串解析、也绝不用 `startsWith('/admin/')`）。
 */
export function isMobileScoreRoutePath(pathname: string): boolean {
  return matchPath({ path: MOBILE_SCORE_ROUTE_PATH, end: true }, pathname) !== null
}

/** 非法 / 缺失路由参数时的轻量提示（不回退到任何别的赛事或比赛）。 */
function AdminScoreInvalidLink() {
  return (
    <div className="ms-shell">
      <div className="ms-message" role="alert">
        <h1>链接不可用</h1>
        <p>这个录分地址里没有有效的赛事编号或比赛编号。</p>
        <p>
          正确格式形如 <code>/admin/t/12/matches/345/score</code>，请向赛事组织者索取完整地址。
        </p>
      </div>
    </div>
  )
}

/**
 * ## 认证与赛事授权边界（master@81827b3 之后的真实状态）
 *
 * ### 后端：已经落地并生效
 *
 * A 轨认证与赛事授权契约**已合入 master**（`docs/A2.7_AUTH_CONTRACT_DELIVERY.md`、
 * `docs/openapi-v0.2.json` 的 `x-contract`）：
 *
 * - 认证入口：`POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、
 *   `GET /api/v1/auth/me`、`POST /api/v1/auth/change-password`；
 * - 浏览器凭据：`pp_session` Cookie（`HttpOnly` / `SameSite=Lax` / `Path=/`，HTTPS 追加 `Secure`）；
 *   非浏览器脚本：`Authorization: Bearer <opaque token>`；
 * - **录分写入已被后端保护**：`POST /api/matches/{match_id}/score` 依赖
 *   `require_tournament_write`（`backend/app/routers/scores.py`）。因此未登录 / 无该赛事授权时，
 *   服务端分别返回 `401 AUTH_REQUIRED` 与 `404 RESOURCE_NOT_FOUND`，
 *   前端是否渲染本页**不影响**数据安全。
 *
 * ### 前端：仍等 C 轨 router shell
 *
 * 截至同一 master，`RequireAuth` / `RequireTournamentAccess` / `AuthContext`
 * **尚未进入 master**（连 C 轨自己的 `feat/v03-c-d3-settings` 分支上也还没有），
 * `frontend/src/pages/LoginPage.tsx` 目前仍是展示层。
 *
 * 因此这里**仍然不实现**：临时 token 存储、localStorage 登录态、第二套 Guard、
 * 假管理员、401 自动跳登录。这些属于 C 轨 Auth shell，D 轨复制一份只会与正式实现冲突。
 *
 * 本组件就是 AuthGuard 的**唯一**接线点，语义已按最终形态固定：
 *
 * ```tsx
 * // C 轨 RequireAuth / RequireTournamentAccess 合入 master 后，就地替换（不改页面 props）：
 * <RequireAuth>
 *   <RequireTournamentAccess tid={tid}>
 *     <MobileScorePage tid={tid} matchId={matchId} />
 *   </RequireTournamentAccess>
 * </RequireAuth>
 * ```
 *
 * 接线时只剩**一个**前置条件：`RequireAuth` / `RequireTournamentAccess` 已在 master。
 * 另外两条已经满足：`/api/v1/auth/me` 与 401/403/404 错误 DTO 已冻结在契约里；
 * 服务端本身已经拒绝未授权调用。
 *
 * ### 页面当前的错误展示（在 Guard 合入前）
 *
 * `MobileScorePage` 会在提交 / 加载失败时**原样展示服务端 message**：
 * 未登录显示「请先登录」，跨赛事 / 未授权显示「资源不存在」
 * （`RESOURCE_NOT_FOUND` 的防枚举语义，不翻译成“你没有某赛事权限”）。
 * 结构化 `{code,message}` 由共享 `api.ts` 统一解析，页面不自己解析 response。
 */
function AdminScoreGuardBoundary({ tid, matchId }: { tid: number; matchId: number }) {
  return <MobileScorePage matchId={matchId} tid={tid} />
}

/**
 * 手机录分 canonical route 的 element。
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
 * 手机录分路由表 —— **只**声明 D 轨拥有的那一条精确 route。
 *
 * 注意两点：
 *
 * 1. 本组件**不读取** `:tid` / `:matchId`（它们在下面声明的 descendant Route 里）；
 * 2. 这里**没有** `/admin/*` catch-all：未匹配的 `/admin/...` 必须交还外层管理端
 *    route tree（A/C 轨），D 轨不替管理端决定“未知 admin 路径该显示什么”。
 */
export default function MobileScoreRoutes() {
  return (
    <Routes>
      <Route element={<AdminScoreAdapter />} path={MOBILE_SCORE_ROUTE_PATH} />
    </Routes>
  )
}
