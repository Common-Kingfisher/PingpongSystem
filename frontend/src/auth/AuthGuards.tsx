import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from './AuthContext'
import TournamentUnavailablePage from '../pages/TournamentUnavailablePage'

export function AuthGateLoading() {
  return (
    <main className="access-state-page">
      <p role="status">正在检查登录状态…</p>
    </main>
  )
}

function buildLoginTarget(pathname: string, search: string): string {
  const next = `${pathname}${search}`
  return `/login?next=${encodeURIComponent(next)}`
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const { pathname, search } = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    if (auth.status === 'unauthenticated' && auth.user === null) {
      navigate(buildLoginTarget(pathname, search), { replace: true })
    }
  }, [auth.status, auth.user, navigate, pathname, search])

  if (auth.status === 'idle' || auth.status === 'loading') return <AuthGateLoading />
  if (!auth.user) return null
  return <>{children}</>
}

type TournamentAccess = 'loading' | 'allowed' | 'unavailable'

export function RequireTournamentAccess({
  tid,
  children,
}: {
  tid: number
  children: ReactNode
}) {
  const auth = useAuth()
  const { pathname, search } = useLocation()
  const [access, setAccess] = useState<TournamentAccess>('loading')

  useEffect(() => {
    if (auth.status !== 'authenticated' || !auth.user) return
    let active = true
    setAccess('loading')
    api.listTournaments()
      .then((tournaments) => {
        if (!active) return
        setAccess(tournaments.some((tournament) => tournament.id === tid) ? 'allowed' : 'unavailable')
      })
      .catch(() => {
        if (!active) return
        setAccess('unavailable')
      })
    return () => { active = false }
  }, [auth.status, auth.user, tid])

  if (auth.status === 'idle' || auth.status === 'loading') return <AuthGateLoading />
  if (!auth.user) return <Navigate replace to={buildLoginTarget(pathname, search)} />
  if (access === 'loading') return <AuthGateLoading />
  if (access === 'unavailable') return <TournamentUnavailablePage />
  return <>{children}</>
}
