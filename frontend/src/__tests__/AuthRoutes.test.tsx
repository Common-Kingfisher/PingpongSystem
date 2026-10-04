/// <reference types="vitest/globals" />
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { AuthUser, Tournament } from '../api'

const TID = 12

const tournament: Tournament = {
  id: TID, name: '认证路由测试赛', date: '2026-10-04', table_count: 4, group_count: 2,
  qualify_per_group: 2, stage: 'REGISTRATION', created_at: '2026-10-04T00:00:00Z',
  event_type: 'SINGLES', bronze_mode: 'JOINT_BRONZE', placement_mode: 'OFF',
  games_to_win: 3, points_to_win: 11, roster_confirmed: false, operation_mode: 'LIVE',
  registration_enabled: true, format_code: 'GROUP_KNOCKOUT', rule_config: {}, rule_version: 1,
}

const user: AuthUser = {
  id: 1,
  username: 'event-admin',
  display_name: '王裁判',
  system_role: 'EVENT_ADMIN',
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let authMeAuthenticated = false
let accessibleTournamentId = TID
let loginStatus = 200
let requestedPaths: string[] = []
let loginPosts: Record<string, unknown>[] = []
let logoutCalls = 0
let changePasswordPosts: Record<string, unknown>[] = []

function installFetchStub() {
  requestedPaths = []
  loginPosts = []
  logoutCalls = 0
  changePasswordPosts = []

  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    const method = init?.method ?? 'GET'
    requestedPaths.push(`${method} ${path}`)

    if (path === '/api/v1/auth/me') {
      if (!authMeAuthenticated) return Promise.resolve(jsonResponse({
        detail: { code: 'AUTH_REQUIRED', message: '请先登录' },
      }, 401))
      return Promise.resolve(jsonResponse({ user, tournament_access_count: 1 }))
    }
    if (path === '/api/v1/auth/login') {
      loginPosts.push(JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>)
      if (loginStatus !== 200) return Promise.resolve(jsonResponse({
        detail: { code: 'AUTH_INVALID_CREDENTIALS', message: '用户名或密码错误' },
      }, loginStatus))
      return Promise.resolve(jsonResponse({
        access_token: null,
        token_type: null,
        expires_at: '2026-10-04T01:00:00Z',
        user,
      }))
    }
    if (path === '/api/v1/auth/logout') {
      logoutCalls += 1
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    if (path === '/api/v1/auth/change-password') {
      changePasswordPosts.push(JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>)
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    if (path === '/api/tournaments') {
      return Promise.resolve(jsonResponse([{ id: accessibleTournamentId, name: tournament.name }]))
    }
    if (path === `/api/tournaments/${TID}`) return Promise.resolve(jsonResponse(tournament))
    return Promise.resolve(jsonResponse([]))
  })
}

function LocationProbe() {
  const { pathname, search } = useLocation()
  return <div data-testid="location">{pathname}{search}</div>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LocationProbe />
      <App />
    </MemoryRouter>,
  )
}

async function submitLogin(username = 'event-admin', password = 'original-password-123') {
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: password } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
  })
}

beforeEach(() => {
  localStorage.clear()
  authMeAuthenticated = false
  accessibleTournamentId = TID
  loginStatus = 200
  installFetchStub()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('认证路由与 Auth Shell', () => {
  it('挂载 /login，browser 登录成功后跳回 next 并显示用户和角色', async () => {
    renderAt('/login?next=%2F')

    await submitLogin()
    await waitFor(() => expect(loginPosts).toHaveLength(1))

    await screen.findByText('王裁判')
    expect(await screen.findByText('赛事管理员')).toBeTruthy()
    expect(screen.getByTestId('location').textContent).toBe('/')
    expect(loginPosts).toEqual([{
      username: 'event-admin',
      password: 'original-password-123',
      mode: 'browser',
    }])
  })

  it('登录失败时展示凭据错误，不进入受保护页面', async () => {
    loginStatus = 401
    renderAt('/login')

    await submitLogin('event-admin', 'wrong-password')

    await screen.findByText('用户名或密码错误')
    expect(loginPosts).toHaveLength(1)
    expect(screen.getByTestId('location').textContent).toBe('/login')
  })

  it('未登录访问受保护页时进入 /login?next=...', async () => {
    renderAt('/players?tid=12')

    await screen.findByText('管理端登录')
    expect(screen.getByTestId('location').textContent).toBe('/login?next=%2Fplayers%3Ftid%3D12')
  })

  it('未登录访问手机录分时进入登录页，不渲染录分表单', async () => {
    renderAt(`/admin/t/${TID}/matches/345/score`)

    await screen.findByText('管理端登录')
    expect(screen.queryByText('确认提交大比分')).toBeNull()
  })

  it('未登录访问修改密码时进入登录页，不渲染改密表单', async () => {
    renderAt('/change-password')

    await screen.findByText('管理端登录')
    expect(screen.queryByText('设置新密码')).toBeNull()
    expect(screen.getByTestId('location').textContent).toBe('/login?next=%2Fchange-password')
  })

  it('已登录但赛事不在可管理列表时显示赛事不可用', async () => {
    authMeAuthenticated = true
    accessibleTournamentId = 99
    renderAt(`/admin/t/${TID}/matches/345/score`)

    await screen.findByText('无法访问赛事。')
    expect(screen.queryByText('确认提交大比分')).toBeNull()
    expect(requestedPaths.filter((path) => path.includes('/matches'))).toEqual([])
  })

  it('Admin Shell 显示用户态，退出后清态并进入登录页', async () => {
    authMeAuthenticated = true
    renderAt('/')

    await screen.findByText('王裁判')
    expect(screen.getByText('赛事管理员')).toBeTruthy()

    fireEvent.click(screen.getByText('王裁判'))
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))

    await screen.findByText('管理端登录')
    await waitFor(() => expect(logoutCalls).toBe(1))
  })

  it('修改密码成功后清除用户态并进入登录页', async () => {
    authMeAuthenticated = true
    renderAt('/')
    await screen.findByText('王裁判')

    fireEvent.click(screen.getByText('王裁判'))
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))
    await screen.findByText('设置新密码')
    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'original-password-123' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'replaced-password-456' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'replaced-password-456' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    await screen.findByText('管理端登录')
    expect(changePasswordPosts).toEqual([{
      current_password: 'original-password-123',
      new_password: 'replaced-password-456',
    }])
  })

  it('/admin/login 不被手机录分路由截断', async () => {
    renderAt('/admin/login')

    await screen.findByText('管理端登录')
    expect(screen.queryByText('链接不可用')).toBeNull()
  })
})
