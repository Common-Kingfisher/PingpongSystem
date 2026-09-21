import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

/**
 * 在线报名页。
 *
 * ⚠️ legacy（V0.2 行为）：本页直接调用 `api.addPlayer` 创建**正式 Player**，
 * 与 V0.3 冻结的 `Registration(pending) → EVENT_ADMIN 确认入赛` 契约不一致。
 *
 * D 轨 Day 2 只在 Public 路由下复用本页作为兼容入口，并显式标记 legacy；
 * 正式报名契约（Registration schema/API、`registration_enabled`）由 A 轨提供后再切换。
 */
export default function RegisterPage({ tid: tidProp }: { tid?: number } = {}) {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  // tid 优先级：显式 prop（Public 路由的 path param）> ?tid= > localStorage（V0.2 兼容）
  const tid = tidProp ?? (urlTid ? Number(urlTid) : getActiveTournamentId())

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [name, setName] = useState('')
  const [college, setCollege] = useState('')
  const [ratingPoints, setRatingPoints] = useState(1000)
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
      await api.addPlayer(tid, { name, college: college || null, rating_points: ratingPoints })
      setMessage({ ok: true, text: `报名成功！${name} 已加入「${tournament?.name ?? '本场赛事'}」。` })
      setName('')
      setCollege('')
      setRatingPoints(1000)
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
            运动员积分
            <input
              type="number"
              min={0}
              max={99999}
              value={ratingPoints}
              onChange={(e) => setRatingPoints(Number(e.target.value))}
              placeholder="如：1200"
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
