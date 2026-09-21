import { FormEvent, useState } from 'react'
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
  createFormOpen?: boolean
  createFormSubmitting?: boolean
  onCancelCreate?: () => void
  onSubmitCreate?: (values: CreateEventAdminFormValues) => void | Promise<void>
  onView?: (id: number) => void
  onResetPassword?: (id: number) => void
  onToggleActive?: (id: number, active: boolean) => void
  onViewGrants?: (id: number) => void
}

export interface CreateEventAdminFormValues {
  username: string
  displayName: string
  password: string
  phone: string | null
  note: string | null
}

export interface CreateEventAdminFormProps {
  submitting?: boolean
  onCancel?: () => void
  onSubmit?: (values: CreateEventAdminFormValues) => void | Promise<void>
}

export function CreateEventAdminForm({ submitting = false, onCancel, onSubmit }: CreateEventAdminFormProps) {
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [phone, setPhone] = useState('')
  const [note, setNote] = useState('')
  const hasLetter = /[A-Za-z]/.test(password)
  const hasNumber = /\d/.test(password)
  const passwordValid = password.length >= 12 && hasLetter && hasNumber
  const passwordsMatch = password.length > 0 && password === confirmPassword
  const canSubmit = Boolean(onSubmit) && !submitting && passwordValid && passwordsMatch

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canSubmit || !onSubmit) return
    void onSubmit({
      username: username.trim(),
      displayName: displayName.trim(),
      password,
      phone: phone.trim() || null,
      note: note.trim() || null,
    })
  }

  return (
    <form className="system-user-create" onSubmit={submit}>
      <header>
        <div><span>NEW ACCOUNT</span><h2>创建赛事管理员</h2></div>
        <b>EVENT_ADMIN</b>
      </header>
      <p>账号默认启用；创建账号不会自动授予任何赛事权限。</p>
      <div className="system-user-create-grid">
        <label><span>用户名</span><input autoComplete="off" onChange={(event) => setUsername(event.target.value)} required value={username} /></label>
        <label><span>姓名</span><input onChange={(event) => setDisplayName(event.target.value)} required value={displayName} /></label>
        <label><span>初始密码</span><input autoComplete="new-password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></label>
        <label><span>确认初始密码</span><input autoComplete="new-password" onChange={(event) => setConfirmPassword(event.target.value)} required type="password" value={confirmPassword} /></label>
        <label><span>手机号（可选）</span><input inputMode="tel" onChange={(event) => setPhone(event.target.value)} value={phone} /></label>
        <label><span>备注（可选）</span><input onChange={(event) => setNote(event.target.value)} value={note} /></label>
      </div>
      <div className="system-password-rules" aria-live="polite">
        <span className={password.length >= 12 ? 'is-valid' : ''}>至少 12 个字符</span>
        <span className={hasLetter ? 'is-valid' : ''}>包含字母</span>
        <span className={hasNumber ? 'is-valid' : ''}>包含数字</span>
        <span className={passwordsMatch ? 'is-valid' : ''}>两次输入一致</span>
      </div>
      <footer>
        <button className="secondary" disabled={!onCancel || submitting} onClick={onCancel} type="button">取消</button>
        <button disabled={!canSubmit} type="submit">{submitting ? '正在创建…' : onSubmit ? '创建账号' : '等待用户管理 API'}</button>
      </footer>
    </form>
  )
}

export default function SystemUsersPage({
  users = null,
  onCreate,
  createFormOpen = false,
  createFormSubmitting = false,
  onCancelCreate,
  onSubmitCreate,
  onView,
  onResetPassword,
  onToggleActive,
  onViewGrants,
}: SystemUsersPageProps) {
  return (
    <div className="system-page">
      <header className="system-page-heading"><div><span>ACCOUNT CONTROL</span><h1>用户管理</h1></div></header>
      <div className="system-user-toolbar">
        <p>{users === null ? '等待用户管理 API；不会用假数据模拟创建成功。' : `共 ${users.length} 个账号，不提供硬删除。`}</p>
        <button disabled={!onCreate} onClick={onCreate}>创建 EVENT_ADMIN</button>
      </div>
      {createFormOpen && (
        <CreateEventAdminForm
          onCancel={onCancelCreate}
          onSubmit={onSubmitCreate}
          submitting={createFormSubmitting}
        />
      )}
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
