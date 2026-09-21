/**
 * Public 赛事 id 解析（D 轨 Day 2）。
 *
 * V0.3 Public 页面的赛事 id 唯一来源是 URL path parameter：
 *
 *     /public/t/:tid/...
 *
 * V0.2 的 Public 页面依赖 `?tid=` / `localStorage.activeTournamentId`，无法满足
 * “复制链接发给另一台手机 / 打开新浏览器 / 局域网访问 / 刷新后仍定位同一赛事”。
 *
 * ## ⚠️ 调用位置约束（PR #44 P1 的根因）
 *
 * `useTidFromPath()` 内部是 `useParams()`，它只能读取**当前组件已经处于的**匹配 Route
 * 以及其**祖先** Route 的参数；**看不到 descendant（后代）Route 的 param**。
 *
 * 因此本 hook 只能在这些位置调用：
 *
 * - ✅ 作为 `<Route path="/public/t/:tid">` 的 element 渲染的 `PublicLayout`；
 * - ✅ 该 Route 下**已匹配的 child route adapter**（见 `PublicRoutes.tsx` 的
 *   `PublicLiveAdapter` 等）。
 * - ❌ 声明 `/public/t/:tid` 的那个 `<Routes>` 的**外层组件**（即 `PublicRoutes()` 自身）：
 *   此时组件尚未匹配到该 Route，`useParams()` 返回 `{}`，本 hook 会得到 `null`。
 *
 * 早期实现正是在 `PublicRoutes()` 顶层调用本 hook，导致 tid 为 `null` → 传给旧页面
 * `tid={undefined}` → 旧页面按兼容链回退到 `localStorage`，即“复制出去的 Public 链接
 * 打开的是管理员浏览器里上一次选的赛事”。修复方式是把 tid 解析下沉到 child route adapter。
 *
 * 这里刻意保持**无状态**（不经过 React context）：调用方一旦处于匹配上下文内即可直接读取，
 * 无需额外 provider，也就不会引入 provider/consumer 的渲染时序耦合。
 */

import { useParams } from 'react-router-dom'
import { parseTournamentId } from './activeTournament'

/**
 * 从路由 path param 解析赛事 id。
 *
 * 不读取 `localStorage`，也不读取 query string：Public URL 必须自解释。
 * 非法（缺失 / 非正整数）时返回 null，由调用方展示可读错误。
 *
 * ⚠️ 必须在**已经匹配 `/public/t/:tid`** 的组件内调用（见文件头说明）。
 */
export function useTidFromPath(): number | null {
  const { tid } = useParams<{ tid: string }>()
  return parseTournamentId(tid)
}
