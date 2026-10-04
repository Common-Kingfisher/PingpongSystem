import { useEffect, useState } from 'react'
import { Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
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
import { ApiError, api } from './api'
import type { Tournament } from './api'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { RequireAuth } from './auth/AuthGuards'
import AdminLayout from './layouts/AdminLayout'
import type { AdminEventOption } from './layouts/AdminLayout'
import LoginPage, { LoginFormValues, LoginPageError } from './pages/LoginPage'
import ChangePasswordPage from './pages/ChangePasswordPage'

function roleLabel(systemRole: 'SYSTEM_ADMIN' | 'EVENT_ADMIN'): string {
  return systemRole === 'SYSTEM_ADMIN' ? '系统管理员' : '赛事管理员'
}

function safeNextPath(next: string | null): string {
  if (!next) return '/'
  return next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/'
}

function LoginRoute() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [error, setError] = useState<LoginPageError>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (values: LoginFormValues) => {
    setSubmitting(true)
    setError(null)
    try {
      await auth.login(values)
      navigate(safeNextPath(params.get('next')), { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 401 ? 'invalid_credentials' : 'network')
    } finally {
      setSubmitting(false)
    }
  }

  return <LoginPage error={error} onSubmit={submit} submitting={submitting} />
}

function AdminShell({ children }: { children: React.ReactNode }) {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const urlTid = new URLSearchParams(location.search).get('tid')
  const parsedUrlTid = urlTid && /^\d+$/.test(urlTid) ? Number(urlTid) : null
  const tid = parsedUrlTid ?? getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [manageableEvents, setManageableEvents] = useState<AdminEventOption[]>([])
  useEffect(() => {
    if (tid === null) { setTournament(null); return }
    let active = true
    api.getTournament(tid).then((tournament) => {
      if (active) setTournament(tournament)
    }).catch(() => { if (active) setTournament(null) })
    return () => { active = false }
  }, [tid, location.key])

  useEffect(() => {
    if (auth.status !== 'authenticated' || auth.user === null) return
    let active = true
    api.listTournaments()
      .then((tournaments) => {
        if (active) {
          setManageableEvents(tournaments.map((tournament) => ({ id: tournament.id, name: tournament.name })))
        }
      })
      .catch(() => { if (active) setManageableEvents([]) })
    return () => { active = false }
  }, [auth.status, auth.user])

  if (auth.status !== 'authenticated' || auth.user === null) {
    return <RequireAuth>{children}</RequireAuth>
  }

  const currentUserLabel = auth.user.display_name.trim() || auth.user.username
  const logout = async () => {
    try {
      await auth.logout()
      navigate('/login', { replace: true })
    } catch {
      // AdminLayout 自身没有错误容器；保持当前页，避免在网络失败时假装已退出。
    }
  }

  return (
    <AdminLayout
      currentUserLabel={currentUserLabel}
      currentUserRoleLabel={roleLabel(auth.user.system_role)}
      manageableEvents={manageableEvents}
      onChangePassword={() => navigate(tid === null ? '/change-password' : `/change-password?tid=${tid}`)}
      onLogout={logout}
      tournamentName={tournament?.name}
      eventType={tournament?.event_type}
    >
      {children}
    </AdminLayout>
  )
}

function AuthenticatedAppRoutes() {
  const { pathname } = useLocation()

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

  if (pathname === '/login') {
    return <LoginRoute />
  }

  if (pathname === '/change-password') {
    return (
      <RequireAuth>
        <ChangePasswordPage />
      </RequireAuth>
    )
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
          {/* C-D5 Phase 3：管理端赛程默认展示"实时赛程"。
              Public 端（/public/t/:tid/schedule）由 PublicRoutes 复用同一组件且不传 variant，
              因此继续拿到既有的 public"选手赛程"行为，D 轨不受影响。 */}
          <Route path="/schedule" element={<SchedulePage variant="admin" />} />
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

export default function App() {
  const { pathname } = useLocation()
  // V0.3 Public 端（D 轨）：`/public/t/:tid/...` 使用独立的 PublicLayout。
  // 这里刻意提前返回、不渲染管理端 App Shell —— 公共页面不得出现管理导航与管理员控件。
  // 该分支只做入口分流，Public 路由本身全部收敛在 PublicRoutes.tsx，避免与 A/C 轨争抢 App.tsx。
  if (pathname === '/public' || pathname.startsWith('/public/')) {
    return <PublicRoutes />
  }

  // 认证状态属于应用级状态；SPA 内从登录页跳回管理页时必须保留同一个 Provider。
  return (
    <AuthProvider>
      <AuthenticatedAppRoutes />
    </AuthProvider>
  )
}
