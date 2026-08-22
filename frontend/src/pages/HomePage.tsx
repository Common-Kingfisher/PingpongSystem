import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, Tournament } from '../api'

interface FormState {
  name: string
  date: string
  table_count: number
  group_count: number
  qualify_per_group: number
}

const emptyForm: FormState = {
  name: '',
  date: new Date().toISOString().slice(0, 10),
  table_count: 6,
  group_count: 4,
  qualify_per_group: 2,
}

export default function HomePage() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'ok' | 'error'>('checking')
  const [tournaments, setTournaments] = useState<Tournament[]>([])
  const [form, setForm] = useState<FormState>(emptyForm)
  const [error, setError] = useState<string | null>(null)

  const loadTournaments = useCallback(() => {
    api
      .listTournaments()
      .then(setTournaments)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : '加载赛事失败'))
  }, [])

  useEffect(() => {
    api
      .health()
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('error'))
    loadTournaments()
  }, [loadTournaments])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await api.createTournament(form)
      setForm(emptyForm)
      loadTournaments()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建赛事失败')
    }
  }

  return (
    <div className="page">
      <div className="card">
        <h2>创建赛事</h2>
        <p className="muted">
          后端连接状态：
          {backendStatus === 'checking' && '检测中…'}
          {backendStatus === 'ok' && <span className="status-ok">正常 ✅</span>}
          {backendStatus === 'error' && (
            <span className="status-error">失败 ❌（请确认后端已启动）</span>
          )}
        </p>
        <form className="form-grid" onSubmit={submit}>
          <label>
            赛事名称
            <input
              type="text"
              required
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="如：2025 秋季乒乓球赛"
            />
          </label>
          <label>
            比赛日期
            <input
              type="date"
              required
              value={form.date}
              onChange={(e) => set('date', e.target.value)}
            />
          </label>
          <label>
            球台数量 (4~8)
            <input
              type="number"
              min={4}
              max={8}
              required
              value={form.table_count}
              onChange={(e) => set('table_count', Number(e.target.value))}
            />
          </label>
          <label>
            小组数量 (1~8)
            <input
              type="number"
              min={1}
              max={8}
              required
              value={form.group_count}
              onChange={(e) => set('group_count', Number(e.target.value))}
            />
          </label>
          <label>
            每组晋级人数
            <input
              type="number"
              min={1}
              required
              value={form.qualify_per_group}
              onChange={(e) => set('qualify_per_group', Number(e.target.value))}
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn primary">
              创建赛事
            </button>
          </div>
        </form>
        {error && <p className="status-error">{error}</p>}
      </div>

      <div className="card">
        <h2>赛事列表</h2>
        {tournaments.length === 0 && <p className="muted">还没有赛事，请先创建。</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>日期</th>
              <th>球台</th>
              <th>小组</th>
              <th>晋级/组</th>
              <th>阶段</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tournaments.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.name}</td>
                <td>{t.date}</td>
                <td>{t.table_count}</td>
                <td>{t.group_count}</td>
                <td>{t.qualify_per_group}</td>
                <td>
                  <span className="badge">{t.stage}</span>
                </td>
                <td>
                  <Link className="btn small" to={`/players?tid=${t.id}`}>
                    选手与分组 →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
