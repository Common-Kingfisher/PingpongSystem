import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, Entry, Player, Tournament } from '../api'

export default function RosterLaunch({
  tournament,
  players,
  onComplete,
}: {
  tournament: Tournament
  players: Player[]
  onComplete: () => Promise<void>
}) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [unpaired, setUnpaired] = useState<Player[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)

  useEffect(() => {
    api.listEntries(tournament.id).then(setEntries).catch(() => setEntries([]))
  }, [tournament.id])

  const ready = useMemo(() => {
    if (tournament.event_type === 'SINGLES') return players.length >= 2
    const pairedPlayers = entries.reduce((total, entry) => total + entry.members.length, 0)
    return entries.length >= 2 && pairedPlayers === players.length && unpaired.length === 0 && entries.every((entry) => entry.members.length === 2)
  }, [entries, players.length, tournament.event_type, unpaired.length])

  const pair = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.pairDoubles(tournament.id)
      setEntries(result.entries)
      setUnpaired(result.unpaired_players)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '生成双打组合失败')
    } finally {
      setBusy(false)
    }
  }

  const confirmRoster = async () => {
    setBusy(true)
    setError(null)
    try {
      const confirmed = await api.confirmRoster(tournament.id)
      setEntries(confirmed.entries)
      setConfirmed(true)
      await onComplete()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '确认名单失败')
    } finally {
      setBusy(false)
    }
  }

  if (tournament.stage !== 'REGISTRATION') return null

  // 团体赛使用独立的队伍名单工作表；不走单打/双打的确认名单后自动抽签流程。
  if (tournament.event_type === 'TEAM') {
    return (
      <section className="card launch-card">
        <div className="section-heading">
          <div>
            <span className="eyebrow">TEAM EVENT</span>
            <h3>团体赛的名单由队伍组成</h3>
          </div>
          <span className="readiness ready">可编辑</span>
        </div>
        <p className="muted">
          队伍即参赛实体，队员即队伍成员。请先在工作表中完成队伍录入、调换、排序和名单确认；
          确认后名单冻结，仍可随时预览。
        </p>
        <div className="button-row"><Link className="btn primary" to={`/team-roster?tid=${tournament.id}`}>进入队伍与名单 →</Link></div>
      </section>
    )
  }

  return (
    <>
      <section className="card launch-card">
        <div className="section-heading">
          <div>
            <span className="eyebrow">ROSTER LOCK</span>
            <h3>{tournament.event_type === 'DOUBLES' ? '先组成搭档，再确认名单' : '确认正式参赛名单'}</h3>
          </div>
          <span className={`readiness ${ready ? 'ready' : ''}`}>{ready ? '可以确认' : '等待名单完整'}</span>
        </div>

        {tournament.event_type === 'DOUBLES' && (
          <>
            <p className="muted">系统优先在相近积分运动员中随机配对，并尽量回避同单位。确认前可以反复重排。</p>
            <div className="pair-grid">
              {entries.map((entry, index) => (
                <div className="pair-card" key={entry.id} style={{ '--pair-index': index } as React.CSSProperties}>
                  <span>组合 {String(index + 1).padStart(2, '0')}</span>
                  <strong>{entry.display_name}</strong>
                  <small>组合积分 {entry.rating_points}</small>
                </div>
              ))}
              {entries.length === 0 && <div className="empty-invite">录入运动员积分后，生成相近水平搭档。</div>}
            </div>
            {unpaired.length > 0 && <p className="status-error">待处理：{unpaired.map((p) => p.name).join('、')} 尚未配对。</p>}
            <button className="btn" onClick={pair} disabled={busy || players.length < 4}>
              {entries.length ? '重新随机配对' : '生成双打组合'}
            </button>
          </>
        )}

        <div className="launch-actions">
          <div>
            <strong>{tournament.event_type === 'DOUBLES' ? entries.length : players.length}</strong>
            <span>{tournament.event_type === 'DOUBLES' ? ' 组参赛组合' : ' 名参赛运动员'}</span>
          </div>
          <button className="btn primary launch-button" onClick={confirmRoster} disabled={!ready || busy}>
            {busy ? '正在确认…' : '确认参赛名单'}
          </button>
        </div>
        {confirmed && <p className="status-ok">名单已确认。下一步请前往<Link to={`/draw?tid=${tournament.id}`}>抽签与编排</Link>。</p>}
        {error && <p className="status-error">{error}</p>}
      </section>
    </>
  )
}
