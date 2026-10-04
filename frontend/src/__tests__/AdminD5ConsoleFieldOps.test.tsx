import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  ApiError,
  Dashboard,
  DashboardCompletion,
  GroupingResult,
  Match,
  Player,
  TableWithMatch,
  Tournament,
} from '../api'
import ConsolePage from '../pages/ConsolePage'
import {
  CONSOLE_POLL_INTERVAL_MS,
  assignDisabledReason,
  canAssignMatches,
  canScheduleBatch,
  completionNotice,
  recommendedMatchForTable,
  sortTablesByNumber,
} from '../fieldOps'

const TID = 12

function tournament(overrides: Partial<Tournament> = {}): Tournament {
  return {
    id: TID,
    name: '城市乒乓球公开赛',
    date: '2026-10-01',
    table_count: 6,
    group_count: 4,
    qualify_per_group: 2,
    stage: 'GROUP_STAGE',
    created_at: '2026-09-24T00:00:00Z',
    event_type: 'SINGLES',
    bronze_mode: 'JOINT_BRONZE',
    placement_mode: 'COMPLETE',
    games_to_win: 3,
    points_to_win: 11,
    roster_confirmed: true,
    operation_mode: 'LIVE',
    registration_enabled: false,
    format_code: 'GROUP_KNOCKOUT',
    rule_config: {},
    rule_version: 1,
    ...overrides,
  }
}

function match(id: number, overrides: Partial<Match> = {}): Match {
  return {
    id,
    tournament_id: TID,
    stage: 'GROUP',
    group_id: 1,
    round: 1,
    match_index: id,
    player_a_id: id,
    player_b_id: id + 100,
    player_a_score: 0,
    player_b_score: 0,
    winner_id: null,
    table_id: null,
    status: 'WAITING',
    prev_match_a_id: null,
    prev_match_b_id: null,
    entry_a_id: id,
    entry_b_id: id + 100,
    entry_a_name: `红方${id}`,
    entry_b_name: `蓝方${id}`,
    bracket: 'GROUP',
    games: [],
    ...overrides,
  }
}

function table(id: number, status: 'FREE' | 'OCCUPIED', recommended: number | null = null): TableWithMatch {
  return {
    id,
    name: `${id}号台`,
    status,
    match: status === 'OCCUPIED' ? match(id, { status: 'PLAYING', table_id: id }) : null,
    recommended_match_id: status === 'FREE' ? recommended : null,
  }
}

function completion(overrides: Partial<DashboardCompletion> = {}): DashboardCompletion {
  return { format_code: 'GROUP_KNOCKOUT', state: 'GROUP_STAGE_IN_PROGRESS', can_advance: false, completed: false, ...overrides }
}

function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    tournament: tournament(),
    stats: { total: 24, finished: 6, playing: 1, waiting: 17 },
    tables: [table(1, 'OCCUPIED'), table(2, 'FREE', 21)],
    next_playable: [match(21), match(22)],
    completion: completion(),
    ...overrides,
  }
}

function installMocks(dash: Dashboard = dashboard(), options: { finished?: Match[]; waiting?: Match[] } = {}) {
  const getTournament = vi.spyOn(api, 'getTournament').mockResolvedValue(dash.tournament)
  const getDashboard = vi.spyOn(api, 'getDashboard').mockResolvedValue(dash)
  vi.spyOn(api, 'listPlayers').mockResolvedValue([{ id: 1, name: '选手1' } as Player])
  vi.spyOn(api, 'listMatches').mockImplementation(async (_tid: number, params?: { status?: string }) => {
    if (params?.status === 'FINISHED') return options.finished ?? []
    if (params?.status === 'WAITING') return options.waiting ?? [match(21), match(22)]
    return []
  })
  vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [{ id: 1, name: 'A组' }] } as GroupingResult)
  vi.spyOn(api, 'getScheduleEstimates').mockResolvedValue({
    tournament_id: TID, generated_at: '', estimated_match_duration_seconds: 600,
    estimate_basis: 'TEST', sample_count: 0,
    initial_playing_matches: 0, simulated_batches: 0, truncated: false,
    matches: [],
  })
  return { getTournament, getDashboard }
}

function renderConsole() {
  return render(<MemoryRouter initialEntries={[`/console?tid=${TID}`]}><ConsolePage /></MemoryRouter>)
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

// ------------------------------------------------------------------ 纯函数契约

describe('C-D5 fieldOps：只消费后端事实', () => {
  it('球台按台号稳定排序，不因 OCCUPIED / FREE 变化跳动', () => {
    const before = [table(3, 'OCCUPIED'), table(1, 'FREE'), table(2, 'OCCUPIED')]
    expect(sortTablesByNumber(before).map((t) => t.id)).toEqual([1, 2, 3])
    // 状态翻转后顺序不变（只按 id / 名称，不看占用状态）
    const after = [table(3, 'FREE'), table(1, 'OCCUPIED'), table(2, 'FREE')]
    expect(sortTablesByNumber(after).map((t) => t.id)).toEqual([1, 2, 3])
    expect(sortTablesByNumber(before).map((t) => t.id)).toEqual(sortTablesByNumber(after).map((t) => t.id))
  })

  it('推荐比赛只按后端 recommended_match_id 查表，不重新排序 next_playable', () => {
    const dash = dashboard({ tables: [table(2, 'FREE', 22)], next_playable: [match(21), match(22)] })
    expect(recommendedMatchForTable(dash, dash.tables[0])?.id).toBe(22)
    // 后端没有给建议时不自行挑一场
    const none = dashboard({ tables: [table(2, 'FREE', null)], next_playable: [match(21), match(22)] })
    expect(recommendedMatchForTable(none, none.tables[0])).toBeUndefined()
  })

  it('ROUND_ROBIN 完成后不出现淘汰赛入口', () => {
    const dash = dashboard({
      tournament: tournament({ format_code: 'ROUND_ROBIN', stage: 'FINISHED' }),
      completion: completion({ format_code: 'ROUND_ROBIN', state: 'COMPLETED', completed: true }),
    })
    const notice = completionNotice(dash, TID)
    expect(notice?.title).toBe('循环赛已全部完成')
    expect(notice?.action?.label).not.toBe('进入淘汰赛')
    // 关键：can_advance 永远为 false，所以批量排台与排台入口都关闭
    expect(canAssignMatches(dash)).toBe(false)
    expect(canScheduleBatch(dash)).toBe(false)
  })

  it('SINGLE_ELIMINATION 的未生成文案明确否认小组阶段', () => {
    const dash = dashboard({
      tournament: tournament({ format_code: 'SINGLE_ELIMINATION' }),
      completion: completion({ format_code: 'SINGLE_ELIMINATION', state: 'MATCHES_NOT_GENERATED' }),
      next_playable: [],
      stats: { total: 0, finished: 0, playing: 0, waiting: 0 },
    })
    const notice = completionNotice(dash, TID)
    expect(notice?.title).toBe('淘汰签尚未生成')
    expect(notice?.title).not.toContain('小组')
    // 必须明确说"不存在小组阶段"，而不是诱导用户去找小组赛
    expect(notice?.detail).toContain('不存在小组阶段')
  })

  it('GROUP_MATCHES_NOT_GENERATED 与 MATCHES_NOT_GENERATED 都被识别为“尚未生成”', () => {
    const knockout = dashboard({ completion: completion({ state: 'GROUP_MATCHES_NOT_GENERATED' }) })
    const roundRobin = dashboard({
      tournament: tournament({ format_code: 'ROUND_ROBIN' }),
      completion: completion({ format_code: 'ROUND_ROBIN', state: 'MATCHES_NOT_GENERATED' }),
    })
    expect(completionNotice(knockout, TID)?.title).toBe('小组赛尚未生成')
    expect(completionNotice(roundRobin, TID)?.title).toBe('循环赛尚未生成')
  })

  it('未设置赛制的历史赛事不默认成小组淘汰', () => {
    const dash = dashboard({
      tournament: tournament({ format_code: null }),
      completion: completion({ format_code: null, state: 'NOT_APPLICABLE' }),
    })
    expect(completionNotice(dash, TID)?.title).toBe('尚未设置赛制')
  })

  it('后端全部 state 取值都有明确处理（不留静默分支）', () => {
    const states = [
      'NOT_APPLICABLE', 'UNAVAILABLE',
      'GROUP_MATCHES_NOT_GENERATED', 'MATCHES_NOT_GENERATED',
      'GROUP_STAGE_IN_PROGRESS', 'ROUND_ROBIN_IN_PROGRESS', 'KNOCKOUT_IN_PROGRESS',
      'QUALIFICATION_UNRESOLVED', 'KNOCKOUT_NOT_READY', 'KNOCKOUT_READY',
      'RANKING_DATA_INSUFFICIENT', 'RANKING_UNRESOLVED', 'COMPLETED',
    ]
    // 只有"正常进行中"允许没有横幅；其余每个 state 都必须有明确文案。
    const inProgress = new Set([
      'GROUP_STAGE_IN_PROGRESS', 'ROUND_ROBIN_IN_PROGRESS', 'KNOCKOUT_IN_PROGRESS',
    ])
    for (const state of states) {
      // NOT_APPLICABLE 只可能由"团体赛 / 未设置赛制"产生，因此 format_code 为 null。
      const format = state === 'NOT_APPLICABLE' ? null : 'GROUP_KNOCKOUT'
      const dash = dashboard({ completion: completion({ format_code: format, state }) })
      const notice = completionNotice(dash, TID)
      if (inProgress.has(state)) {
        expect(notice, state).toBeNull()
      } else {
        expect(notice, state).not.toBeNull()
        expect(notice?.title, state).toBeTruthy()
        expect(notice?.detail, state).toBeTruthy()
      }
    }
  })

  it('阶段收口时排台入口全部关闭并给出原因', () => {
    const ready = dashboard({ completion: completion({ state: 'KNOCKOUT_READY', can_advance: true }) })
    expect(canAssignMatches(ready)).toBe(false)
    expect(canScheduleBatch(ready)).toBe(false)
    expect(assignDisabledReason(ready)).toBe('本阶段已结束')

    const playing = dashboard()
    expect(canAssignMatches(playing)).toBe(true)
    expect(assignDisabledReason(playing)).toBeUndefined()
  })
})

// ------------------------------------------------------------------ 页面行为

describe('C-D5 Console：5 秒同步与 stale 语义', () => {
  it('visible 时每 5 秒静默刷新，hidden 暂停，恢复可见立即刷新', async () => {
    vi.useFakeTimers()
    const { getDashboard } = installMocks()
    renderConsole()
    await act(async () => {})
    expect(getDashboard).toHaveBeenCalledTimes(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_INTERVAL_MS) })
    expect(getDashboard).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    fireEvent(document, new Event('visibilitychange'))
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_INTERVAL_MS * 3) })
    expect(getDashboard).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    fireEvent(document, new Event('visibilitychange'))
    await act(async () => {})
    expect(getDashboard).toHaveBeenCalledTimes(3)
  })

  it('轮询失败保留最后一次成功快照，显示 stale，恢复后自动清除', async () => {
    vi.useFakeTimers()
    const { getDashboard } = installMocks()
    getDashboard
      .mockResolvedValueOnce(dashboard())
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(dashboard({ stats: { total: 24, finished: 7, playing: 1, waiting: 16 } }))
    renderConsole()
    await act(async () => {})
    expect(screen.getByText(/比赛进度 6 \/ 24/)).toBeTruthy()
    expect(screen.queryByText(/当前显示可能不是最新状态/)).toBeNull()

    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_INTERVAL_MS) })
    expect(screen.getByText(/当前显示可能不是最新状态/)).toBeTruthy()
    // 关键：不因一次轮询失败清空比赛列表 / 球台 / 比分
    expect(screen.getByText(/比赛进度 6 \/ 24/)).toBeTruthy()
    expect(screen.getByText('1号台')).toBeTruthy()
    expect(screen.getByText('最近同步：', { exact: false })).toBeTruthy()

    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_INTERVAL_MS) })
    await act(async () => {})
    expect(screen.queryByText(/当前显示可能不是最新状态/)).toBeNull()
    expect(screen.getByText(/比赛进度 7 \/ 24/)).toBeTruthy()
  })

  it('首次加载失败时给出错误信息与重试按钮，不白屏、不无限 loading', async () => {
    installMocks()
    vi.spyOn(api, 'getTournament').mockRejectedValue(new ApiError(404, '资源不存在'))
    renderConsole()
    expect(await screen.findByText(/现场数据加载失败/)).toBeTruthy()
    expect(screen.getByText(/资源不存在/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
    expect(screen.queryByText(/正在加载赛事数据/)).toBeNull()
  })

  it('刷新失败后恢复成功会更新现场状态', async () => {
    vi.useFakeTimers()
    const { getDashboard } = installMocks()
    getDashboard
      .mockResolvedValueOnce(dashboard())
      .mockResolvedValueOnce(dashboard({
        stats: { total: 24, finished: 8, playing: 2, waiting: 14 },
        tables: [table(1, 'OCCUPIED'), table(2, 'OCCUPIED')],
      }))
    renderConsole()
    await act(async () => {})
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_INTERVAL_MS) })
    expect(screen.getByText(/比赛进度 8 \/ 24/)).toBeTruthy()
    expect(screen.getByText(/正在进行 2/)).toBeTruthy()
  })
})

describe('C-D5 Console：球台与排台', () => {
  it('球台固定按台号排列，状态变化不改变顺序', async () => {
    installMocks(dashboard({
      tables: [table(3, 'OCCUPIED'), table(1, 'FREE', 21), table(2, 'OCCUPIED')],
    }))
    renderConsole()
    await act(async () => {})
    const cards = document.querySelectorAll('.live-table-card .live-table-head strong')
    expect([...cards].map((node) => node.textContent)).toEqual(['1号台', '2号台', '3号台'])
  })

  it('空闲球台只读展示后端推荐，不由前端挑选比赛', async () => {
    installMocks(dashboard({
      tables: [table(1, 'FREE', 22)],
      next_playable: [match(21), match(22)],
    }))
    renderConsole()
    await act(async () => {})
    expect(screen.getByText('后端推荐：红方22 vs 蓝方22')).toBeTruthy()
  })

  it('安排比赛列出后端全部合法 next_playable，而不是前端选好的一场', async () => {
    installMocks(dashboard({
      tables: [table(1, 'FREE', 22)],
      next_playable: [match(21), match(22), match(23)],
    }))
    renderConsole()
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '安排比赛' }))
    const dialog = screen.getByRole('dialog', { name: /为 1号台 安排比赛/ })
    const items = within(dialog).getAllByRole('button')
    // 3 场后端候选 + 关闭按钮
    expect(items.filter((item) => item.className.includes('console-assign-item'))).toHaveLength(3)
    expect(within(dialog).getByText('后端推荐')).toBeTruthy()
    expect(within(dialog).getByText(/本页不重新排序/)).toBeTruthy()
  })

  it('阶段收口时不显示自动排台，空闲球台按钮给出后端阶段原因', async () => {
    installMocks(dashboard({
      stats: { total: 24, finished: 24, playing: 0, waiting: 0 },
      tables: [table(1, 'FREE', null)],
      next_playable: [],
      completion: completion({ state: 'KNOCKOUT_READY', can_advance: true }),
    }))
    renderConsole()
    await act(async () => {})
    expect(screen.queryByRole('button', { name: '自动安排下一批比赛' })).toBeNull()
    expect(screen.getByRole('button', { name: '本阶段已结束' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '进入淘汰赛' })).toBeTruthy()
  })

  it('ROUND_ROBIN 完成后不诱导生成淘汰赛', async () => {
    installMocks(dashboard({
      tournament: tournament({ format_code: 'ROUND_ROBIN', stage: 'FINISHED' }),
      stats: { total: 15, finished: 15, playing: 0, waiting: 0 },
      tables: [table(1, 'FREE', null)],
      next_playable: [],
      completion: completion({ format_code: 'ROUND_ROBIN', state: 'COMPLETED', completed: true }),
    }))
    renderConsole()
    await act(async () => {})
    expect(screen.getByText('循环赛已全部完成')).toBeTruthy()
    expect(screen.queryByRole('link', { name: '进入淘汰赛' })).toBeNull()
    expect(screen.queryByRole('button', { name: '自动安排下一批比赛' })).toBeNull()
  })

  it('SINGLE_ELIMINATION 的未生成提示不出现小组阶段文案', async () => {
    installMocks(dashboard({
      tournament: tournament({ format_code: 'SINGLE_ELIMINATION', stage: 'REGISTRATION' }),
      stats: { total: 0, finished: 0, playing: 0, waiting: 0 },
      tables: [],
      next_playable: [],
      completion: completion({ format_code: 'SINGLE_ELIMINATION', state: 'MATCHES_NOT_GENERATED' }),
    }))
    renderConsole()
    await act(async () => {})
    expect(screen.getByText('淘汰签尚未生成')).toBeTruthy()
    expect(screen.getByText(/单淘汰赛不存在小组阶段/)).toBeTruthy()
    expect(screen.getByText(/当前赛事还没有可用球台/)).toBeTruthy()
  })

  it('阶段标签按赛制显示，不把所有赛制写死成小组赛', async () => {
    installMocks(dashboard({
      tournament: tournament({ format_code: 'ROUND_ROBIN' }),
      completion: completion({ format_code: 'ROUND_ROBIN', state: 'ROUND_ROBIN_IN_PROGRESS' }),
    }))
    renderConsole()
    await act(async () => {})
    expect(screen.getByText('循环赛阶段')).toBeTruthy()
    expect(screen.queryByText('小组赛阶段')).toBeNull()
  })

  it('顶部只保留高频操作，低频入口收进“更多”', async () => {
    installMocks()
    renderConsole()
    await act(async () => {})
    const more = screen.getByText('更多').closest('details')
    expect(more).toBeTruthy()
    for (const label of ['实时赛程', '打印快照', '排名', '淘汰赛']) {
      expect(within(more as HTMLElement).getByRole('link', { name: label })).toBeTruthy()
    }
    // 高频操作直出，不在“更多”折叠里
    expect(within(more as HTMLElement).queryByRole('button', { name: '自动安排下一批比赛' })).toBeNull()
    expect(screen.getByRole('button', { name: '刷新' })).toBeTruthy()
  })

  it('已结束比赛的“打印成绩单 / 操作记录”收进行内“更多”', async () => {
    installMocks(dashboard(), {
      finished: [match(88, { status: 'FINISHED', stage: 'GROUP', player_a_score: 3, player_b_score: 1, result_type: 'NORMAL' })],
    })
    renderConsole()
    await act(async () => {})
    expect(screen.getByRole('button', { name: '修改大比分' })).toBeTruthy()
    const row = screen.getByRole('button', { name: '修改大比分' }).closest('tr') as HTMLElement
    const rowMore = within(row).getByText('更多').closest('details') as HTMLElement
    expect(within(rowMore).getByRole('button', { name: '操作记录' })).toBeTruthy()
    expect(within(rowMore).getByRole('link', { name: '打印成绩单' })).toBeTruthy()
    expect(within(rowMore).getByRole('button', { name: '补录小比分' })).toBeTruthy()
  })

  it('超长赛事名不破坏主布局（有界文本容器）', async () => {
    const longName = '全国大学生乒乓球锦标赛'.repeat(6)
    installMocks(dashboard({ tournament: tournament({ name: longName }) }))
    renderConsole()
    await act(async () => {})
    const title = document.querySelector('.console-title-text')
    expect(title?.textContent).toContain(longName)
  })
})

describe('C-D5 Console：TEAM 硬边界', () => {
  it('团体赛不请求普通 Match Dashboard，也不渲染球台与比分', async () => {
    const getDashboard = vi.spyOn(api, 'getDashboard')
    vi.spyOn(api, 'getTournament').mockResolvedValue(tournament({ event_type: 'TEAM' }))
    renderConsole()
    expect(await screen.findByText(/不使用个人赛 Match 比赛控制台/)).toBeTruthy()
    expect(getDashboard).not.toHaveBeenCalled()
    expect(screen.queryByText(/比赛进度/)).toBeNull()
    expect(screen.queryByText('比赛现场')).toBeNull()
  })
})

describe('C-D5 Console：无赛事与空态', () => {
  it('没有当前赛事时不无限 loading', async () => {
    localStorage.clear()
    render(<MemoryRouter initialEntries={['/console']}><ConsolePage /></MemoryRouter>)
    expect(await screen.findByText(/请先在/)).toBeTruthy()
    expect(screen.queryByText(/正在加载赛事数据/)).toBeNull()
  })

  it('无比赛时给出合理空态而不是白屏', async () => {
    installMocks(dashboard({
      stats: { total: 0, finished: 0, playing: 0, waiting: 0 },
      tables: [],
      next_playable: [],
      completion: completion({ state: 'GROUP_MATCHES_NOT_GENERATED' }),
    }), { finished: [], waiting: [] })
    renderConsole()
    await act(async () => {})
    expect(screen.getByText(/当前赛事还没有可用球台/)).toBeTruthy()
    expect(screen.getByText('暂无待进行的比赛。')).toBeTruthy()
    expect(screen.getByText('暂无已结束的比赛。')).toBeTruthy()
  })
})
