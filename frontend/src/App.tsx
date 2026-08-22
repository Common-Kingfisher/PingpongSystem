import { NavLink, Route, Routes } from 'react-router-dom'
import HomePage from './pages/HomePage'
import PlayersPage from './pages/PlayersPage'
import ConsolePage from './pages/ConsolePage'
import RankingsPage from './pages/RankingsPage'
import KnockoutPage from './pages/KnockoutPage'

const navItems = [
  { to: '/', label: '赛事首页', end: true },
  { to: '/players', label: '选手与分组' },
  { to: '/console', label: '比赛控制台' },
  { to: '/rankings', label: '小组排名' },
  { to: '/knockout', label: '淘汰赛' },
]

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">🏓 乒乓球赛事编排 Demo</span>
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
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/players" element={<PlayersPage />} />
          <Route path="/console" element={<ConsolePage />} />
          <Route path="/rankings" element={<RankingsPage />} />
          <Route path="/knockout" element={<KnockoutPage />} />
        </Routes>
      </main>
    </div>
  )
}
