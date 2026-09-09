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
import PreflightPage from './pages/PreflightPage'
import { getActiveTournamentId } from './activeTournament'

function AppNav() {
  // 订阅路由变化：每次导航都重新读取当前赛事 id，保证顶部链接始终携带它
  useLocation()
  const tid = getActiveTournamentId()
  const qs = tid !== null ? `?tid=${tid}` : ''
  const navItems = [
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
        </Routes>
      </main>
    </div>
  )
}
