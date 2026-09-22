/**
 * 赛事上下文路由参数解析（D 轨 Day 3）。
 *
 * V0.3 的“可分享 / 可发给现场手机”的 URL 一律把赛事 id 放在 **path** 里：
 *
 * ```
 * /public/t/:tid/live                     ← Day 2 公开页
 * /admin/t/:tid/matches/:matchId/score   ← Day 3 手机录分
 * ```
 *
 * ## 为什么单独一个文件
 *
 * Day 2 出过一次真实 P1：`useParams()` 只能读取**当前组件已经处于的**匹配 Route
 * 及**祖先** Route 的参数，读不到 descendant（后代）Route 的 param；把 tid 解析写在
 * `<Routes>` 外层组件里会拿到 `null`，旧页面随即按 `prop > ?tid= > localStorage`
 * 兼容链回退到 `localStorage.activeTournamentId`，于是“复制出去的链接打开了别人
 * 浏览器里上一次选中的赛事”。
 *
 * 结论（Day 3 沿用同一约束）：
 *
 * 1. 解析函数是**纯函数**，只吃 path param 字符串，不读 `localStorage`、不读 `?tid=`；
 * 2. 调用位置必须在**已匹配的 route element** 内（见 `MobileScoreRoutes.tsx`）；
 * 3. 非法 param 一律返回 `null`，由调用方展示“链接不可用”，**绝不回退**到别的赛事。
 */

import { parseTournamentId } from './activeTournament'

/**
 * 解析正整数路由参数（tid / matchId / entryId ...）。
 *
 * 只接受纯数字字符串：`'12'` → `12`；`' 12'`、`'12a'`、`'-1'`、`''`、`undefined` → `null`。
 * 刻意不调用 `Number()` 做宽松转换，避免 `Number('')===0` / `Number('0x10')===16`
 * 这类静默误判把 URL 指向不存在的资源。
 */
export function parsePositiveIntParam(raw: string | null | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null
  const value = Number(raw)
  return Number.isSafeInteger(value) && value > 0 ? value : null
}

/**
 * 解析录分路由的赛事 id —— 语义与 `parseTournamentId` 完全一致。
 *
 * 这里保留一个显式别名，让“赛事 id”的解析在录分代码里读起来与其他页面同源，
 * 同时避免调用方误用 `Number(param)`。
 */
export function parseRouteTournamentId(raw: string | null | undefined): number | null {
  return parseTournamentId(raw)
}

/** 解析录分路由的比赛 id。 */
export function parseRouteMatchId(raw: string | null | undefined): number | null {
  return parsePositiveIntParam(raw)
}
