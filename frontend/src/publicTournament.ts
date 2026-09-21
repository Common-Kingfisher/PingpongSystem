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
 * 这里刻意保持**无状态**（直接读路由 path param，不经过 React context）：
 * PublicLayout 与 PublicRoutes 处于同一层路由树，若用 context 传递，
 * PublicRoutes 会在 provider 之下渲染，拿不到值，反而引入时序耦合。
 */

import { useParams } from 'react-router-dom'
import { parseTournamentId } from './activeTournament'

/**
 * 从路由 path param 解析赛事 id。
 *
 * 不读取 `localStorage`，也不读取 query string：Public URL 必须自解释。
 * 非法（缺失 / 非正整数）时返回 null，由调用方展示可读错误。
 */
export function useTidFromPath(): number | null {
  const { tid } = useParams<{ tid: string }>()
  return parseTournamentId(tid)
}
