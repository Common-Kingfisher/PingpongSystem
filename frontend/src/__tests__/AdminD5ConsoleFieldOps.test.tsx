import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router-dom'
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

// ------------------------------------------------------------------ 赛事切换竞态（PR #66 Warning 1）

/** 手动控制 resolve / reject 的 Promise。 */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

/** 通过真实 router 导航切换 ?tid=，而不是重新 mount（重新 mount 掩盖不了竞态）。 */
function ConsoleHarness({ to }: { to: string }) {
  const navigate = useNavigate()
  return (
    <>
      <button onClick={() => navigate(to)} type="button">切换到 {to}</button>
      <ConsolePage />
    </>
  )
}

const OLD_TID = 1
const NEW_TID = 2

function raceTournament(id: number, name: string): Tournament {
  return { ...tournament(), id, name }
}

function raceDashboard(id: number, name: string, finished: number, total: number, tableId: number, tableName: string): Dashboard {
  return dashboard({
    tournament: raceTournament(id, name),
    stats: { total, finished, playing: 0, waiting: total - finished },
    tables: [{
      id: tableId,
      name: tableName,
      status: 'FREE',
      match: null,
      recommended_match_id: null,
    }],
    next_playable: [],
  })
}

const syncText = () => (document.querySelector('.console-sync')?.textContent ?? '').replace(/\s+/g, ' ')
// jsdom 没有实现 innerText，这里用 textContent（空白已归一化，足以做包含断言）。
const bodyText = () => (document.body.textContent ?? '').replace(/\s+/g, ' ')

describe('C-D5 Console：赛事切换竞态（PR #66 Warning 1）', () => {
  it('切换 tid 后，旧赛事的在途响应不得覆盖新赛事快照 / stale / 最近同步时间', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-04T10:00:00'))

    // 旧赛事：getTournament 悬停在途 —— 模拟"切走时请求还没回来"。
    const oldTournament = deferred<Tournament>()
    vi.spyOn(api, 'getTournament').mockImplementation(async (id: number) =>
      id === OLD_TID ? oldTournament.promise : raceTournament(NEW_TID, '新赛事乙'))

    const newDash = raceDashboard(NEW_TID, '新赛事乙', 1, 10, 9, '9号台')
    const getDashboard = vi.spyOn(api, 'getDashboard').mockResolvedValue(newDash)
    vi.spyOn(api, 'listPlayers').mockResolvedValue([])
    vi.spyOn(api, 'listMatches').mockResolvedValue([])
    vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [] } as GroupingResult)
    vi.spyOn(api, 'getScheduleEstimates').mockResolvedValue({
      tournament_id: NEW_TID, generated_at: '', estimated_match_duration_seconds: 600,
      estimate_basis: 'TEST', sample_count: 0,
      initial_playing_matches: 0, simulated_batches: 0, truncated: false,
      matches: [],
    })

    render(
      <MemoryRouter initialEntries={[`/console?tid=${OLD_TID}`]}>
        <ConsoleHarness to={`/console?tid=${NEW_TID}`} />
      </MemoryRouter>,
    )
    await act(async () => {})
    // 旧赛事仍加载中
    expect(bodyText()).toContain('正在加载赛事数据')

    // 切到新赛事：它的请求必须立即发出（不能被旧赛事的在途请求挡掉）
    fireEvent.click(screen.getByRole('button', { name: `切换到 /console?tid=${NEW_TID}` }))
    await act(async () => {})
    expect(api.getTournament).toHaveBeenCalledWith(NEW_TID)
    expect(getDashboard).toHaveBeenCalledWith(NEW_TID)

    expect(bodyText()).toContain('新赛事乙')
    expect(bodyText()).toContain('比赛进度 1 / 10')
    expect(bodyText()).toContain('9号台')
    expect(syncText()).toContain('最近同步：10:00:00')
    expect(syncText()).not.toContain('当前显示可能不是最新状态')

    const syncedBefore = syncText()
    // 时间前进 5 分钟：如果旧响应错误地刷新了最近同步时间，时间文本就会变。
    vi.setSystemTime(new Date('2026-10-04T10:05:00'))

    // 现在才让旧赛事的响应回来
    await act(async () => { oldTournament.resolve(raceTournament(OLD_TID, '旧赛事甲')) })
    await act(async () => {})

    // 新赛事内容仍在，旧赛事没有重新出现，旧赛事的数据没有覆盖新赛事
    expect(bodyText()).toContain('新赛事乙')
    expect(bodyText()).toContain('比赛进度 1 / 10')
    expect(bodyText()).toContain('9号台')
    expect(bodyText()).not.toContain('旧赛事甲')
    // 旧请求不得改动 stale 与最近同步时间
    expect(syncText()).not.toContain('当前显示可能不是最新状态')
    expect(syncText()).toBe(syncedBefore)
    // 旧请求的 tid 不应触发任何后续请求
    expect(getDashboard).not.toHaveBeenCalledWith(OLD_TID)
  })

  it('旧赛事请求已进入 Promise.all 后才切走时，其后续响应同样被丢弃', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-04T10:00:00'))

    // 旧赛事：getTournament 立即返回，但 dashboard 悬停 —— 旧请求已经越过第一道守卫。
    const oldDashboard = deferred<Dashboard>()
    vi.spyOn(api, 'getTournament').mockImplementation(async (id: number) =>
      id === OLD_TID ? raceTournament(OLD_TID, '旧赛事甲') : raceTournament(NEW_TID, '新赛事乙'))
    const getDashboard = vi.spyOn(api, 'getDashboard').mockImplementation(async (id: number) =>
      id === OLD_TID ? oldDashboard.promise : raceDashboard(NEW_TID, '新赛事乙', 3, 10, 9, '9号台'))
    vi.spyOn(api, 'listPlayers').mockResolvedValue([])
    vi.spyOn(api, 'listMatches').mockResolvedValue([])
    vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [] } as GroupingResult)
    vi.spyOn(api, 'getScheduleEstimates').mockResolvedValue({
      tournament_id: NEW_TID, generated_at: '', estimated_match_duration_seconds: 600,
      estimate_basis: 'TEST', sample_count: 0,
      initial_playing_matches: 0, simulated_batches: 0, truncated: false,
      matches: [],
    })

    render(
      <MemoryRouter initialEntries={[`/console?tid=${OLD_TID}`]}>
        <ConsoleHarness to={`/console?tid=${NEW_TID}`} />
      </MemoryRouter>,
    )
    await act(async () => {})
    expect(getDashboard).toHaveBeenCalledWith(OLD_TID)

    fireEvent.click(screen.getByRole('button', { name: `切换到 /console?tid=${NEW_TID}` }))
    await act(async () => {})
    expect(bodyText()).toContain('新赛事乙')
    expect(bodyText()).toContain('比赛进度 3 / 10')

    const syncedBefore = syncText()
    vi.setSystemTime(new Date('2026-10-04T10:09:00'))

    await act(async () => {
      oldDashboard.resolve(raceDashboard(OLD_TID, '旧赛事甲', 23, 24, 1, '1号台'))
    })
    await act(async () => {})

    expect(bodyText()).toContain('新赛事乙')
    expect(bodyText()).toContain('比赛进度 3 / 10')
    expect(bodyText()).toContain('9号台')
    expect(bodyText()).not.toContain('旧赛事甲')
    expect(bodyText()).not.toContain('1号台')
    expect(syncText()).not.toContain('当前显示可能不是最新状态')
    expect(syncText()).toBe(syncedBefore)
  })

  it('旧赛事请求失败时不得把新赛事标记成 stale', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-04T10:00:00'))

    const oldTournament = deferred<Tournament>()
    vi.spyOn(api, 'getTournament').mockImplementation(async (id: number) =>
      id === OLD_TID ? oldTournament.promise : raceTournament(NEW_TID, '新赛事乙'))
    vi.spyOn(api, 'getDashboard').mockResolvedValue(raceDashboard(NEW_TID, '新赛事乙', 2, 10, 9, '9号台'))
    vi.spyOn(api, 'listPlayers').mockResolvedValue([])
    vi.spyOn(api, 'listMatches').mockResolvedValue([])
    vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [] } as GroupingResult)
    vi.spyOn(api, 'getScheduleEstimates').mockResolvedValue({
      tournament_id: NEW_TID, generated_at: '', estimated_match_duration_seconds: 600,
      estimate_basis: 'TEST', sample_count: 0,
      initial_playing_matches: 0, simulated_batches: 0, truncated: false,
      matches: [],
    })

    render(
      <MemoryRouter initialEntries={[`/console?tid=${OLD_TID}`]}>
        <ConsoleHarness to={`/console?tid=${NEW_TID}`} />
      </MemoryRouter>,
    )
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: `切换到 /console?tid=${NEW_TID}` }))
    await act(async () => {})
    expect(bodyText()).toContain('新赛事乙')
    const syncedBefore = syncText()

    vi.setSystemTime(new Date('2026-10-04T10:07:00'))
    await act(async () => { oldTournament.reject(new ApiError(500, '旧赛事读取失败')) })
    await act(async () => {})

    expect(syncText()).not.toContain('当前显示可能不是最新状态')
    expect(syncText()).toBe(syncedBefore)
    expect(bodyText()).toContain('新赛事乙')
    expect(bodyText()).not.toContain('旧赛事读取失败')
  })
})

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

  /**
   * 后端 `completion.state` 的行为表。
   *
   * 类型是 `Record<DashboardCompletion['state'], ...>`，因此：
   * - 后端新增 state 时这里**必须**补一行，否则 `tsc` 报缺 key；
   * - 写了契约外的 state 也会被 `tsc` 拒绝。
   * 这保证测试不会变成"与生产代码各自漂移的第二套列表"。
   */
  const STATE_COVERAGE: Record<DashboardCompletion['state'], {
    format: DashboardCompletion['format_code']
    /** null = 该状态属于"正常进行中"，不显示横幅。 */
    expectedTitle: string | null
  }> = {
    NOT_APPLICABLE: { format: null, expectedTitle: '尚未设置赛制' },
    UNAVAILABLE: { format: 'GROUP_KNOCKOUT', expectedTitle: '赛制配置无法解析' },
    GROUP_MATCHES_NOT_GENERATED: { format: 'GROUP_KNOCKOUT', expectedTitle: '小组赛尚未生成' },
    GROUP_STAGE_IN_PROGRESS: { format: 'GROUP_KNOCKOUT', expectedTitle: null },
    QUALIFICATION_UNRESOLVED: { format: 'GROUP_KNOCKOUT', expectedTitle: '小组出线存在无法判定的并列' },
    KNOCKOUT_NOT_READY: { format: 'GROUP_KNOCKOUT', expectedTitle: '小组赛已结束，淘汰签暂时无法生成' },
    KNOCKOUT_READY: { format: 'GROUP_KNOCKOUT', expectedTitle: '小组赛已全部完成' },
    KNOCKOUT_IN_PROGRESS: { format: 'GROUP_KNOCKOUT', expectedTitle: null },
    MATCHES_NOT_GENERATED: { format: 'GROUP_KNOCKOUT', expectedTitle: '小组赛尚未生成' },
    ROUND_ROBIN_IN_PROGRESS: { format: 'ROUND_ROBIN', expectedTitle: null },
    RANKING_DATA_INSUFFICIENT: { format: 'ROUND_ROBIN', expectedTitle: '循环赛已结束，排名数据不足' },
    RANKING_UNRESOLVED: { format: 'ROUND_ROBIN', expectedTitle: '循环赛已结束，但仍有无法判定的并列' },
    COMPLETED: { format: 'GROUP_KNOCKOUT', expectedTitle: '赛事已全部完成' },
  }

  it('后端全部 state 取值都有明确处理（13 个，行为表由契约类型强制穷尽）', () => {
    const states = Object.keys(STATE_COVERAGE) as DashboardCompletion['state'][]
    // 与 generated OpenAPI 的 DashboardCompletion.state 联合成员数一致
    expect(states).toHaveLength(13)
    for (const state of states) {
      const spec = STATE_COVERAGE[state]
      const dash = dashboard({ completion: completion({ format_code: spec.format, state }) })
      const notice = completionNotice(dash, TID)
      if (spec.expectedTitle === null) {
        expect(notice, state).toBeNull()
      } else {
        expect(notice, state).not.toBeNull()
        expect(notice?.title, state).toBe(spec.expectedTitle)
        expect(notice?.detail, state).toBeTruthy()
      }
    }
  })

  it('服务端返回契约外状态时运行期兜底：不静默、不白屏', () => {
    // 模拟"后端上了新状态但前端还没更新" —— 只能靠 cast 构造。
    const bogus = {
      ...completion(),
      state: 'SOMETHING_NEW_FROM_BACKEND',
    } as unknown as DashboardCompletion
    const notice = completionNotice(dashboard({ completion: bogus }), TID)
    expect(notice).not.toBeNull()
    expect(notice?.title).toBe('无法识别赛事状态')
    expect(notice?.detail).toContain('SOMETHING_NEW_FROM_BACKEND')
    expect(notice?.tone).toBe('warn')
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
