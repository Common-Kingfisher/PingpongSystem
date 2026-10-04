import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'
import './AccessStatePage.css'

export default function ChangePasswordPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await auth.changePassword({ current_password: currentPassword, new_password: newPassword })
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改密码失败，请检查网络后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="access-state-page">
      <section className="access-state-card">
        <span className="access-state-code">修改密码</span>
        <h1>设置新密码</h1>
        <p>密码修改成功后，当前会话会被后端撤销，需要重新登录。</p>
        {error && <div className="login-error" role="alert">{error}</div>}
        <form onSubmit={submit}>
          <label>
            <span>当前密码</span>
            <input
              autoComplete="current-password"
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              type="password"
              value={currentPassword}
            />
          </label>
          <label>
            <span>新密码</span>
            <input
              autoComplete="new-password"
              minLength={12}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              type="password"
              value={newPassword}
            />
          </label>
          <label>
            <span>确认新密码</span>
            <input
              autoComplete="new-password"
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              type="password"
              value={confirmPassword}
            />
          </label>
          <button disabled={submitting} type="submit">
            {submitting ? '正在修改…' : '修改密码'}
          </button>
        </form>
      </section>
    </main>
  )
}
