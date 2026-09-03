import { useEffect, useMemo, useState } from 'react'
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
  const [showDraw, setShowDraw] = useState(false)
  const [motionDone, setMotionDone] = useState(false)

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

  const confirmAndDraw = async () => {
    setBusy(true)
    setError(null)
    try {
      const confirmed = await api.confirmRoster(tournament.id)
      setEntries(confirmed.entries)
      await api.autoGroup(tournament.id)
      setShowDraw(true)
      window.setTimeout(() => setMotionDone(true), 2600)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '确认名单失败')
    } finally {
      setBusy(false)
    }
  }

  const closeDraw = async () => {
    setShowDraw(false)
    setMotionDone(false)
    await onComplete()
  }

  if (tournament.stage !== 'REGISTRATION') return null

  return (
    <>
      <section className="card launch-card">
        <div className="section-heading">
          <div>
            <span className="eyebrow">ROSTER LOCK</span>
            <h3>{tournament.event_type === 'DOUBLES' ? '先组成搭档，再确认名单' : '确认名单，开始抽签'}</h3>
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
          <button className="btn primary launch-button" onClick={confirmAndDraw} disabled={!ready || busy}>
            {busy ? '正在确认…' : '确认名单并开始抽签'}
          </button>
        </div>
        {error && <p className="status-error">{error}</p>}
      </section>

      {showDraw && (
        <div className="draw-overlay" role="dialog" aria-modal="true" aria-label="抽签结果动画">
          <button className="draw-skip" onClick={closeDraw}>跳过动画</button>
          <div className="draw-orbit" aria-hidden="true"><i /></div>
          <span className="draw-kicker">DRAWING CEREMONY</span>
          <h2>{tournament.name}</h2>
          <p>{tournament.event_type === 'DOUBLES' ? '双打组合正在进入签位' : '参赛选手正在进入签位'}</p>
          <div className="flying-names">
            {(entries.length ? entries.map((entry) => entry.display_name) : players.map((player) => player.name)).map((name, index) => (
              <div
                key={`${name}-${index}`}
                className="flying-name"
                style={{ '--fly-index': index, '--fly-group': index % tournament.group_count } as React.CSSProperties}
              >
                <small>{String.fromCharCode(65 + (index % tournament.group_count))}组</small>
                <strong>{name}</strong>
              </div>
            ))}
          </div>
          <button className="btn draw-confirm" onClick={closeDraw} disabled={!motionDone}>
            {motionDone ? '查看分组结果' : '正在生成签位…'}
          </button>
        </div>
      )}
    </>
  )
}
