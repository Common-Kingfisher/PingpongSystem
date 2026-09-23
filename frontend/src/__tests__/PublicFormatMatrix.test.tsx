/**
 * Public 多赛制矩阵回归（D 轨 Day4D 接线轮，PR #50 review）。
 *
 * 覆盖 reviewer 要求的矩阵：
 *
 * | 场景 | 期望 |
 * | --- | --- |
 * | PublicLayout 导航 | RR / SE / GK / null 四套可见性 |
 * | `/rankings` 深链 | SINGLE_ELIMINATION → 只读「不设置循环赛排名」+ CTA；GROUP_KNOCKOUT 不退化 |
 * | `/bracket` 深链 | ROUND_ROBIN → 只读「不设置淘汰赛签表」+ CTA；SINGLE_ELIMINATION 渲染真实签表 |
 * | BigScreen | RR 只展示赛事排名、SE 只展示签表、GK / legacy 不退化 |
 *
 * 原则：
 *
 * - 赛制来源只有一个 —— 后端 `Tournament.format_code`（fixture 直接给该字段），
 *   测试**不**按 stage / 有没有 group / 有没有 knockout tree 反推；
 * - fixture 只是后端 DTO 的形状，不实现任何排名或抽签算法；
 * - 不适用的视图不得请求不适用的数据（用请求记录断言）。
 */

/// <reference types="vitest/globals" />
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const TID = 12

/** 只允许 generated contract 里的三个取值 + legacy(null) */
type FormatCase = 'ROUND_ROBIN' | 'SINGLE_ELIMINATION' | 'GROUP_KNOCKOUT' | null

function tournament(formatCode: FormatCase, stage: string) {
  return {
    id: TID,
    name: `赛事-${formatCode ?? 'legacy'}`,
    date: '2026-09-23',
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
    stage,
    format_code: formatCode,
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

const RANKINGS_WITH_GROUP = {
  rankings: [
    {
      group_id: 1,
      group_name: 'A组',
      qualify_count: 2,
      total_matches: 6,
      finished_matches: 6,
      ambiguous_qualification: false,
      needs_point_scores: false,
      point_score_match_ids: [],
      manually_resolved: false,
      manual_candidate_entry_ids: [],
      manual_slots_remaining: 0,
      entries: [rankingEntry(1, '甲选手', 1, true), rankingEntry(2, '乙选手', 2, false)],
    },
  ],
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

function emptyTree() {
  return {
    tournament: tournament('GROUP_KNOCKOUT', 'REGISTRATION'),
    rounds: [],
    champion: null,
    runner_up: null,
    placements: [],
    placement_matches: [],
    champion_path_match_ids: [],
  }
}

/**
 * 单淘汰签表 fixture：含一个 BYE（`player_b === null`）——
 * 它只能由服务端给出，前端只负责渲染成「待定」，不计算 BYE。
 */
function singleEliminationTree(champion: { id: number; name: string } | null = null) {
  return {
    tournament: tournament('SINGLE_ELIMINATION', 'KNOCKOUT'),
    rounds: [
      {
        round: 1,
        label: '半决赛',
        matches: [
          koMatch(101, 1, 0, { id: 1, name: '甲选手', seed_no: 1 }, null),
          koMatch(102, 1, 1, { id: 3, name: '丙选手' }, { id: 4, name: '丁选手' }),
        ],
      },
    ],
    champion,
    runner_up: null,
    placements: [],
    placement_matches: [],
    champion_path_match_ids: [],
  }
}

let requestedPaths: string[] = []
let currentTournament = tournament('GROUP_KNOCKOUT', 'GROUP_STAGE')
let rankingsBody: unknown = RANKINGS_WITH_GROUP
let knockoutBody: unknown = emptyTree()

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function installFetch() {
  requestedPaths = []
  vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    requestedPaths.push(path)

    if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) {
      return Promise.resolve(jsonResponse(currentTournament))
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

/** 只取 Public 主导航里的链接文案（顺序即信息架构） */
function navLabels(): string[] {
  const nav = screen.getByRole('navigation', { name: '公开赛事导航' })
  return within(nav)
    .getAllByRole('link')
    .map((link) => link.textContent ?? '')
}

function hrefs(): string[] {
  return Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href') ?? '')
}

function requestsMatching(pattern: RegExp): string[] {
  return requestedPaths.filter((path) => pattern.test(path))
}

const ADMIN_PREFIXES = ['/console', '/players', '/preflight', '/journey', '/orderbook', '/team-']

beforeEach(() => {
  localStorage.clear()
  currentTournament = tournament('GROUP_KNOCKOUT', 'GROUP_STAGE')
  rankingsBody = RANKINGS_WITH_GROUP
  knockoutBody = emptyTree()
  installFetch()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// --------------------------------------------------------------- 1. 导航矩阵

describe('PublicLayout：赛制 → 导航可见性', () => {
  it('ROUND_ROBIN：实况 / 赛程 / 排名 / 报名（无签表、无冠军）', async () => {
    currentTournament = tournament('ROUND_ROBIN', 'GROUP_STAGE')
    renderAt(`/public/t/${TID}/live`)

    await waitFor(() => expect(navLabels()).toEqual(['实况', '赛程', '排名', '报名']))
    // 阶段徽标不得把循环赛说成「小组赛」
    expect(await screen.findByText('循环赛')).toBeTruthy()
  })

  it('SINGLE_ELIMINATION：实况 / 赛程 / 签表 / 冠军 / 报名（无排名）', async () => {
    currentTournament = tournament('SINGLE_ELIMINATION', 'KNOCKOUT')
    renderAt(`/public/t/${TID}/live`)

    await waitFor(() => expect(navLabels()).toEqual(['实况', '赛程', '签表', '冠军', '报名']))
    expect(await screen.findByText('单淘汰')).toBeTruthy()
  })

  it('GROUP_KNOCKOUT：六个入口全部保留', async () => {
    currentTournament = tournament('GROUP_KNOCKOUT', 'GROUP_STAGE')
    renderAt(`/public/t/${TID}/live`)

    await waitFor(() =>
      expect(navLabels()).toEqual(['实况', '赛程', '排名', '签表', '冠军', '报名']),
    )
  })

  it('legacy（format_code = null）：保持全部可见，不默认成 GROUP_KNOCKOUT 式隐藏', async () => {
    const legacy = tournament(null, 'GROUP_STAGE')
    // 模拟真正的历史赛事：DTO 里连字段都没有
    delete (legacy as { format_code?: unknown }).format_code
    currentTournament = legacy

    renderAt(`/public/t/${TID}/live`)

    await waitFor(() =>
      expect(navLabels()).toEqual(['实况', '赛程', '排名', '签表', '冠军', '报名']),
    )
    // 旧赛事的阶段文案保持既有映射
    expect(await screen.findByText('小组赛')).toBeTruthy()
  })
})

// --------------------------------------------------------------- 2. 排名深链

describe('Rankings 深链', () => {
  it('SINGLE_ELIMINATION：只读「不设置循环赛排名」+ 查看签表，且不请求排名数据', async () => {
    currentTournament = tournament('SINGLE_ELIMINATION', 'KNOCKOUT')
    renderAt(`/public/t/${TID}/rankings`)

    expect(await screen.findByText('本赛事采用单淘汰赛制，不设置循环赛排名。')).toBeTruthy()
    expect(screen.getByText('请查看淘汰赛签表了解晋级情况。')).toBeTruthy()
    expect(screen.getByRole('link', { name: '查看签表' }).getAttribute('href')).toBe(
      `/public/t/${TID}/bracket`,
    )

    // 不适用的数据一个字节都不请求
    expect(requestsMatching(/\/rankings$/)).toEqual([])
    expect(requestsMatching(/\/matches/)).toEqual([])

    // 只读：没有管理入口、没有写请求
    const all = hrefs()
    for (const prefix of ADMIN_PREFIXES) {
      expect(all.filter((h) => h.startsWith(prefix))).toEqual([])
    }
    expect(all).not.toContain('/')
    expect(screen.queryByRole('button', { name: /模拟完成剩余小组赛/ })).toBeNull()
  })

  it('GROUP_KNOCKOUT：仍显示小组排名（主链不退化）', async () => {
    currentTournament = tournament('GROUP_KNOCKOUT', 'GROUP_STAGE')
    renderAt(`/public/t/${TID}/rankings`)

    expect(await screen.findByRole('heading', { name: /A组/ })).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2 }).textContent).toContain('小组排名')
    expect(screen.queryByText('本赛事采用单淘汰赛制，不设置循环赛排名。')).toBeNull()
    expect(requestsMatching(/\/rankings$/).length).toBeGreaterThan(0)
  })

  it('ROUND_ROBIN：标题用中性的「赛事排名」', async () => {
    currentTournament = tournament('ROUND_ROBIN', 'GROUP_STAGE')
    renderAt(`/public/t/${TID}/rankings`)

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2 }).textContent).toContain('赛事排名'),
    )
    expect(screen.getByRole('heading', { level: 2 }).textContent).not.toContain('小组排名')
  })
})

// --------------------------------------------------------------- 3. 签表深链

describe('Bracket 深链', () => {
  it('ROUND_ROBIN：只读「不设置淘汰赛签表」+ 查看排名，且不请求 /knockout', async () => {
    currentTournament = tournament('ROUND_ROBIN', 'GROUP_STAGE')
    renderAt(`/public/t/${TID}/bracket`)

    expect(await screen.findByText('本赛事采用循环赛制，不设置淘汰赛签表。')).toBeTruthy()
    expect(screen.getByText('请查看赛事排名了解当前名次。')).toBeTruthy()
    expect(screen.getByRole('link', { name: '查看排名' }).getAttribute('href')).toBe(
      `/public/t/${TID}/rankings`,
    )

    expect(requestsMatching(/\/knockout$/)).toEqual([])
    expect(requestsMatching(/generate-knockout/)).toEqual([])

    // 不得出现 GROUP_KNOCKOUT 专属语义
    expect(screen.queryByText(/请先完成小组赛/)).toBeNull()
    expect(screen.queryByText(/每组前/)).toBeNull()
    expect(screen.queryByText(/小组赛尚未完成/)).toBeNull()
    expect(screen.queryByRole('button', { name: /生成淘汰赛签表/ })).toBeNull()
  })

  it('SINGLE_ELIMINATION：渲染后端真实签表，BYE 只按服务端数据展示为「待定」', async () => {
    currentTournament = tournament('SINGLE_ELIMINATION', 'KNOCKOUT')
    knockoutBody = singleEliminationTree()
    renderAt(`/public/t/${TID}/bracket`)

    expect(await screen.findByRole('heading', { name: '半决赛' })).toBeTruthy()
    expect(screen.getByText(/甲选手/)).toBeTruthy()
    // BYE 槽位 = 后端给 null，前端只显示「待定」，不自行推算
    expect(screen.getAllByText(/待定/).length).toBeGreaterThan(0)

    // 单淘汰没有小组：不请求排名，也不出现小组赛语义
    expect(requestsMatching(/\/rankings$/)).toEqual([])
    expect(screen.queryByText(/请先完成小组赛/)).toBeNull()
    expect(screen.queryByText(/每组前/)).toBeNull()
    // 只读：无录分 / 生成入口
    expect(screen.queryByRole('button', { name: '录入大比分' })).toBeNull()
    expect(screen.queryByRole('button', { name: /生成淘汰赛签表/ })).toBeNull()
  })

  it('legacy（format_code = null）：保持数据驱动，签表数据到达即渲染', async () => {
    const legacy = tournament(null, 'KNOCKOUT')
    delete (legacy as { format_code?: unknown }).format_code
    currentTournament = legacy
    knockoutBody = singleEliminationTree()
    renderAt(`/public/t/${TID}/bracket`)

    expect(await screen.findByRole('heading', { name: '半决赛' })).toBeTruthy()
    expect(requestsMatching(/\/knockout$/).length).toBeGreaterThan(0)
    expect(screen.queryByText('本赛事采用循环赛制，不设置淘汰赛签表。')).toBeNull()
  })
})

// --------------------------------------------------------------- 4. BigScreen

describe('BigScreen：赛制 → 展示区域与请求集合', () => {
  it('ROUND_ROBIN：展示赛事排名，不展示签表 / 出线区，也不请求 /knockout', async () => {
    currentTournament = tournament('ROUND_ROBIN', 'GROUP_STAGE')
    renderAt(`/public/t/${TID}/live`)

    expect(await screen.findByRole('heading', { name: '赛事排名' })).toBeTruthy()
    expect(screen.getByText(/甲选手/)).toBeTruthy()
    expect(screen.queryByText('小组排名（出线区）')).toBeNull()
    expect(requestsMatching(/\/knockout$/)).toEqual([])
  })

  it('ROUND_ROBIN（已结束）：展示最终赛事排名，不伪造冠军', async () => {
    currentTournament = tournament('ROUND_ROBIN', 'FINISHED')
    renderAt(`/public/t/${TID}/live`)

    expect(await screen.findByRole('heading', { name: '赛事排名' })).toBeTruthy()
    // 没有淘汰签表就没有冠军：不得凭空出现冠军区
    expect(screen.queryByText('🏆')).toBeNull()
  })

  it('SINGLE_ELIMINATION：展示签表与冠军，不展示小组出线区，也不请求 /rankings', async () => {
    currentTournament = tournament('SINGLE_ELIMINATION', 'KNOCKOUT')
    knockoutBody = singleEliminationTree()
    renderAt(`/public/t/${TID}/live`)

    expect(await screen.findByRole('heading', { name: '半决赛' })).toBeTruthy()
    expect(screen.queryByText('小组排名（出线区）')).toBeNull()
    expect(screen.queryByRole('heading', { name: '赛事排名' })).toBeNull()
    expect(requestsMatching(/\/rankings$/)).toEqual([])
  })

  it('GROUP_KNOCKOUT：出线区与签表同时保留（主链不退化）', async () => {
    currentTournament = tournament('GROUP_KNOCKOUT', 'GROUP_STAGE')
    knockoutBody = singleEliminationTree()
    renderAt(`/public/t/${TID}/live`)

    expect(await screen.findByRole('heading', { name: '小组排名（出线区）' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: '半决赛' })).toBeTruthy()
    expect(requestsMatching(/\/rankings$/).length).toBeGreaterThan(0)
    expect(requestsMatching(/\/knockout$/).length).toBeGreaterThan(0)
  })

  it('legacy（format_code = null）：数据驱动，出线区照旧展示', async () => {
    const legacy = tournament(null, 'GROUP_STAGE')
    delete (legacy as { format_code?: unknown }).format_code
    currentTournament = legacy
    renderAt(`/public/t/${TID}/live`)

    expect(await screen.findByRole('heading', { name: '小组排名（出线区）' })).toBeTruthy()
    expect(requestsMatching(/\/knockout$/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('heading', { name: '赛事排名' })).toBeNull()
  })
})
