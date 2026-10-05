import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useRef,
  type ReactNode,
} from 'react'
import { api } from '../api'
import type { AuthChangePasswordRequest, AuthUser } from '../api'

export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'unauthenticated'

interface AuthContextValue {
  status: AuthStatus
  user: AuthUser | null
  login: (values: { username: string; password: string }) => Promise<AuthUser>
  logout: () => Promise<void>
  changePassword: (values: { current_password: string; new_password: string }) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const sessionRequestIdRef = useRef(0)
  const [status, setStatus] = useState<AuthStatus>('idle')
  const [user, setUser] = useState<AuthUser | null>(null)

  useEffect(() => {
    let active = true
    const requestId = ++sessionRequestIdRef.current
    setStatus('loading')
    api.me()
      .then((result) => {
        if (!active || sessionRequestIdRef.current !== requestId) return
        if (!result.user) throw new Error('invalid auth response')
        setUser(result.user)
        setStatus('authenticated')
      })
      .catch(() => {
        if (!active || sessionRequestIdRef.current !== requestId) return
        setUser(null)
        setStatus('unauthenticated')
      })
    return () => { active = false }
  }, [])

  const login = useCallback(async (values: { username: string; password: string }) => {
    const result = await api.login({ ...values, mode: 'browser' })
    // A /me probe that started before login must not overwrite the fresh session.
    sessionRequestIdRef.current += 1
    setUser(result.user)
    setStatus('authenticated')
    return result.user
  }, [])

  const clearUser = useCallback(() => {
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    clearUser()
  }, [clearUser])

  const changePassword = useCallback(async (values: AuthChangePasswordRequest) => {
    await api.changePassword(values)
    clearUser()
  }, [clearUser])

  const value = useMemo(() => ({
    status,
    user,
    login,
    logout,
    changePassword,
  }), [status, user, login, logout, changePassword])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === null) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
