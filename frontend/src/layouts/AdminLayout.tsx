import { ReactNode, useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { getActiveTournamentId, parseTournamentId } from '../activeTournament'
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
  currentUserRoleLabel?: string | null
  manageableEvents?: AdminEventOption[]
  navAccess?: Partial<Record<AdminNavKey, AdminNavAccess>>
  onChangePassword?: () => void
  onLogout?: () => void
}

export interface AdminEventOption {
  id: number
  name: string
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
  currentUserRoleLabel,
  manageableEvents = [],
  navAccess = {},
  onChangePassword,
  onLogout,
}: AdminLayoutProps) {
  const location = useLocation()
  const [params] = useSearchParams()
  const [accessMessage, setAccessMessage] = useState<string | null>(null)
  const tournamentId = parseTournamentId(params.get('tid')) ?? getActiveTournamentId()
  const tournamentQuery = tournamentId === null ? '' : `?tid=${tournamentId}`
  const dense = location.pathname === '/console'
  const alternateEvents = manageableEvents.filter(
    (event) => Number.isSafeInteger(event.id) && event.id > 0 && event.id !== tournamentId,
  )

  const eventHref = (eventId: number) => {
    const next = new URLSearchParams(location.search)
    next.set('tid', String(eventId))
    return `${location.pathname}?${next.toString()}`
  }

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
        {alternateEvents.length > 0 ? (
          <details className="admin-event-switcher">
            <summary>
              <small>当前赛事</small>
              <strong>{tournamentName || '选择一场赛事'}</strong>
              <span aria-hidden="true">⌄</span>
            </summary>
            <div className="admin-event-menu">
              {alternateEvents.map((event) => (
                <Link key={event.id} to={eventHref(event.id)}>{event.name}</Link>
              ))}
              <Link className="admin-event-menu-all" to="/events">查看全部赛事</Link>
            </div>
          </details>
        ) : (
          <div className="admin-event-switcher admin-event-switcher--single">
            <small>当前赛事</small>
            <strong>{tournamentName || '选择一场赛事'}</strong>
            <span>{tournamentName ? '当前唯一赛事' : '等待赛事权限数据'}</span>
          </div>
        )}
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
            <details className="admin-user-menu">
              <summary>
                <span>{currentUserLabel || '用户信息待接入'}</span>
                <small>{currentUserRoleLabel || '角色待接入'}</small>
              </summary>
              <div>
                <button disabled={!onChangePassword} onClick={onChangePassword} type="button">修改密码</button>
                <button disabled={!onLogout} onClick={onLogout} type="button">退出登录</button>
              </div>
            </details>
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
