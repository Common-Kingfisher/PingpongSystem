/**
 * Public 只读「空态 / 暂不适用」提示卡（D 轨 Day 4D）。
 *
 * 背景：Public 深链接（`/public/t/:tid/rankings`、`/public/t/:tid/bracket` …）必须**永远可用**。
 * 观众可能从旧书签、群消息或二维码打开一个对本场赛事并不适用的视图，因此这里只做三件事：
 *
 * 1. 说清“为什么这里没有内容”，而不是白屏 / 404 / API 红屏；
 * 2. 给出一个回到**本赛事**可用视图的 CTA（始终携带 path param `tid`）；
 * 3. 不推断赛制，也不替后端回答“本赛事到底有没有排名 / 签表”。
 *
 * ## ⚠️ 边界（Day 4D 冻结，不要越过）
 *
 * - 本组件**不读取任何赛事字段**，因此它不会假装知道当前赛事是循环赛 / 单淘汰 / 小组+淘汰；
 *   文案刻意对三种赛制都成立（“可能尚未产生” + “若本赛事不设置……”）。
 * - 真正的「按赛制隐藏入口 / 显式显示不适用」依赖 A 轨 `TournamentOut.format_code`
 *   与 B 轨 Format Handler 进入 master 后接线（见 `docs/WORKSTREAM_D.md` 的 Day 4D 章节）。
 * - 这里不复制任何排名 / 签表 / BYE / 种子 / 晋级算法，只做展示与导航。
 *
 * ## 为什么 CTA 用 `<Link>` 而不是 `window.location`
 *
 * CTA 目标是另一条 Public 深链接，走 BrowserRouter 的客户端跳转即可；
 * 使用 `Link` 才能保证地址栏与 `useTidFromPath()` 始终同源，避免整页刷新。
 */

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import './PublicEmptyState.css'

export interface PublicEmptyStateAction {
  /** 按钮文案，例如「查看签表」 */
  label: string
  /** 站内绝对路径，必须是 `/public/t/:tid/...` 或其它 self-explaining 路由 */
  to: string
}

export default function PublicEmptyState({
  title,
  hint,
  actions = [],
  children,
}: {
  /** 空态标题（一句话说明“这里现在没有内容”） */
  title: string
  /** 面向观众的一句话解释，可用纯文本 */
  hint?: string
  /** 0..n 个回到可用视图的 CTA */
  actions?: PublicEmptyStateAction[]
  /** 需要更细的说明时使用（例如区分“尚未产生”与“本赛事不设置”） */
  children?: ReactNode
}) {
  return (
    <section className="pub-empty" role="status">
      <h3 className="pub-empty-title">{title}</h3>
      {hint && <p className="pub-empty-hint">{hint}</p>}
      {children && <div className="pub-empty-body">{children}</div>}
      {actions.length > 0 && (
        <div className="pub-empty-actions">
          {actions.map((action) => (
            <Link className="pub-empty-action" key={action.to} to={action.to}>
              {action.label}
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}
