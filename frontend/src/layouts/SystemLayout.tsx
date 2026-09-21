import { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import './SystemLayout.css'

export interface SystemLayoutProps {
  children?: ReactNode
  currentUserLabel?: string | null
  currentUserRoleLabel?: string | null
  onChangePassword?: () => void
  onLogout?: () => void
}

const items = [
  { to: '/system', label: '系统总览', note: '状态与异常' },
  { to: '/system/users', label: '用户管理', note: '账号与状态' },
  { to: '/system/events', label: '赛事列表', note: '全局赛事概况' },
  { to: '/system/backups', label: '备份与恢复', note: '运维入口' },
]

export default function SystemLayout({
  children,
  currentUserLabel,
  currentUserRoleLabel,
  onChangePassword,
  onLogout,
}: SystemLayoutProps) {
  return (
    <div className="system-shell">
      <aside className="system-sidebar">
        <div className="system-brand"><span>SYS</span><strong>PingpongSystem<small>SYSTEM CONTROL</small></strong></div>
        <div className="system-scope"><small>管理域</small><strong>系统管理</strong><span>不自动获得赛事写权限</span></div>
        <nav aria-label="系统管理">
          {items.map((item) => (
            <NavLink className={({ isActive }) => isActive ? 'is-active' : ''} end={item.to === '/system'} key={item.to} to={item.to}>
              <span>{item.label}</span><small>{item.note}</small>
            </NavLink>
          ))}
        </nav>
      </aside>
      <section className="system-workspace">
        <header className="system-topbar">
          <div><small>当前账号</small><strong>{currentUserLabel || '用户信息待接入'}</strong><span>{currentUserRoleLabel || '角色待接入'}</span></div>
          <div><button disabled={!onChangePassword} onClick={onChangePassword}>修改密码</button><button disabled={!onLogout} onClick={onLogout}>退出登录</button></div>
        </header>
        <main className="system-content">{children ?? <Outlet />}</main>
      </section>
    </div>
  )
}
