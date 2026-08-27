import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

export default function RegisterPage() {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  const tid = urlTid ? Number(urlTid) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [name, setName] = useState('')
  const [college, setCollege] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    setTournament(await api.getTournament(tid))
  }, [tid])

  useEffect(() => {
    load().catch(() => {})
  }, [load])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (tid === null) {
      setMessage({ ok: false, text: '尚未选择赛事，请先从赛事首页进入报名入口。' })
      return
    }
    setMessage(null)
    setBusy(true)
    try {
      await api.addPlayer(tid, { name, college: college || null })
      setMessage({ ok: true, text: `报名成功！${name} 已加入「${tournament?.name ?? '本场赛事'}」。` })
      setName('')
      setCollege('')
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : '报名失败' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 在线报名
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        <p className="muted">
          填写姓名即可报名参赛（学院/单位选填）。报名后请管理员在「选手与分组」中完成种子设置与分组。
        </p>
        <form className="form-grid" onSubmit={submit} style={{ maxWidth: 520 }}>
          <label>
            姓名（必填）
            <input
              type="text"
              required
              maxLength={50}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="请输入姓名"
            />
          </label>
          <label>
            学院/单位（选填）
            <input
              type="text"
              maxLength={100}
              value={college}
              onChange={(e) => setCollege(e.target.value)}
              placeholder="如：计算机学院"
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn primary" disabled={busy}>
              {busy ? '提交中…' : '提交报名'}
            </button>
          </div>
        </form>
        {message && (
          <p className={message.ok ? 'status-ok' : 'status-error'}>{message.text}</p>
        )}
      </div>
    </div>
  )
}
