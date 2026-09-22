/**
 * D 轨 Day 3 —— 路由切换时的陈旧响应（stale response）回归测试。
 *
 * ## 被测缺陷
 *
 * React Router 在同一路由 pattern 下切换 `:tid` / `:matchId` 时，`MobileScorePage`
 * **不会 remount**，只有 props 变化。旧实现里 `load()` 自己 `setData(...)`，于是：
 *
 * ```text
 * 打开 /admin/t/A/score/X（关键 GET 悬挂）
 *   → 同 SPA 导航到 /admin/t/B/score/Y，B/Y 先完成并正确显示
 *   → 释放 A/X 旧请求，旧响应晚返回 → setData(A/X) 覆盖页面
 * ```
 *
 * 最危险的结果是「页面显示 A/X，但提交目标已经是 B/Y」——现场录分会写到别的比赛上。
 *
 * ## 测试手法（真实竞态，不规避）
 *
 * 1. 用 deferred promise 让 A 的 `GET /api/tournaments/A/matches` **真正悬挂**；
 * 2. 在**同一个 MemoryRouter / 同一次 render** 内导航到 B/Y（不重新 mount 一套测试 App）；
 * 3. 等 B/Y 显示完成；
 * 4. 再释放 A 的旧请求，让它晚返回；
 * 5. 断言页面仍是 B/Y、A 的信息不出现，并且最终提交只命中 Y。
 *
 * 路由使用**生产环境的真实 adapter**（`MobileScoreRoutes.tsx::AdminScoreAdapter`）；
 * 测试只在外层注入一个导航探针，因为录分页本身刻意不含任何跳转链接。
 */

/// <reference types="vitest/globals" />
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminScoreAdapter } from '../MobileScoreRoutes'
import type { Match } from '../api'

/** A/X：先打开、请求被悬挂的旧比赛 */
const TID_A = 31
const MATCH_X = 3101
/** B/Y：导航过去、必须保持显示的新比赛 */
const TID_B = 32
const MATCH_Y = 3201

const STORAGE_TID = 99
const STORAGE_KEY = 'pingpong_active_tournament_id'

const TOURNAMENT_A = {
  id: TID_A,
  name: 'TID-A-THIRTY-ONE 赛事',
  date: '2026-01-01',
  table_count: 2,
  group_count: 1,
  qualify_per_group: 1,
  event_type: 'SINGLES',
  bronze_mode: 'JOINT_BRONZE',
  placement_mode: 'OFF',
  games_to_win: 2,
  points_to_win: 11,
  roster_confirmed: 1,
  operation_mode: 'LIVE',
  stage: 'GROUP_STAGE',
}

const TOURNAMENT_B = { ...TOURNAMENT_A, id: TID_B, name: 'TID-B-THIRTY-TWO 赛事' }

/** A 与 B 的选手名刻意完全不同，便于断言“A 的名字绝不能出现在最终页面” */
const PLAYERS_A = [
  { id: 901, tournament_id: TID_A, name: 'AAA选手一', seed: null, group_id: null, active: 1 },
  { id: 902, tournament_id: TID_A, name: 'AAA选手二', seed: null, group_id: null, active: 1 },
]
const PLAYERS_B = [
  { id: 911, tournament_id: TID_B, name: 'BBB选手一', seed: null, group_id: null, active: 1 },
  { id: 912, tournament_id: TID_B, name: 'BBB选手二', seed: null, group_id: null, active: 1 },
]

const GROUPS = { groups: [] }

function matchFor(tid: number, matchId: number, overrides: Partial<Match> = {}): Match {
  return {
    id: matchId,
    tournament_id: tid,
    stage: 'GROUP',
    group_id: null,
    round: 1,
    match_index: 1,
    player_a_id: null,
    player_b_id: null,
    player_a_score: null,
    player_b_score: null,
    winner_id: null,
    table_id: null,
    status: 'PLAYING',
    prev_match_a_id: null,
    prev_match_b_id: null,
    entry_a_id: tid * 1000 + 1,
    entry_b_id: tid * 1000 + 2,
    winner_entry_id: null,
    entry_a_name: tid === TID_A ? 'AAA选手一' : 'BBB选手一',
    entry_b_name: tid === TID_A ? 'AAA选手二' : 'BBB选手二',
    result_type: null,
    forfeit_entry_id: null,
    result_note: null,
    bracket: 'GROUP',
    games: [],
    ...overrides,
  }
}

const MATCH_X_RECORD = matchFor(TID_A, MATCH_X)
const MATCH_Y_RECORD = matchFor(TID_B, MATCH_Y)

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** 可手动释放的 deferred，用于真实制造“旧请求晚返回”。 */
function createDeferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

let requestedPaths: string[] = []
let scorePostPaths: string[] = []
let scorePostBodies: Record<string, unknown>[] = []
/** tid → 是否让该赛事的 GET /matches 悬挂（延迟） */
let deferMatchesFor: Set<number>
let deferredMatches: Map<number, ReturnType<typeof createDeferred<Response>>>
/**
 * 服务端当前的比赛事实。
 *
 * 必须在 POST 成功后更新：页面提交成功后会**重新拉取真实 Match**，
 * 如果 GET 仍返回 PLAYING，页面保持表单才是正确行为（否则测试会误判）。
 */
let currentMatches: Map<number, Match>

function installFetchStub() {
  requestedPaths = []
  scorePostPaths = []
  scorePostBodies = []
  deferMatchesFor = new Set()
  deferredMatches = new Map()
  currentMatches = new Map([
    [MATCH_X, MATCH_X_RECORD],
    [MATCH_Y, MATCH_Y_RECORD],
  ])

  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    const method = init?.method ?? 'GET'
    requestedPaths.push(`${method} ${path}`)

    const scorePost = /\/api\/matches\/(\d+)\/score$/.exec(path)
    if (method === 'POST' && scorePost) {
      const postedMatchId = Number(scorePost[1])
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      scorePostPaths.push(path)
      scorePostBodies.push(body)
      const record = postedMatchId === MATCH_Y ? MATCH_Y_RECORD : MATCH_X_RECORD
      // 服务端接受了本次比分：后续 GET 必须看到已结束的真实状态
      const finished: Match = {
        ...record,
        status: 'FINISHED',
        player_a_score: (body.player_a_score as number | null) ?? null,
        player_b_score: (body.player_b_score as number | null) ?? null,
        result_type: 'NORMAL',
      }
      currentMatches.set(postedMatchId, finished)
      return Promise.resolve(jsonResponse(finished))
    }

    const tid = Number(/\/api\/tournaments\/(\d+)/.exec(path)?.[1] ?? 0)
    const forTournament = (id: number) =>
      [...currentMatches.values()].filter((item) => item.tournament_id === id)

    // 关键：A 的比赛列表被悬挂住，模拟“旧请求尚未返回”
    if (/\/matches$/.test(path) && deferMatchesFor.has(tid)) {
      const existing = deferredMatches.get(tid)
      if (existing) return existing.promise
      const deferred = createDeferred<Response>()
      deferredMatches.set(tid, deferred)
      return deferred.promise
    }

    if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) {
      return Promise.resolve(jsonResponse(tid === TID_A ? TOURNAMENT_A : TOURNAMENT_B))
    }
    if (/\/matches$/.test(path)) {
      return Promise.resolve(jsonResponse(forTournament(tid)))
    }
    if (/\/players$/.test(path)) {
      return Promise.resolve(jsonResponse(tid === TID_A ? PLAYERS_A : PLAYERS_B))
    }
    if (/\/groups$/.test(path)) return Promise.resolve(jsonResponse(GROUPS))
    if (/\/dashboard$/.test(path)) {
      return Promise.resolve(jsonResponse({ stats: {}, tables: [], next_playable: [] }))
    }
    return Promise.resolve(jsonResponse([]))
  })
}

/**
 * 测试专用导航探针。
 *
 * 录分页是“一场比赛一页”，刻意没有任何跳转入口，所以竞态导航必须由测试提供。
 * 它只负责在**同一次 render** 内切换路由，不参与任何页面逻辑。
 */
function RaceProbe({ to }: { to: string }) {
  const navigate = useNavigate()
  return (
    <button onClick={() => navigate(to)} type="button">
      导航到 {to}
    </button>
  )
}

/** 使用**生产环境真实 adapter** 的路由树；探针只注入到外层。 */
function renderRace({ to }: { to: string }) {
  return render(
    <MemoryRouter initialEntries={[`/admin/t/${TID_A}/score/${MATCH_X}`]}>
      <RaceProbe to={to} />
      <Routes>
        <Route element={<AdminScoreAdapter />} path="/admin/t/:tid/score/:matchId" />
      </Routes>
    </MemoryRouter>,
  )
}

async function waitForPage(name: string) {
  await screen.findByText(name)
  await screen.findByRole('button', { name: '确认提交大比分' })
}

/** 让微任务/promise 链跑完（旧响应“晚返回”）。 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 60))

beforeEach(() => {
  localStorage.clear()
  installFetchStub()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('路由切换：陈旧响应不得覆盖新比赛页面', () => {
  it('A/X 请求晚返回时页面仍显示 B/Y，且提交只命中 Y', async () => {
    // localStorage 里放另一场赛事，顺带证明路径参数优先
    localStorage.setItem(STORAGE_KEY, String(STORAGE_TID))
    deferMatchesFor.add(TID_A)

    renderRace({ to: `/admin/t/${TID_B}/score/${MATCH_Y}` })

    // Step 1：A/X 处于加载中（关键 GET 被悬挂）
    await waitFor(() => expect(document.querySelector('.ms-loading')).not.toBeNull())
    expect(screen.queryByText(TOURNAMENT_A.name)).toBeNull()

    // Step 2：同 SPA 导航到 B/Y（不重新 mount 测试 App）
    fireEvent.click(screen.getByRole('button', { name: /导航到/ }))

    // Step 3：B/Y 必须正常显示
    await waitForPage(TOURNAMENT_B.name)
    expect(screen.getAllByText('BBB选手一').length).toBeGreaterThan(0)
    expect(screen.getAllByText('BBB选手二').length).toBeGreaterThan(0)

    // Step 4：释放 A/X 的旧请求，让它“晚返回”
    deferredMatches.get(TID_A)?.resolve(jsonResponse([MATCH_X_RECORD]))
    await settle()

    // Step 5：页面必须仍然是 B/Y
    expect(screen.getByText(TOURNAMENT_B.name)).toBeTruthy()
    expect(screen.getAllByText('BBB选手一').length).toBeGreaterThan(0)
    expect(screen.getAllByText('BBB选手二').length).toBeGreaterThan(0)
    expect(screen.queryByText(TOURNAMENT_A.name)).toBeNull()
    expect(screen.queryByText('AAA选手一')).toBeNull()
    expect(screen.queryByText('AAA选手二')).toBeNull()
    expect(screen.queryByText('比赛不存在')).toBeNull()

    // 提交目标仍必须是 Y：填分并提交
    fireEvent.change(screen.getByLabelText('BBB选手一 大比分'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('BBB选手二 大比分'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: '确认提交大比分' }))

    await settle()
    await settle()
    await screen.findAllByText('比分已保存')

    expect(scorePostPaths).toEqual([`/api/matches/${MATCH_Y}/score`])
    expect(scorePostPaths).not.toContain(`/api/matches/${MATCH_X}/score`)
    expect(scorePostBodies).toHaveLength(1)
    expect(scorePostBodies[0].player_a_score).toBe(2)
    expect(scorePostBodies[0].player_b_score).toBe(1)
  })

  it('A/X 旧请求晚返回时不得把已显示 B/Y 的页面改成“比赛不存在”', async () => {
    // 覆盖“match 不存在也必须在 generation 保护之内”：A 的悬挂请求释放后返回
    // 一个**不含 X** 的比赛列表 —— 若旧代码在 load() 内写 failure，B/Y 会被改写。
    deferMatchesFor.add(TID_A)

    renderRace({ to: `/admin/t/${TID_B}/score/${MATCH_Y}` })

    await waitFor(() => expect(document.querySelector('.ms-loading')).not.toBeNull())
    fireEvent.click(screen.getByRole('button', { name: /导航到/ }))
    await waitForPage(TOURNAMENT_B.name)

    deferredMatches.get(TID_A)?.resolve(jsonResponse([]))
    await settle()

    expect(screen.queryByText('比赛不存在')).toBeNull()
    expect(screen.getByText(TOURNAMENT_B.name)).toBeTruthy()
    expect(screen.getAllByText('BBB选手一').length).toBeGreaterThan(0)
  })

  it('B/Y 显示期间不出现上一场的错误态或“已保存/刷新失败”提示', async () => {
    // 覆盖渲染分支：旧上下文留下的失败态与 savedMatch / refreshWarning 都必须已被重置，
    // 否则裁判会在新比赛页面上看到上一场的提示。
    deferMatchesFor.add(TID_A)

    renderRace({ to: `/admin/t/${TID_B}/score/${MATCH_Y}` })

    await waitFor(() => expect(document.querySelector('.ms-loading')).not.toBeNull())
    fireEvent.click(screen.getByRole('button', { name: /导航到/ }))
    await waitForPage(TOURNAMENT_B.name)

    deferredMatches.get(TID_A)?.resolve(jsonResponse([MATCH_X_RECORD]))
    await settle()

    expect(screen.queryByText('比赛不存在')).toBeNull()
    expect(screen.queryByText(/最新状态刷新失败/)).toBeNull()
    expect(screen.queryByText('比分已保存')).toBeNull()
    expect(screen.getByText(TOURNAMENT_B.name)).toBeTruthy()
    expect(screen.getAllByText('BBB选手一').length).toBeGreaterThan(0)
    // 全程没有任何提交发生
    expect(scorePostPaths).toEqual([])
  })
})
