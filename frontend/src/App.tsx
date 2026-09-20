import { useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import HomePage from './pages/HomePage'
import PlayersPage from './pages/PlayersPage'
import ConsolePage from './pages/ConsolePage'
import RankingsPage from './pages/RankingsPage'
import KnockoutPage from './pages/KnockoutPage'
import SchedulePage from './pages/SchedulePage'
import BigScreenPage from './pages/BigScreenPage'
import RegisterPage from './pages/RegisterPage'
import ChampionJourneyPage from './pages/ChampionJourneyPage'
import OrderBookPage from './pages/OrderBookPage'
import MatchPrintPage from './pages/MatchPrintPage'
import TeamTiePage from './pages/TeamTiePage'
import TeamTiesPage from './pages/TeamTiesPage'
import PreflightPage from './pages/PreflightPage'
import TeamRosterPage from './pages/TeamRosterPage'
import TeamRankingsPage from './pages/TeamRankingsPage'
import TeamQualificationPage from './pages/TeamQualificationPage'
import TeamKnockoutPage from './pages/TeamKnockoutPage'
import { getActiveTournamentId } from './activeTournament'
import { api } from './api'

function AppNav() {
  // 订阅路由变化：每次导航都重新读取当前赛事 id，保证顶部链接始终携带它
  const location = useLocation()
  const urlTid = new URLSearchParams(location.search).get('tid')
  const parsedUrlTid = urlTid && /^\d+$/.test(urlTid) ? Number(urlTid) : null
  const tid = parsedUrlTid ?? getActiveTournamentId()
  const [isTeamEvent, setIsTeamEvent] = useState<boolean | null>(tid === null ? false : null)
  useEffect(() => {
    if (tid === null) { setIsTeamEvent(false); return }
    setIsTeamEvent(null)
    let active = true
    api.getTournament(tid).then((tournament) => {
      if (active) setIsTeamEvent(tournament.event_type === 'TEAM')
    }).catch(() => { if (active) setIsTeamEvent(false) })
    return () => { active = false }
  }, [tid, location.key])
  const qs = tid !== null ? `?tid=${tid}` : ''
  const standardNavItems = [
    { to: '/', label: '赛事首页', end: true },
    { to: `/players${qs}`, label: '选手与分组' },
    { to: `/preflight${qs}`, label: '赛前检查' },
    { to: `/console${qs}`, label: '比赛控制台' },
    { to: `/rankings${qs}`, label: '小组排名' },
    { to: `/knockout${qs}`, label: '淘汰赛' },
    { to: `/journey${qs}`, label: '冠军之路' },
    { to: `/schedule${qs}`, label: '选手赛程' },
    { to: `/bigscreen${qs}`, label: '赛事大屏' },
    { to: `/register${qs}`, label: '在线报名' },
    { to: `/orderbook${qs}`, label: '秩序册' },
  ]
  const teamNavItems = [
    { to: '/', label: '赛事首页', end: true },
    { to: `/team-roster${qs}`, label: '队伍与名单' },
    { to: `/team-ties${qs}`, label: '团体对抗' },
    { to: `/team-rankings${qs}`, label: '团体排名' },
    { to: `/team-qualification${qs}`, label: '晋级确认' },
    { to: `/team-knockout${qs}`, label: '团体淘汰赛' },
  ]
  const navItems = isTeamEvent === null ? [{ to: '/', label: '赛事首页', end: true }] : isTeamEvent ? teamNavItems : standardNavItems
  return (
    <nav>
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

export default function App() {
  const { pathname } = useLocation()
  const fullwidth = ['/bigscreen', '/journey', '/orderbook'].includes(pathname)
  return (
    <div className="app">
      <header className="app-header">
        <Link className="app-title" to="/"><span className="brand-mark">TT</span><span>乒乓赛事控制台<small>TOURNAMENT OPS</small></span></Link>
        <AppNav />
      </header>
      <main className={fullwidth ? 'app-main fullwidth' : 'app-main'}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/players" element={<PlayersPage />} />
          <Route path="/preflight" element={<PreflightPage />} />
          <Route path="/console" element={<ConsolePage />} />
          <Route path="/rankings" element={<RankingsPage />} />
          <Route path="/knockout" element={<KnockoutPage />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/bigscreen" element={<BigScreenPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/journey" element={<ChampionJourneyPage />} />
          <Route path="/orderbook" element={<OrderBookPage />} />
          <Route path="/match-print" element={<MatchPrintPage />} />
          <Route path="/team-tie" element={<TeamTiePage />} />
          <Route path="/team-ties" element={<TeamTiesPage />} />
          <Route path="/team-roster" element={<TeamRosterPage />} />
          <Route path="/team-rankings" element={<TeamRankingsPage />} />
          <Route path="/team-qualification" element={<TeamQualificationPage />} />
          <Route path="/team-knockout" element={<TeamKnockoutPage />} />
        </Routes>
      </main>
    </div>
  )
}
