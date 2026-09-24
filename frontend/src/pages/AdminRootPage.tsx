import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Tournament } from '../api'
import { getActiveTournamentId, parseTournamentId, setActiveTournamentId } from '../activeTournament'
import AdminDashboardPage from './AdminDashboardPage'
import HomePage from './HomePage'

export default function AdminRootPage() {
  const [params] = useSearchParams()
  const urlTournamentId = parseTournamentId(params.get('tid'))
  const tournamentId = urlTournamentId ?? getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [loading, setLoading] = useState(tournamentId !== null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const retry = useCallback(() => setReloadKey((value) => value + 1), [])

  useEffect(() => {
    let active = true
    if (tournamentId === null) {
      setTournament(null)
      setLoading(false)
      setError(null)
      return () => { active = false }
    }

    setLoading(true)
    setError(null)
    api.getTournament(tournamentId).then((result) => {
      if (!active) return
      setActiveTournamentId(result.id)
      setTournament(result)
      setLoading(false)
    }).catch((reason: unknown) => {
      if (!active) return
      setLoading(false)
      setTournament(null)
      if (reason instanceof ApiError && reason.status === 404) {
        setActiveTournamentId(null)
        setError(null)
        return
      }
      setError(reason instanceof ApiError ? reason.message : '当前赛事加载失败')
    })
    return () => { active = false }
  }, [reloadKey, tournamentId])

  if (loading) {
    return <section className="admin-dashboard admin-dashboard--empty"><h1>正在进入赛事…</h1></section>
  }

  if (error) {
    return (
      <section className="admin-dashboard admin-dashboard--empty" role="alert">
        <span className="admin-dashboard-kicker">赛事入口</span>
        <h1>无法读取当前赛事</h1>
        <p>{error}</p>
        <button className="btn primary" onClick={retry} type="button">重试</button>
      </section>
    )
  }

  if (!tournament) return <HomePage />

  if (tournament.event_type === 'TEAM') {
    return (
      <section className="admin-dashboard admin-dashboard--empty admin-team-overview">
        <span className="admin-dashboard-kicker">团体赛事入口</span>
        <h1>{tournament.name}</h1>
        <p>团体赛使用独立的队伍、对抗与单盘运行链路；这里不会用个人赛 Match 数据伪装团体赛总览。</p>
        <div className="admin-action-links">
          <Link to={`/team-roster?tid=${tournament.id}`}>进入队伍与名单</Link>
          <Link to={`/team-ties?tid=${tournament.id}`}>进入团体对抗</Link>
          <Link to={`/team-rankings?tid=${tournament.id}`}>查看团体排名</Link>
        </div>
      </section>
    )
  }

  return <AdminDashboardPage key={tournament.id} tournamentId={tournament.id} />
}
