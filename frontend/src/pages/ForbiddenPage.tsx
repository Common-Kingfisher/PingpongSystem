import { Link } from 'react-router-dom'
import './AccessStatePage.css'

export interface ForbiddenPageProps {
  currentUserLabel?: string | null
  currentRoleLabel?: string | null
  returnTo?: 'events' | 'system' | 'tournament'
  tournamentId?: number | null
}

export default function ForbiddenPage({
  currentUserLabel,
  currentRoleLabel,
  returnTo = 'events',
  tournamentId = null,
}: ForbiddenPageProps) {
  const returnHref = returnTo === 'system'
    ? '/system'
    : returnTo === 'tournament' && tournamentId
      ? `/?tid=${tournamentId}`
      : '/events'
  const returnLabel = returnTo === 'system'
    ? '返回系统管理'
    : returnTo === 'tournament'
      ? '返回赛事总览'
      : '返回赛事列表'

  return (
    <main className="access-state-page">
      <section className="access-state-card">
        <span className="access-state-code">403 · FORBIDDEN</span>
        <h1>你没有权限访问此页面。</h1>
        <p>当前账号已登录，但不具备此系统功能所需的角色。系统不会自动将你切换到另一场赛事。</p>
        <div className="access-state-meta">
          <div><span>当前账号</span><strong>{currentUserLabel || '等待当前用户数据'}</strong></div>
          <div><span>当前角色</span><strong>{currentRoleLabel || '等待角色数据'}</strong></div>
        </div>
        <div className="access-state-actions"><Link to={returnHref}>{returnLabel}</Link></div>
      </section>
    </main>
  )
}
