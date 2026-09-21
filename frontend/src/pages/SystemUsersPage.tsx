import './SystemPages.css'

export interface SystemUserRowViewModel {
  id: number
  displayName: string
  username: string
  roleLabel: string
  active: boolean
  lastLoginLabel: string
}

export interface SystemUsersPageProps {
  users?: SystemUserRowViewModel[] | null
  onCreate?: () => void
  onView?: (id: number) => void
  onResetPassword?: (id: number) => void
  onToggleActive?: (id: number, active: boolean) => void
  onViewGrants?: (id: number) => void
}

export default function SystemUsersPage({ users = null, onCreate, onView, onResetPassword, onToggleActive, onViewGrants }: SystemUsersPageProps) {
  return (
    <div className="system-page">
      <header className="system-page-heading"><div><span>ACCOUNT CONTROL</span><h1>用户管理</h1></div></header>
      <div className="system-user-toolbar">
        <p>{users === null ? '等待用户管理 API；不会用假数据模拟创建成功。' : `共 ${users.length} 个账号，不提供硬删除。`}</p>
        <button disabled={!onCreate} onClick={onCreate}>创建 EVENT_ADMIN</button>
      </div>
      <div className="system-users-table-wrap">
        <table className="system-user-table">
          <thead><tr><th>姓名</th><th>用户名</th><th>角色</th><th>状态</th><th>最近登录</th><th>操作</th></tr></thead>
          <tbody>
            {users && users.length ? users.map((user) => (
              <tr key={user.id}>
                <td>{user.displayName}</td><td>{user.username}</td><td>{user.roleLabel}</td>
                <td><span className={`system-user-status${user.active ? '' : ' is-inactive'}`}>{user.active ? '启用' : '停用'}</span></td>
                <td>{user.lastLoginLabel}</td>
                <td><div className="system-user-actions">
                  <button disabled={!onView} onClick={() => onView?.(user.id)}>查看详情</button>
                  <button disabled={!onResetPassword} onClick={() => onResetPassword?.(user.id)}>重置密码</button>
                  <button disabled={!onToggleActive} onClick={() => onToggleActive?.(user.id, !user.active)}>{user.active ? '停用' : '重新启用'}</button>
                  <button disabled={!onViewGrants} onClick={() => onViewGrants?.(user.id)}>赛事授权</button>
                </div></td>
              </tr>
            )) : (
              <tr className="system-user-empty"><td colSpan={6}>{users === null ? '等待用户管理契约接入' : '尚无用户记录'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
