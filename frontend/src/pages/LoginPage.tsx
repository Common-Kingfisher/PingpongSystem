import { FormEvent, useState } from 'react'
import './LoginPage.css'

export interface LoginFormValues {
  username: string
  password: string
}

export type LoginPageError = 'invalid_credentials' | 'network' | null

export interface LoginPageProps {
  error?: LoginPageError
  submitting?: boolean
  onSubmit?: (values: LoginFormValues) => void | Promise<void>
}

export default function LoginPage({ error = null, submitting = false, onSubmit }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!onSubmit || submitting) return
    void onSubmit({ username: username.trim(), password })
  }

  const errorMessage = error === 'invalid_credentials'
    ? '用户名或密码错误'
    : error === 'network'
      ? '无法连接服务器，请检查服务器或本地网络'
      : null

  return (
    <main className="login-page">
      <section className="login-court" aria-hidden="true">
        <div className="login-court-copy">
          <span>TOURNAMENT CONTROL</span>
          <strong>每一分，都有清晰的去向。</strong>
        </div>
        <div className="login-court-table">
          <span className="login-court-line" />
          <i />
        </div>
        <div className="login-score-track">
          <span>READY</span><b>01</b><i>—</i><b>11</b>
        </div>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <header>
            <span className="login-mark">TT</span>
            <div>
              <strong>PingpongSystem</strong>
              <small>赛事管理系统</small>
            </div>
          </header>
          <div className="login-heading">
            <span>管理端登录</span>
            <h1>回到比赛现场</h1>
            <p>使用赛事管理员或系统管理员账号继续。</p>
          </div>

          {errorMessage && <div className="login-error" role="alert">{errorMessage}</div>}

          <label>
            <span>用户名</span>
            <input
              autoComplete="username"
              autoFocus
              onChange={(event) => setUsername(event.target.value)}
              required
              value={username}
            />
          </label>
          <label>
            <span>密码</span>
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button disabled={!onSubmit || submitting} type="submit">
            {submitting ? '正在登录…' : onSubmit ? '登录' : '等待认证服务接入'}
          </button>
          <p className="login-help">忘记密码请联系系统管理员重置。</p>
        </form>
      </section>
    </main>
  )
}
