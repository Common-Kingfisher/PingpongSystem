import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  ApiError,
  Dashboard,
  Entry,
  GroupingResult,
  Match,
  Player,
  PreflightResult,
  TableWithMatch,
  Tournament,
} from '../api'
import AdminDashboardPage, { selectDashboardTables } from '../pages/AdminDashboardPage'
import AdminRootPage from '../pages/AdminRootPage'

const tournament: Tournament = {
  id: 12,
  name: '城市乒乓球公开赛',
  date: '2026-10-01',
  table_count: 8,
  group_count: 4,
  qualify_per_group: 2,
  stage: 'GROUP_STAGE',
  created_at: '2026-09-24T00:00:00Z',
  event_type: 'SINGLES',
  bronze_mode: 'JOINT_BRONZE',
  placement_mode: 'COMPLETE',
  games_to_win: 2,
  points_to_win: 11,
  roster_confirmed: true,
  operation_mode: 'LIVE',
  registration_enabled: false,
  format_code: 'GROUP_KNOCKOUT',
  rule_config: {},
  rule_version: 1,
}

function match(id: number): Match {
  return {
    id,
    tournament_id: 12,
    stage: 'GROUP',
    group_id: 1,
    round: 1,
    match_index: id,
    player_a_id: id,
    player_b_id: id + 100,
    player_a_score: 0,
    player_b_score: 0,
    winner_id: null,
    table_id: id,
    status: 'PLAYING',
    prev_match_a_id: null,
    prev_match_b_id: null,
    entry_a_name: `红方${id}`,
    entry_b_name: `蓝方${id}`,
    bracket: 'GROUP',
    games: [],
  }
}

function table(id: number, status: 'FREE' | 'OCCUPIED'): TableWithMatch {
  return {
    id,
    name: `${id}号台`,
    status,
    match: status === 'OCCUPIED' ? match(id) : null,
    recommended_match_id: status === 'FREE' ? 20 + id : null,
  }
}

function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    tournament,
    stats: { total: 24, finished: 6, playing: 2, waiting: 18 },
    tables: [table(1, 'OCCUPIED'), table(2, 'FREE')],
    next_playable: [],
    ...overrides,
  }
}

const preflight: PreflightResult = {
  tournament,
  overall: 'BLOCK',
  ready_count: 8,
  warning_count: 1,
  blocker_count: 2,
  metrics: {},
  checks: [],
}

function installDashboardMocks(dash: Dashboard = dashboard()) {
  const getDashboard = vi.spyOn(api, 'getDashboard').mockResolvedValue(dash)
  vi.spyOn(api, 'getPreflight').mockResolvedValue({ ...preflight, tournament: dash.tournament })
  vi.spyOn(api, 'listPlayers').mockResolvedValue(Array.from({ length: 16 }, (_, index) => ({ id: index + 1 } as Player)))
  vi.spyOn(api, 'listEntries').mockResolvedValue(Array.from({ length: 12 }, (_, index) => ({ id: index + 1 } as Entry)))
  vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: Array.from({ length: 4 }, (_, index) => ({ id: index + 1 })) } as GroupingResult)
  vi.spyOn(api, 'getOrganization').mockResolvedValue({ id: 1, tournament_id: 12, name: '市乒协', created_at: '', updated_at: '' })
  vi.spyOn(api, 'getVenue').mockResolvedValue({ id: 1, tournament_id: 12, name: '市体育馆', created_at: '', updated_at: '' })
  return getDashboard
}

function renderDashboard() {
  return render(<MemoryRouter><AdminDashboardPage tournamentId={12} /></MemoryRouter>)
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.useRealTimers()
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('C-D5 根页面分流', () => {
  it('没有当前赛事时保留创建赛事和赛事列表，不渲染虚假 Dashboard', async () => {
    vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok' })
    vi.spyOn(api, 'listTournaments').mockResolvedValue([])
    render(<MemoryRouter><AdminRootPage /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: '创建赛事' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '赛事列表' })).toBeTruthy()
    expect(screen.queryByText('比赛进度')).toBeNull()
  })

  it('有效单打当前赛事进入真实 Dashboard', async () => {
    localStorage.setItem('pingpong_active_tournament_id', '12')
    vi.spyOn(api, 'getTournament').mockResolvedValue(tournament)
    installDashboardMocks()
    render(<MemoryRouter><AdminRootPage /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: tournament.name })).toBeTruthy()
    expect(screen.getByText('比赛进度')).toBeTruthy()
    expect(screen.queryByText('等待赛事概览数据')).toBeNull()
  })

  it('TEAM 保持独立入口，不请求普通 Match Dashboard', async () => {
    localStorage.setItem('pingpong_active_tournament_id', '12')
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...tournament, event_type: 'TEAM' })
    const getDashboard = vi.spyOn(api, 'getDashboard')
    render(<MemoryRouter><AdminRootPage /></MemoryRouter>)
    expect(await screen.findByText(/不会用个人赛 Match 数据伪装团体赛总览/)).toBeTruthy()
    expect(screen.getByRole('link', { name: '进入团体对抗' })).toBeTruthy()
    expect(getDashboard).not.toHaveBeenCalled()
  })
})

describe('C-D5 真实赛事总览', () => {
  it('显示后端统计、参赛规模、组织场馆与 Preflight 摘要', async () => {
    installDashboardMocks()
    renderDashboard()
    expect(await screen.findByText('进行中 2 场 · 待比赛 18 场')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.getByText('市乒协')).toBeTruthy()
    expect(screen.getByText('市体育馆')).toBeTruthy()
    expect(screen.getByText('2 项需要处理', { exact: false })).toBeTruthy()
    expect(screen.getByText((_, node) => node?.tagName === 'SPAN' && node.textContent === '1 注意')).toBeTruthy()
    expect(screen.getByText((_, node) => node?.tagName === 'SPAN' && node.textContent === '8 通过')).toBeTruthy()
    expect(screen.queryByText('下一步')).toBeNull()
  })

  it('ROUND_ROBIN 的 GROUP_STAGE 显示循环赛阶段', async () => {
    installDashboardMocks(dashboard({ tournament: { ...tournament, format_code: 'ROUND_ROBIN' } }))
    renderDashboard()
    expect(await screen.findByText('循环赛阶段')).toBeTruthy()
    expect(screen.queryByText('小组赛阶段')).toBeNull()
  })

  it('GROUP_KNOCKOUT 的 GROUP_STAGE 显示小组赛阶段', async () => {
    installDashboardMocks()
    renderDashboard()
    expect(await screen.findByText('小组赛阶段')).toBeTruthy()
  })

  it('总场数为 0 时安全显示 0%', async () => {
    installDashboardMocks(dashboard({ stats: { total: 0, finished: 0, playing: 0, waiting: 0 } }))
    renderDashboard()
    expect(await screen.findByText('0%')).toBeTruthy()
    expect(screen.getByLabelText('已完成 0%')).toBeTruthy()
  })

  it('Organization / Venue 返回 404 时正常省略', async () => {
    installDashboardMocks()
    vi.spyOn(api, 'getOrganization').mockRejectedValue(new ApiError(404, '未配置'))
    vi.spyOn(api, 'getVenue').mockRejectedValue(new ApiError(404, '未配置'))
    renderDashboard()
    expect(await screen.findByRole('heading', { name: tournament.name })).toBeTruthy()
    expect(screen.queryByText('主办单位：—')).toBeNull()
    expect(screen.queryByText('场馆：—')).toBeNull()
  })

  it('Organization 非 404 错误按首次加载错误处理并提供重试', async () => {
    installDashboardMocks()
    vi.spyOn(api, 'getOrganization').mockRejectedValue(new ApiError(500, '组织信息读取失败'))
    renderDashboard()
    expect(await screen.findByRole('heading', { name: '现场数据加载失败' })).toBeTruthy()
    expect(screen.getByText('组织信息读取失败')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  })

  it('展示全部使用中球台且最多补两张空闲球台，不提供排台操作', async () => {
    const tables = [
      ...Array.from({ length: 5 }, (_, index) => table(index + 1, 'OCCUPIED')),
      ...Array.from({ length: 3 }, (_, index) => table(index + 6, 'FREE')),
    ]
    expect(selectDashboardTables(tables).map((item) => item.id)).toEqual([1, 2, 3, 4, 5, 6, 7])
    installDashboardMocks(dashboard({ tables }))
    renderDashboard()
    await screen.findByRole('heading', { name: tournament.name })
    expect(screen.getByText((_, node) => node?.tagName === 'P' && node.textContent === '红方5 VS 蓝方5')).toBeTruthy()
    expect(screen.getByText((_, node) => node?.tagName === 'P' && node.textContent === '推荐 M26')).toBeTruthy()
    expect(screen.getByText((_, node) => node?.tagName === 'P' && node.textContent === '推荐 M27')).toBeTruthy()
    expect(screen.queryByText((_, node) => node?.tagName === 'P' && node.textContent === '推荐 M28')).toBeNull()
    expect(screen.queryByRole('button', { name: /排台|分配/ })).toBeNull()
  })

  it('只提供当前 master 真实存在的 Public 实况与赛程入口', async () => {
    installDashboardMocks()
    renderDashboard()
    const live = await screen.findByRole('link', { name: '公开实况' })
    const schedule = screen.getByRole('link', { name: '公开赛程' })
    expect(live.getAttribute('href')).toBe('/public/t/12/live')
    expect(schedule.getAttribute('href')).toBe('/public/t/12/schedule')
  })
})

describe('C-D5 Dashboard polling 与 stale', () => {
  it('visible 时每 10 秒刷新，hidden 时暂停，恢复可见后立即刷新', async () => {
    vi.useFakeTimers()
    const getDashboard = installDashboardMocks()
    renderDashboard()
    await act(async () => {})
    expect(getDashboard).toHaveBeenCalledTimes(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    expect(getDashboard).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    fireEvent(document, new Event('visibilitychange'))
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(getDashboard).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    fireEvent(document, new Event('visibilitychange'))
    await act(async () => {})
    expect(getDashboard).toHaveBeenCalledTimes(3)
  })

  it('刷新失败保留旧数据并提示 stale，恢复成功后清除提示', async () => {
    vi.useFakeTimers()
    const getDashboard = installDashboardMocks()
    getDashboard
      .mockResolvedValueOnce(dashboard())
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(dashboard({ stats: { total: 24, finished: 7, playing: 1, waiting: 17 } }))
    renderDashboard()
    await act(async () => {})
    expect(screen.getByText('进行中 2 场 · 待比赛 18 场')).toBeTruthy()

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    expect(screen.getByText(/当前显示可能不是最新状态/)).toBeTruthy()
    expect(screen.getByText('进行中 2 场 · 待比赛 18 场')).toBeTruthy()

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    await act(async () => {})
    expect(screen.queryByText(/当前显示可能不是最新状态/)).toBeNull()
    expect(screen.getByText('进行中 1 场 · 待比赛 17 场')).toBeTruthy()
  })
})
