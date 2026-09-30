import { useEffect, useState } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import AdminRootPage from './pages/AdminRootPage'
import PlayersPage from './pages/PlayersPage'
import DrawPage from './pages/DrawPage'
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
import TournamentSettingsPage from './pages/TournamentSettingsPage'
import TeamRosterPage from './pages/TeamRosterPage'
import TeamRankingsPage from './pages/TeamRankingsPage'
import TeamQualificationPage from './pages/TeamQualificationPage'
import TeamKnockoutPage from './pages/TeamKnockoutPage'
import PublicRoutes from './PublicRoutes'
import MobileScoreRoutes, { isMobileScoreRoutePath } from './MobileScoreRoutes'
import { getActiveTournamentId } from './activeTournament'
import { api } from './api'
import type { Tournament } from './api'
import AdminLayout from './layouts/AdminLayout'

function AdminShell({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const urlTid = new URLSearchParams(location.search).get('tid')
  const parsedUrlTid = urlTid && /^\d+$/.test(urlTid) ? Number(urlTid) : null
  const tid = parsedUrlTid ?? getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  useEffect(() => {
    if (tid === null) { setTournament(null); return }
    let active = true
    api.getTournament(tid).then((tournament) => {
      if (active) setTournament(tournament)
    }).catch(() => { if (active) setTournament(null) })
    return () => { active = false }
  }, [tid, location.key])
  return <AdminLayout tournamentName={tournament?.name} eventType={tournament?.event_type}>{children}</AdminLayout>
}

export default function App() {
  const { pathname } = useLocation()
  // V0.3 Public 端（D 轨）：`/public/t/:tid/...` 使用独立的 PublicLayout。
  // 这里刻意提前返回、不渲染管理端 App Shell —— 公共页面不得出现管理导航与管理员控件。
  // 该分支只做入口分流，Public 路由本身全部收敛在 PublicRoutes.tsx，避免与 A/C 轨争抢 App.tsx。
  if (pathname === '/public' || pathname.startsWith('/public/')) {
    return <PublicRoutes />
  }

  // V0.3 手机录分（D 轨 Day 3）：**只**在完整匹配 D 轨拥有的那一条精确 path 时才进入
  // MobileScoreRoutes —— `/admin/t/:tid/matches/:matchId/score`。
  //
  // ⚠️ Route ownership：`/admin` 命名空间的总体所有权属于 A/C 轨（AdminLayout / Login /
  // AccessState / AuthGuard / RequireTournamentAccess 及其他管理端 route）。
  // 这里刻意**不用** `pathname.startsWith('/admin/')`，否则 A/C 后续接入的
  // `/admin/events`、`/admin/login`、`/admin/t/:tid/settings` 都会被 D 轨截断。
  //
  // 判定与 D 轨 route 表共用同一个 `isMobileScoreRoutePath()`（内部是 react-router 的
  // `matchPath(..., { end: true })` 完整匹配），因此不会出现“入口判断与 route 声明漂移”。
  if (isMobileScoreRoutePath(pathname)) {
    return <MobileScoreRoutes />
  }

  return (
    <AdminShell>
        <Routes>
          <Route path="/" element={<AdminRootPage />} />
          <Route path="/players" element={<PlayersPage />} />
          <Route path="/draw" element={<DrawPage />} />
          <Route path="/settings" element={<TournamentSettingsPage />} />
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
    </AdminShell>
  )
}
