import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  ApiError,
  Dashboard,
  Entry,
  GroupingResult,
  KnockoutTree,
  Match,
  OrderBookSnapshot,
  Player,
  RankingsResult,
  Tournament,
} from '../api'
import SchedulePage from '../pages/SchedulePage'
import OrderBookPage from '../pages/OrderBookPage'

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
    player_a_score: null,
    player_b_score: null,
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

function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    tournament: tournament(),
    stats: { total: 4, finished: 0, playing: 0, waiting: 4 },
    tables: [
      { id: 1, name: '1号台', status: 'FREE', match: null, recommended_match_id: 1 },
      { id: 2, name: '2号台', status: 'FREE', match: null, recommended_match_id: null },
    ],
    next_playable: [match(1)],
    completion: { format_code: 'GROUP_KNOCKOUT', state: 'GROUP_STAGE_IN_PROGRESS', can_advance: false, completed: false },
    ...overrides,
  }
}

const emptyTree: KnockoutTree = {
  tournament: tournament(), rounds: [], champion: null, runner_up: null,
  placements: [], placement_matches: [], champion_path_match_ids: [],
}

const knockoutTree: KnockoutTree = {
  ...emptyTree,
  rounds: [
    { round: 1, label: '8强赛', matches: [{ id: 90, player_a: null, player_b: null } as never] },
    { round: 3, label: '决赛', matches: [{ id: 99, player_a: null, player_b: null } as never] },
  ],
}

function estimate(match_id: number, overrides: Record<string, unknown> = {}) {
  return {
    match_id,
    stage: 'GROUP' as const,
    round: 1,
    group_id: 1,
    estimated_start_at: null,
    estimated_wait_minutes: null,
    queue_ahead: null,
    estimate_basis: null,
    unavailable_reason: null,
    ...overrides,
  }
}

function installScheduleMocks(options: {
  matches?: Match[]
  tree?: KnockoutTree
  estimates?: ReturnType<typeof estimate>[]
  dash?: Dashboard
  tournament?: Tournament
} = {}) {
  const t = options.tournament ?? tournament()
  vi.spyOn(api, 'getTournament').mockResolvedValue(t)
  vi.spyOn(api, 'listPlayers').mockResolvedValue([{ id: 1, name: '选手1' } as Player])
  vi.spyOn(api, 'listEntries').mockResolvedValue([{ id: 1, display_name: '红方1', group_id: 1, seed_no: null, members: [] } as unknown as Entry])
  vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [{ id: 1, name: 'A组' }] } as GroupingResult)
  vi.spyOn(api, 'listMatches').mockResolvedValue(options.matches ?? [match(1), match(2)])
  vi.spyOn(api, 'getDashboard').mockResolvedValue(options.dash ?? { ...dashboard(), tournament: t })
  vi.spyOn(api, 'getKnockout').mockResolvedValue(options.tree ?? emptyTree)
  vi.spyOn(api, 'getScheduleEstimates').mockResolvedValue({
    tournament_id: TID, generated_at: '2026-10-01T02:00:00Z', estimated_match_duration_seconds: 600,
    estimate_basis: 'TEST', sample_count: 0,
    initial_playing_matches: 0, simulated_batches: 0, truncated: false,
    matches: options.estimates ?? [],
  })
}

function renderSchedule(variant: 'admin' | 'public' = 'admin') {
  return render(
    <MemoryRouter initialEntries={[`/schedule?tid=${TID}`]}>
      <SchedulePage variant={variant} />
    </MemoryRouter>,
  )
}

function renderOrderBook(entry = `/orderbook?tid=${TID}`) {
  return render(<MemoryRouter initialEntries={[entry]}><OrderBookPage /></MemoryRouter>)
}

function snapshot(overrides: Partial<OrderBookSnapshot> = {}): OrderBookSnapshot {
  return {
    snapshot_at: '2026-10-01T02:30:00.000Z',
    tournament: tournament(),
    entries: [],
    groups: { groups: [] } as GroupingResult,
    rankings: { rankings: [] } as RankingsResult,
    tree: emptyTree,
    matches: [match(1, { status: 'FINISHED', player_a_score: 3, player_b_score: 1, table_id: 1 })],
    dashboard: dashboard(),
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

afterEach(cleanup)

// ------------------------------------------------------------------ 实时赛程

describe('C-D5 Schedule：默认展示实时赛程', () => {
  it('管理端展示轮次、对阵、球台、状态与比分', async () => {
    installScheduleMocks({
      matches: [
        match(1, { status: 'FINISHED', player_a_score: 3, player_b_score: 1, result_type: 'NORMAL', table_id: 1 }),
        match(2, { status: 'WAITING', table_id: null, round: 2 }),
      ],
    })
    renderSchedule('admin')
    expect(await screen.findByText('实时赛程（2 场）')).toBeTruthy()
    const table = document.querySelector('.schedule-table') as HTMLElement
    expect(within(table).getByText('A组 · 小组赛 · 第 1 轮')).toBeTruthy()
    expect(within(table).getByText('A组 · 小组赛 · 第 2 轮')).toBeTruthy()
    expect(within(table).getByText('红方1 VS 蓝方1')).toBeTruthy()
    expect(within(table).getByText('1号台')).toBeTruthy()
    expect(within(table).getByText('待安排')).toBeTruthy()
    // 状态列用 .schedule-status 精确定位（"已结束"也会出现在预计上场列）
    const statuses = [...table.querySelectorAll('.schedule-status')].map((node) => node.textContent)
    expect(statuses).toEqual(['已结束', '待开始'])
    expect(within(table).getByText('3 : 1')).toBeTruthy()
  })

  it('淘汰赛轮次名直接取后端签表 label，不按 round 数字自行命名', async () => {
    installScheduleMocks({
      matches: [match(90, { stage: 'KNOCKOUT', bracket: 'MAIN', round: 1, group_id: null })],
      tree: knockoutTree,
    })
    renderSchedule('admin')
    await screen.findByText('实时赛程（1 场）')
    const table = document.querySelector('.schedule-table') as HTMLElement
    expect(within(table).getByText('8强赛')).toBeTruthy()
  })

  it('预计上场时间来自后端估算；无法估算时明确降级', async () => {
    installScheduleMocks({
      matches: [match(1), match(2)],
      estimates: [
        estimate(1, { estimated_start_at: '2026-10-01T02:00:00Z', queue_ahead: 2 }),
        estimate(2, { unavailable_reason: '签位未定' }),
      ],
    })
    renderSchedule('admin')
    await screen.findByText('实时赛程（2 场）')
    const table = document.querySelector('.schedule-table') as HTMLElement
    expect(within(table).getAllByText(/约 |签位未定/).length).toBe(2)
  })

  it('没有比赛时给出空态，不白屏', async () => {
    installScheduleMocks({ matches: [] })
    renderSchedule('admin')
    expect(await screen.findByText(/当前赛事还没有生成比赛/)).toBeTruthy()
  })

  it('加载失败时给出明确错误', async () => {
    installScheduleMocks()
    vi.spyOn(api, 'getTournament').mockRejectedValue(new ApiError(404, '资源不存在'))
    renderSchedule('admin')
    expect(await screen.findByText(/赛程加载失败：资源不存在/)).toBeTruthy()
  })

  it('失效 tid 不无限 loading', async () => {
    installScheduleMocks()
    render(<MemoryRouter initialEntries={['/schedule']}><SchedulePage variant="admin" /></MemoryRouter>)
    expect(await screen.findByText(/请先在/)).toBeTruthy()
    expect(screen.queryByText(/正在加载赛程/)).toBeNull()
  })
})

describe('C-D5 Schedule：打印快照语义', () => {
  it('打印区包含赛事名称、生成时间、当前阶段与数据状态', async () => {
    installScheduleMocks()
    renderSchedule('admin')
    await screen.findByText('实时赛程（2 场）')
    const meta = document.querySelector('.print-snapshot-meta') as HTMLElement
    expect(meta).toBeTruthy()
    expect(within(meta).getByText('赛事名称：')).toBeTruthy()
    expect(within(meta).getByText('生成时间：')).toBeTruthy()
    expect(within(meta).getByText('当前阶段：')).toBeTruthy()
    expect(within(meta).getByText(/实时系统快照/)).toBeTruthy()
    expect(within(meta).getByText(/非官方秩序册/)).toBeTruthy()
  })

  it('工具区带 no-print，可被打印样式隐藏', async () => {
    installScheduleMocks()
    renderSchedule('admin')
    await screen.findByText('实时赛程（2 场）')
    const tools = document.querySelector('.schedule-tools')
    expect(tools?.className).toContain('no-print')
    expect(within(tools as HTMLElement).getByRole('button', { name: 'A4 打印' })).toBeTruthy()
  })
})

describe('C-D5 Schedule：Public 行为不回归', () => {
  it('public variant 保持既有选手赛程，不渲染实时赛程区块', async () => {
    installScheduleMocks()
    renderSchedule('public')
    expect(await screen.findByRole('heading', { name: '选手赛程' })).toBeTruthy()
    expect(document.querySelector('.console-title-text')?.textContent).toContain('选手赛程')
    expect(screen.queryByText(/实时赛程（/)).toBeNull()
    expect(screen.queryByText('按选手查询')).toBeNull()
    expect(document.querySelector('.print-snapshot-meta')).toBeNull()
    expect(document.querySelector('.schedule-table')).toBeNull()
  })
})

// ------------------------------------------------------------------ 秩序册语义

describe('C-D5 OrderBook：实时快照与官方秩序册必须区分', () => {
  it('没有官方秩序册文件时明确显示“暂未关联官方秩序册”', async () => {
    vi.spyOn(api, 'getOrderBookSnapshot').mockResolvedValue(snapshot())
    renderOrderBook()
    expect(await screen.findByText('官方秩序册：暂未关联官方秩序册')).toBeTruthy()
    const notice = document.querySelector('.order-official-notice') as HTMLElement
    expect(notice).toBeTruthy()
    expect(notice.textContent).toContain('实时赛程快照')
    expect(notice.textContent).toContain('不是赛事方发布的正式秩序册')
    // 不得伪造"已生成"
    expect(notice.textContent).not.toContain('已生成官方秩序册')
  })

  it('打印快照带生成时间与实时快照状态，不冒充官方秩序册', async () => {
    vi.spyOn(api, 'getOrderBookSnapshot').mockResolvedValue(snapshot())
    renderOrderBook()
    await screen.findByText('官方秩序册：暂未关联官方秩序册')
    const footer = document.querySelector('.order-book footer') as HTMLElement
    expect(within(footer).getByText(/生成时间：/)).toBeTruthy()
    expect(within(footer).getByText(/实时系统快照/)).toBeTruthy()
    expect(within(footer).getByText(/非官方秩序册/)).toBeTruthy()
    // 封面标题不得自称 ORDER BOOK
    expect(screen.queryByText(/TOURNAMENT ORDER BOOK/)).toBeNull()
    expect(screen.getByText(/TOURNAMENT LIVE SNAPSHOT/)).toBeTruthy()
  })

  it('打印工具栏带 no-print', async () => {
    vi.spyOn(api, 'getOrderBookSnapshot').mockResolvedValue(snapshot())
    renderOrderBook()
    await screen.findByText('官方秩序册：暂未关联官方秩序册')
    expect(document.querySelector('.order-toolbar')?.className).toContain('no-print')
  })

  it('失效 tid 不无限 loading', async () => {
    const spy = vi.spyOn(api, 'getOrderBookSnapshot')
    renderOrderBook('/orderbook?tid=abc')
    expect(await screen.findByText(/请先在/)).toBeTruthy()
    expect(screen.queryByText(/正在整理赛事资料/)).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })

  it('加载失败给出错误与重试', async () => {
    vi.spyOn(api, 'getOrderBookSnapshot').mockRejectedValue(new ApiError(500, '服务暂时不可用'))
    renderOrderBook()
    expect(await screen.findByText(/加载失败：服务暂时不可用/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  })

  it('空签表与空比赛时使用明确占位文案', async () => {
    vi.spyOn(api, 'getOrderBookSnapshot').mockResolvedValue(snapshot({ matches: [] }))
    renderOrderBook()
    await screen.findByText('官方秩序册：暂未关联官方秩序册')
    expect(screen.getByText(/生成比赛后显示完整赛程与球台安排/)).toBeTruthy()
    expect(screen.getByText(/小组赛完成并生成淘汰赛后显示签表/)).toBeTruthy()
  })
})
