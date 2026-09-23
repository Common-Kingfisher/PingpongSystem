/**
 * Public 只读视图的「空态 / 不适用 / 无管理入口」回归测试（D 轨 Day 4D）。
 *
 * 覆盖三件事：
 *
 * 1. **深链接稳定**：`/public/t/:tid/rankings`、`/public/t/:tid/bracket` 即使对该场赛事
 *    “不适用 / 还没有数据”，也只能落到可理解的空态 + CTA —— 不允许白屏、404、
 *    API 报错、重定向循环，也不允许留一片空白；
 * 2. **既有主链不退化**：后端真的返回排名行 / 签表时，页面照常渲染，空态不出现；
 * 3. **无管理入口**：Public 页面不出现管理端导航（`/console`、`/players` …）、
 *    “返回首页”去 `/`、录分按钮、生成签表按钮。
 *
 * ⚠️ 本文件**不**测试「按赛制（ROUND_ROBIN / SINGLE_ELIMINATION / GROUP_KNOCKOUT）显隐入口」：
 * 那依赖 A 轨 `TournamentOut.format_code` 与 B 轨 Handler 进入 master，
 * 尚未合入时前端**不发明临时契约**（见 `docs/WORKSTREAM_D.md` Day 4D 章节）。
 * 因此这里断言的是“三种赛制都成立”的中性空态，而不是赛制判定结果。
 *
 * 测试策略与 `PublicRoutes.test.tsx` 一致：渲染真实 `App`，只把网络层换成可控录制器。
 */

/// <reference types="vitest/globals" />
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const TID = 12
/** localStorage 里预置的“另一场赛事”，用于证明路径优先（与本文件空态断言正交，但保留防回退语义） */
const STORAGE_TID = 99
const STORAGE_KEY = 'pingpong_active_tournament_id'

function tournament(overrides: Record<string, unknown> = {}) {
  return {
    id: TID,
    name: 'Day4D 测试赛事',
    date: '2026-01-01',
    table_count: 4,
    group_count: 2,
    qualify_per_group: 2,
    event_type: 'SINGLES',
    bronze_mode: 'JOINT_BRONZE',
    placement_mode: 'OFF',
    games_to_win: 2,
    points_to_win: 11,
    roster_confirmed: 0,
    operation_mode: 'LIVE',
    stage: 'REGISTRATION',
    ...overrides,
  }
}

const DASHBOARD = {
  stats: { total: 0, finished: 0, playing: 0, waiting: 0 },
  tables: [],
  next_playable: [],
}

function rankingEntry(playerId: number, name: string, rank: number, qualified: boolean) {
  return {
    player_id: playerId,
    name,
    wins: 3,
    losses: 0,
    games_won: 6,
    games_lost: 1,
    rank,
    tied: false,
    qualified,
    match_points: 9,
    points_won: 66,
    points_lost: 40,
    point_difference: 26,
    point_ratio: 1.65,
  }
}

function groupRanking(groupName: string, entries: unknown[]) {
  return {
    group_id: 1,
    group_name: groupName,
    qualify_count: 2,
    total_matches: 6,
    finished_matches: 6,
    ambiguous_qualification: false,
    needs_point_scores: false,
    point_score_match_ids: [],
    manually_resolved: false,
    manual_candidate_entry_ids: [],
    manual_slots_remaining: 0,
    entries,
  }
}

function koMatch(
  id: number,
  round: number,
  matchIndex: number,
  a: { id: number; name: string; seed_no?: number } | null,
  b: { id: number; name: string; seed_no?: number } | null,
) {
  return {
    id,
    round,
    match_index: matchIndex,
    status: 'WAITING',
    player_a: a,
    player_b: b,
    player_a_score: null,
    player_b_score: null,
    winner_id: null,
    table_id: null,
    prev_match_a_id: null,
    prev_match_b_id: null,
    bracket: 'MAIN',
  }
}

function knockoutTree(rounds: unknown[], champion: unknown = null, runnerUp: unknown = null) {
  return {
    tournament: tournament(),
    rounds,
    champion,
    runner_up: runnerUp,
    placements: [],
    placement_matches: [],
    champion_path_match_ids: [],
  }
}

const EMPTY_TREE = knockoutTree([])

/** 后端返回的排名 / 签表可按用例替换 */
let rankingsBody: unknown = { rankings: [] }
let knockoutBody: unknown = EMPTY_TREE
let tournamentStage = 'REGISTRATION'
let requestedPaths: string[] = []

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function installFetchRecorder() {
  requestedPaths = []
  vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    requestedPaths.push(path)

    const id = Number(/\/api\/tournaments\/(\d+)/.exec(path)?.[1] ?? 0)
    if (/\/api\/tournaments\/(\d+)(\?|$)/.test(path)) {
      if (id === STORAGE_TID) {
        return Promise.resolve(jsonResponse(tournament({ id: STORAGE_TID, name: 'LOCALSTORAGE-TRAP-99' })))
      }
      return Promise.resolve(jsonResponse(tournament({ stage: tournamentStage })))
    }
    if (/\/dashboard$/.test(path)) return Promise.resolve(jsonResponse(DASHBOARD))
    if (/\/rankings$/.test(path)) return Promise.resolve(jsonResponse(rankingsBody))
    if (/\/groups$/.test(path)) return Promise.resolve(jsonResponse({ groups: [] }))
    if (/\/knockout$/.test(path)) return Promise.resolve(jsonResponse(knockoutBody))
    return Promise.resolve(jsonResponse([]))
  })
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

/** 页面上所有 <a> 的 href */
function hrefs(): string[] {
  return Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href') ?? '')
}

/** 管理端入口（Public 页面一律不得出现） */
const ADMIN_PREFIXES = ['/console', '/players', '/preflight', '/journey', '/orderbook', '/team-', '/match-print']

beforeEach(() => {
  localStorage.clear()
  rankingsBody = { rankings: [] }
  knockoutBody = EMPTY_TREE
  tournamentStage = 'REGISTRATION'
  installFetchRecorder()
})

afterEach(() => {
  // 本仓库的 vitest 未开启 globals，@testing-library/react 的自动 cleanup 因此不会生效；
  // 不显式 cleanup 会让上一个用例的 DOM 残留，产生 "Found multiple elements" 假失败。
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Public 深链接空态：不适用视图必须可读、可返回', () => {
  it('排名页没有排名行时显示空态，并给出指向本赛事签表的 CTA', async () => {
    renderAt(`/public/t/${TID}/rankings`)

    expect(await screen.findByText('暂无赛事排名')).toBeTruthy()
    const cta = screen.getByRole('link', { name: '查看签表' })
    expect(cta.getAttribute('href')).toBe(`/public/t/${TID}/bracket`)
  })

  it('排名页在 Public 下使用中性标题「赛事排名」，不再强制叫「小组排名」', async () => {
    renderAt(`/public/t/${TID}/rankings`)

    await screen.findByText('暂无赛事排名')
    const heading = screen.getByRole('heading', { level: 2 })
    expect(heading.textContent).toContain('赛事排名')
    expect(heading.textContent).not.toContain('小组排名')
  })

  it('签表页既无签表也无小组赛时显示空态，并给出指向本赛事排名的 CTA', async () => {
    renderAt(`/public/t/${TID}/bracket`)

    expect(await screen.findByText('暂无淘汰赛签表')).toBeTruthy()
    expect(screen.getByRole('link', { name: '查看排名' }).getAttribute('href')).toBe(
      `/public/t/${TID}/rankings`,
    )
    // 旧文案只对“小组 + 淘汰赛”成立，V0.3 的循环赛 / 单淘汰赛事会误导观众
    expect(screen.queryByText('小组赛对阵尚未发布，请稍后再查看。')).toBeNull()
  })

  it('空态不会调用任何写接口（生成签表 / 录分 / Demo 模拟）', async () => {
    renderAt(`/public/t/${TID}/bracket`)
    await screen.findByText('暂无淘汰赛签表')

    const writes = requestedPaths.filter(
      (p) => p.includes('generate-knockout') || p.includes('/score') || p.includes('finish-group-stage'),
    )
    expect(writes).toEqual([])
  })

  it('排名 / 签表空态仍然只指向本赛事，不退回 ?tid= 或 localStorage 里的其他赛事', async () => {
    localStorage.setItem(STORAGE_KEY, String(STORAGE_TID))

    renderAt(`/public/t/${TID}/rankings`)
    await screen.findByText('暂无赛事排名')

    expect(hrefs().filter((h) => h.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
    expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
  })
})

describe('Public 既有主链不退化：有数据时照常渲染', () => {
  it('后端有排名行时渲染名次表，且不出现空态', async () => {
    rankingsBody = {
      rankings: [groupRanking('A组', [rankingEntry(1, '甲选手', 1, true), rankingEntry(2, '乙选手', 2, false)])],
    }

    renderAt(`/public/t/${TID}/rankings`)

    expect(await screen.findByRole('heading', { name: /A组/ })).toBeTruthy()
    expect(screen.getByText(/甲选手/)).toBeTruthy()
    expect(screen.queryByText('暂无赛事排名')).toBeNull()
  })

  it('后端有签表时渲染签表，且不出现空态、不出现录分按钮', async () => {
    knockoutBody = knockoutTree([
      {
        round: 1,
        label: '半决赛',
        matches: [
          koMatch(101, 1, 0, { id: 1, name: '甲选手', seed_no: 1 }, { id: 2, name: '乙选手' }),
          koMatch(102, 1, 1, { id: 3, name: '丙选手' }, { id: 4, name: '丁选手' }),
        ],
      },
    ])

    renderAt(`/public/t/${TID}/bracket`)

    expect(await screen.findByRole('heading', { name: '半决赛' })).toBeTruthy()
    expect(screen.getByText(/甲选手/)).toBeTruthy()
    expect(screen.queryByText('暂无淘汰赛签表')).toBeNull()
    expect(screen.queryByRole('button', { name: '录入大比分' })).toBeNull()
    expect(screen.queryByRole('button', { name: /生成淘汰赛签表/ })).toBeNull()
  })
})

describe('Public 页面没有管理入口', () => {
  it('排名页不出现管理端导航 / 录分 / Demo 模拟 / 指向管理首页的返回链接', async () => {
    renderAt(`/public/t/${TID}/rankings`)
    await screen.findByText('暂无赛事排名')

    const all = hrefs()
    for (const prefix of ADMIN_PREFIXES) {
      expect(all.filter((h) => h.startsWith(prefix))).toEqual([])
    }
    expect(all).not.toContain('/')
    expect(all).toContain(`/public/t/${TID}/live`)
    expect(screen.getByRole('link', { name: /返回实况/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /模拟完成剩余小组赛/ })).toBeNull()
  })

  it('签表页不出现管理端导航 / 生成签表 / 冠军之路 / 秩序册', async () => {
    renderAt(`/public/t/${TID}/bracket`)
    await screen.findByText('暂无淘汰赛签表')

    const all = hrefs()
    for (const prefix of ADMIN_PREFIXES) {
      expect(all.filter((h) => h.startsWith(prefix))).toEqual([])
    }
    expect(all).not.toContain('/')
    expect(screen.queryByRole('link', { name: '冠军之路' })).toBeNull()
    expect(screen.queryByRole('link', { name: '打印秩序册' })).toBeNull()
  })
})

describe('Public 未知子路径与实况页的多状态展示', () => {
  it('未知 Public 子路径安全回到本赛事实况页（不白屏）', async () => {
    renderAt(`/public/t/${TID}/no-such-view`)

    await waitFor(() =>
      expect(requestedPaths.some((p) => /\/dashboard$/.test(p) && p.includes(`/tournaments/${TID}`))).toBe(true),
    )
  })

  it('已结束且本赛事没有签表时，大屏展示后端发布的「赛事排名」', async () => {
    tournamentStage = 'FINISHED'
    rankingsBody = { rankings: [groupRanking('A组', [rankingEntry(1, '冠军候选人', 1, false)])] }

    renderAt(`/public/t/${TID}/live`)

    expect(await screen.findByRole('heading', { name: '赛事排名' })).toBeTruthy()
    expect(screen.getByText(/冠军候选人/)).toBeTruthy()
    expect(screen.getByText(/比赛进度/)).toBeTruthy()
  })

  it('已结束且有冠军时，大屏展示冠军且不额外叠加「赛事排名」', async () => {
    tournamentStage = 'FINISHED'
    rankingsBody = { rankings: [groupRanking('A组', [rankingEntry(1, '冠军候选人', 1, false)])] }
    knockoutBody = knockoutTree(
      [
        {
          round: 1,
          label: '决赛',
          matches: [koMatch(201, 1, 0, { id: 1, name: '决赛甲' }, { id: 2, name: '决赛乙' })],
        },
      ],
      { id: 1, name: '决赛甲' },
      { id: 2, name: '决赛乙' },
    )

    renderAt(`/public/t/${TID}/live`)

    // 「决赛甲」在冠军区与签表卡片里都会出现，因此用 findAllByText 断言“确实渲染了”
    expect(await screen.findAllByText(/决赛甲/)).not.toHaveLength(0)
    expect(screen.queryByRole('heading', { name: '赛事排名' })).toBeNull()
  })
})
