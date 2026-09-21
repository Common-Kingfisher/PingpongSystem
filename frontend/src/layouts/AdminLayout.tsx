import { ReactNode, useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { getActiveTournamentId } from '../activeTournament'
import './AdminLayout.css'

export type AdminNavKey =
  | 'overview'
  | 'participants'
  | 'draw'
  | 'orderbook'
  | 'console'
  | 'rankings'
  | 'knockout'
  | 'settings'

export interface AdminNavAccess {
  disabled: boolean
  reason?: string
}

export interface AdminLayoutProps {
  children?: ReactNode
  tournamentName?: string | null
  currentUserLabel?: string | null
  navAccess?: Partial<Record<AdminNavKey, AdminNavAccess>>
  onLogout?: () => void
}

interface AdminNavItem {
  key: AdminNavKey
  label: string
  to: string
  note: string
}

const primaryItems: AdminNavItem[] = [
  { key: 'overview', label: '赛事总览', to: '/', note: '进度与下一步' },
  { key: 'participants', label: '参赛名单', to: '/players', note: '确认谁参赛' },
  { key: 'draw', label: '分组抽签', to: '/draw', note: '建立比赛结构' },
  { key: 'orderbook', label: '秩序册', to: '/orderbook', note: '赛前与赛中输出' },
  { key: 'console', label: '比赛控制', to: '/console', note: '排台与录分' },
  { key: 'rankings', label: '排名', to: '/rankings', note: '小组与名次' },
  { key: 'knockout', label: '淘汰赛', to: '/knockout', note: '签表与晋级' },
]

const settingsItem: AdminNavItem = {
  key: 'settings',
  label: '赛事设置',
  to: '/settings',
  note: '规则、报名与公开',
}

export default function AdminLayout({
  children,
  tournamentName,
  currentUserLabel,
  navAccess = {},
  onLogout,
}: AdminLayoutProps) {
  const location = useLocation()
  const [params] = useSearchParams()
  const [accessMessage, setAccessMessage] = useState<string | null>(null)
  const urlTournamentId = params.get('tid')
  const tournamentId = urlTournamentId && /^\d+$/.test(urlTournamentId)
    ? Number(urlTournamentId)
    : getActiveTournamentId()
  const tournamentQuery = tournamentId === null ? '' : `?tid=${tournamentId}`
  const dense = location.pathname === '/console'

  const publicHref = useMemo(
    () => (tournamentId === null ? null : `/bigscreen${tournamentQuery}`),
    [tournamentId, tournamentQuery],
  )

  const renderItem = (item: AdminNavItem) => {
    const access = navAccess[item.key]
    if (access?.disabled) {
      return (
        <button
          aria-disabled="true"
          className="admin-nav-item is-disabled"
          key={item.key}
          onClick={() => setAccessMessage(access.reason || `你没有使用“${item.label}”的权限。`)}
          type="button"
        >
          <span>{item.label}</span>
          <small>{item.note}</small>
        </button>
      )
    }
    return (
      <NavLink
        className={({ isActive }) => `admin-nav-item${isActive ? ' is-active' : ''}`}
        end={item.to === '/'}
        key={item.key}
        onClick={() => setAccessMessage(null)}
        to={`${item.to}${tournamentQuery}`}
      >
        <span>{item.label}</span>
        <small>{item.note}</small>
      </NavLink>
    )
  }

  return (
    <div className={`admin-shell${dense ? ' admin-shell--dense' : ''}`}>
      <aside className="admin-sidebar">
        <Link className="admin-brand" to="/">
          <span className="admin-brand-mark" aria-hidden="true">TT</span>
          <span>赛事管理<small>TOURNAMENT ADMIN</small></span>
        </Link>
        <Link className="admin-event-switcher" to="/">
          <small>当前赛事</small>
          <strong>{tournamentName || '选择一场赛事'}</strong>
          <span>返回“我的赛事”切换</span>
        </Link>
        <nav className="admin-nav" aria-label="赛事管理">
          {primaryItems.map(renderItem)}
        </nav>
        <div className="admin-nav admin-nav--settings">
          {renderItem(settingsItem)}
        </div>
      </aside>

      <section className="admin-workspace">
        <header className="admin-topbar">
          <div>
            <small>正在管理</small>
            <strong>{tournamentName || '尚未选择赛事'}</strong>
          </div>
          <div className="admin-topbar-actions">
            {publicHref ? (
              <Link className="admin-public-link" to={publicHref}>打开 Public 页面</Link>
            ) : (
              <span className="admin-public-link is-disabled" aria-disabled="true">打开 Public 页面</span>
            )}
            <span className="admin-user">{currentUserLabel || '用户信息待接入'}</span>
            <button disabled={!onLogout} onClick={onLogout} type="button">退出</button>
          </div>
        </header>
        {accessMessage && (
          <div className="admin-access-message" role="status">
            <strong>无权限</strong>
            <span>{accessMessage}</span>
            <button onClick={() => setAccessMessage(null)} type="button">关闭</button>
          </div>
        )}
        <main className="admin-content">{children ?? <Outlet />}</main>
      </section>
    </div>
  )
}
