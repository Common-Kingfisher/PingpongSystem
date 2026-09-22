/**
 * 手机录分页测试（D 轨 Day 3）。
 *
 * 覆盖（对应 Day 3 验收条款）：
 *
 * 1. 载荷契约：只录大比分时**不携带 games**；完整小比分同次提交；异常结果不带 games；
 * 2. 提交后**重新拉取真实 Match**，完成态由服务端状态驱动（不靠本地 state 假装 FINISHED）；
 * 3. 后端 422 业务错误原样展示，且**不清空**用户已输入的数据；
 * 4. 防重复提交：连点只发出一次请求，且提交期间按钮 disabled / 显示“提交中…”；
 * 5. 路由：赛事上下文只来自 URL path（`/admin/t/:tid/matches/:matchId/score`），
 *    绝不回退到 `localStorage.activeTournamentId`，也不从别的赛事读比赛。
 *
 * Route ownership（哪些 `/admin/...` 属于 D 轨、哪些必须交还 A/C）由
 * `MobileScoreRouteOwnership.test.tsx` 单独覆盖。
 *
 * 测试策略：渲染**真实** `App`（含真实路由分支），只替换网络层 `fetch`。
 * 断言落在真实请求 URL / 请求体上，而不是只断言页面文案 —— 否则“页面看起来对、
 * 实际打到别的赛事”这类缺陷会被漏掉（Day 2 的 PR #44 P1 正是这一种）。
 */

/// <reference types="vitest/globals" />
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { Match } from '../api'

/** URL 里指定的赛事与比赛 */
const URL_TID = 12
const MATCH_ID = 345
/** localStorage 里预置的“另一场赛事”，用于证明 path 优先 */
const STORAGE_TID = 99
const STORAGE_KEY = 'pingpong_active_tournament_id'
const OPERATOR_KEY = 'pingpong_referee_name'

const TOURNAMENT = {
  id: URL_TID,
  name: 'D3 手机录分测试赛',
  date: '2026-01-01',
  table_count: 4,
  group_count: 2,
  qualify_per_group: 2,
  event_type: 'SINGLES',
  bronze_mode: 'JOINT_BRONZE',
  placement_mode: 'OFF',
  games_to_win: 2,
  points_to_win: 11,
  roster_confirmed: 1,
  operation_mode: 'LIVE',
  stage: 'GROUP_STAGE',
}

const STORAGE_TOURNAMENT = { ...TOURNAMENT, id: STORAGE_TID, name: 'LOCALSTORAGE-TRAP-99' }

const PLAYERS = [
  { id: 1, tournament_id: URL_TID, name: '张三', seed: null, group_id: 7, active: 1 },
  { id: 2, tournament_id: URL_TID, name: '李四', seed: null, group_id: 7, active: 1 },
]

const GROUPS = {
  groups: [
    {
      id: 7,
      tournament_id: URL_TID,
      name: 'A组',
      qualify_count: 2,
      players: [],
    },
  ],
}

const DASHBOARD = {
  stats: { total: 1, finished: 0, playing: 0, waiting: 1 },
  tables: [{ id: 5, name: '1 号台', status: 'OCCUPIED', match: null, recommended_match_id: null }],
  next_playable: [],
}

function baseMatch(overrides: Partial<Match> = {}): Match {
  return {
    id: MATCH_ID,
    tournament_id: URL_TID,
    stage: 'GROUP',
    group_id: 7,
    round: 1,
    match_index: 1,
    player_a_id: 1,
    player_b_id: 2,
    player_a_score: null,
    player_b_score: null,
    winner_id: null,
    table_id: 5,
    status: 'PLAYING',
    prev_match_a_id: null,
    prev_match_b_id: null,
    entry_a_id: 101,
    entry_b_id: 102,
    winner_entry_id: null,
    entry_a_name: '张三',
    entry_b_name: '李四',
    result_type: null,
    forfeit_entry_id: null,
    result_note: null,
    bracket: 'GROUP',
    games: [],
    ...overrides,
  }
}

/** 已被写入结果的比赛（服务端重新拉取时会返回这个形状）。 */
function finishedMatch(overrides: Partial<Match> = {}): Match {
  return baseMatch({
    status: 'FINISHED',
    player_a_score: 2,
    player_b_score: 1,
    winner_id: 1,
    winner_entry_id: 101,
    result_type: 'NORMAL',
    games: [
      { id: 1, match_id: MATCH_ID, game_no: 1, side_a_score: 11, side_b_score: 7 },
      { id: 2, match_id: MATCH_ID, game_no: 2, side_a_score: 9, side_b_score: 11 },
      { id: 3, match_id: MATCH_ID, game_no: 3, side_a_score: 11, side_b_score: 8 },
    ],
    ...overrides,
  })
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface ServerState {
  /** 比赛列表接口当前返回的比赛（默认未结束；提交成功后可换成已结束的真实状态）。 */
  matches: Match[]
  /**
   * 未结束比赛的 POST /score 响应。
   *
   * ⚠️ 覆盖时必须同时更新 `server.matches` —— 页面在提交成功后会**重新拉取真实比赛**，
   * 只返回响应而不更新列表，会让“服务端已结束、页面仍看到未结束”这种假象混进测试结论。
   */
  onScorePost?: (body: Record<string, unknown>) => Response | Promise<Response>
}

let requestedPaths: string[] = []
let scorePosts: Record<string, unknown>[] = []
let server: ServerState

/** 服务端接受异常结果：写入结果并让后续 GET /matches 返回同一个已结束比赛。 */
function acceptAbnormalResult(overrides: Partial<Match>) {
  const finished = finishedMatch(overrides)
  server.matches = [finished]
  return jsonResponse(finished)
}

function installFetchStub() {
  requestedPaths = []
  scorePosts = []
  server = { matches: [baseMatch()] }

  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    const method = init?.method ?? 'GET'
    requestedPaths.push(`${method} ${path}`)

    if (method === 'POST' && /\/api\/matches\/\d+\/score$/.test(path)) {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      scorePosts.push(body)
      if (server.onScorePost) return Promise.resolve(server.onScorePost(body))
      const scoreA = Number(body.player_a_score)
      const scoreB = Number(body.player_b_score)
      const games = Array.isArray(body.games)
        ? (body.games as { side_a_score: number; side_b_score: number }[]).map((game, index) => ({
            id: index + 1,
            match_id: MATCH_ID,
            game_no: index + 1,
            side_a_score: game.side_a_score,
            side_b_score: game.side_b_score,
          }))
        : []
      // 提交成功后服务端把比赛置为 FINISHED；页面重新拉取时应看到这个状态。
      server.matches = [
        finishedMatch({
          player_a_score: scoreA,
          player_b_score: scoreB,
          winner_id: scoreA > scoreB ? 1 : 2,
          winner_entry_id: scoreA > scoreB ? 101 : 102,
          result_type: String(body.result_type ?? 'NORMAL') as Match['result_type'],
          forfeit_entry_id: (body.forfeit_entry_id as number | null) ?? null,
          result_note: (body.note as string | null) ?? null,
          games,
        }),
      ]
      return Promise.resolve(jsonResponse(server.matches[0]))
    }

    const tid = Number(/\/api\/tournaments\/(\d+)/.exec(path)?.[1] ?? 0)
    if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) {
      return Promise.resolve(jsonResponse(tid === URL_TID ? TOURNAMENT : STORAGE_TOURNAMENT))
    }
    if (/\/matches$/.test(path)) return Promise.resolve(jsonResponse(server.matches))
    if (/\/players$/.test(path)) return Promise.resolve(jsonResponse(PLAYERS))
    if (/\/groups$/.test(path)) return Promise.resolve(jsonResponse(GROUPS))
    if (/\/dashboard$/.test(path)) return Promise.resolve(jsonResponse(DASHBOARD))
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

/** 等到页面加载完成（对阵与提交按钮都出现）。 */
async function waitForReady() {
  await screen.findByText('D3 手机录分测试赛')
  await screen.findByRole('button', { name: '确认提交大比分' })
}

function scoreInput(name: string): HTMLInputElement {
  return screen.getByLabelText(`${name} 大比分`) as HTMLInputElement
}

/** 填写大比分（change 事件与真实用户输入一致地驱动受控组件）。 */
function fillBigScore(a: string, b: string) {
  fireEvent.change(scoreInput('张三'), { target: { value: a } })
  fireEvent.change(scoreInput('李四'), { target: { value: b } })
}

async function submitNormalScore() {
  fireEvent.click(screen.getByRole('button', { name: '确认提交大比分' }))
}

beforeEach(() => {
  localStorage.clear()
  installFetchStub()
})

afterEach(() => {
  // 本仓库 vitest 未开启 globals，@testing-library/react 的自动 cleanup 不会注册；
  // 必须显式清理，否则上一个用例的 DOM 会残留，getByText 会命中多个元素。
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('手机录分路由：赛事/比赛上下文只来自 URL path', () => {
  it('渲染真实录分页，且所有赛事请求都命中 URL 里的 tid', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    // 顶部必须显示：赛事名称 / 阶段 / 球台 / 比赛状态
    expect(screen.getByText('D3 手机录分测试赛')).toBeTruthy()
    expect(screen.getByText(/A组 · 小组赛/)).toBeTruthy()
    expect(screen.getByText('球台：1 号台')).toBeTruthy()
    expect(screen.getByText('进行中')).toBeTruthy()

    // 对阵双方
    expect(screen.getAllByText('张三').length).toBeGreaterThan(0)
    expect(screen.getAllByText('李四').length).toBeGreaterThan(0)

    // 页面自身的请求全部落在 URL 指定的赛事上
    expect(requestedPaths.some((p) => p.includes(`/api/tournaments/${URL_TID}/matches`))).toBe(true)
    expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
  })

  it('URL 与 localStorage 冲突时，URL path 获胜（不读 localStorage 赛事）', async () => {
    localStorage.setItem(STORAGE_KEY, String(STORAGE_TID))

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    expect(screen.queryByText('LOCALSTORAGE-TRAP-99')).toBeNull()
    expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
  })

  it('比赛不属于该赛事时明确报错，且不会去别的赛事里找它', async () => {
    localStorage.setItem(STORAGE_KEY, String(STORAGE_TID))

    renderAt(`/admin/t/${URL_TID}/matches/999999/score`)

    await screen.findByText('比赛不存在')
    expect(screen.getByText(/没有编号为 #999999 的比赛/)).toBeTruthy()
    expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
  })

  it('非法路由参数不渲染录分页，也不发出任何赛事数据请求', async () => {
    localStorage.setItem(STORAGE_KEY, String(STORAGE_TID))

    renderAt(`/admin/t/${URL_TID}/matches/not-a-number/score`)

    await screen.findByText('链接不可用')
    expect(requestedPaths.filter((p) => p.includes('/api/tournaments/'))).toEqual([])
  })

  it('手机录分页不渲染管理端顶部导航（不会出现 11 个管理入口）', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    expect(screen.queryByText('赛事大屏')).toBeNull()
    expect(screen.queryByText('在线报名')).toBeNull()
  })
})

describe('正常比分：只录大比分', () => {
  it('不展开小比分时，payload 不携带 games，且提交后重新拉取真实 Match', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    await screen.findByText('比分已保存')
    expect(scorePosts).toHaveLength(1)

    const body = scorePosts[0]
    expect(body.player_a_score).toBe(2)
    expect(body.player_b_score).toBe(1)
    expect(body.result_type).toBe('NORMAL')
    // 关键：没有伪造逐局小比分（既不是 [] 也不是假局分）
    expect('games' in body).toBe(false)
    expect(body.forfeit_entry_id).toBeUndefined()

    // 提交后重新 GET 该赛事的比赛列表，完成态来自服务端真实状态
    expect(requestedPaths.filter((p) => p === `GET /api/tournaments/${URL_TID}/matches`).length).toBeGreaterThanOrEqual(2)

    // 完成态展示：比分已保存 / 2 : 1 / 比赛已结束
    expect(screen.getByText('比赛已结束')).toBeTruthy()
    expect(screen.getByText('2 : 1')).toBeTruthy()
    expect(screen.getByText('本场只录入了大比分，没有逐局小比分。')).toBeTruthy()
  })

  it('大比分未填完时直接提示，不发请求', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fireEvent.change(scoreInput('张三'), { target: { value: '2' } })
    await submitNormalScore()

    await screen.findByText('请先填写双方大比分。')
    expect(scorePosts).toEqual([])
  })

  it('大比分平局时前端只做基础提示，不发请求（最终判定仍在服务端）', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '2')
    await submitNormalScore()

    await screen.findByText('大比分不能平局，请检查后重新填写。')
    expect(scorePosts).toEqual([])
  })

  it('胜方局数不符合本赛事局制时不在前端阻断，请求照样发给后端并展示服务端 detail', async () => {
    // review 返工：前端不再用 gamesToWin 做业务合法性裁决。
    // 三局两胜里 1:0 业务上非法，但必须允许它走到后端，由后端返回 422。
    server.onScorePost = () => jsonResponse({ detail: '大比分胜局数必须为 2' }, 422)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('1', '0')
    await submitNormalScore()

    await screen.findByText('服务端未接受本次比分：大比分胜局数必须为 2')
    // 请求确实发出去了（前端没有把它挡在本地）
    expect(scorePosts).toHaveLength(1)
    expect(scorePosts[0].player_a_score).toBe(1)
    expect(scorePosts[0].player_b_score).toBe(0)
  })

  it('步进按钮只做 +1 / −1 与下限 0，不受 gamesToWin 限制、也不改动另一方', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    const plusA = screen.getByRole('button', { name: '张三 加一局' })
    const minusB = screen.getByRole('button', { name: '李四 减一局' })

    // 连点 4 次：本赛事是 2 局制，但前端不得用 gamesToWin 当上限
    for (let i = 0; i < 4; i += 1) fireEvent.click(plusA)
    expect(scoreInput('张三').value).toBe('4')
    // 绝不自动改写另一方比分（旧实现会在达到 gamesToWin 时写 1）
    expect(scoreInput('李四').value).toBe('')

    // 下限仍然是 0
    fireEvent.click(minusB)
    fireEvent.click(minusB)
    expect(scoreInput('李四').value).toBe('0')
  })
})

describe('正常比分：可选逐局小比分', () => {
  it('大比分 + 完整小比分可以同次提交，使用 contract 字段 games[].side_a_score/side_b_score', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    fireEvent.click(screen.getByRole('button', { name: '+ 录入逐局小比分（可选）' }))

    const rows: Array<[string, string]> = [
      ['11', '7'],
      ['9', '11'],
      ['11', '8'],
    ]
    rows.forEach(([a, b], index) => {
      fireEvent.change(screen.getByLabelText(`第${index + 1}局张三得分`), { target: { value: a } })
      fireEvent.change(screen.getByLabelText(`第${index + 1}局李四得分`), { target: { value: b } })
    })

    await submitNormalScore()
    await screen.findByText('比分已保存')

    expect(scorePosts).toHaveLength(1)
    expect(scorePosts[0].games).toEqual([
      { side_a_score: 11, side_b_score: 7 },
      { side_a_score: 9, side_b_score: 11 },
      { side_a_score: 11, side_b_score: 8 },
    ])
    // 没有发明 gameScores / roundScores 之类字段
    expect('gameScores' in scorePosts[0]).toBe(false)
    expect('roundScores' in scorePosts[0]).toBe(false)

    // 刷新后逐局小比分正确展示
    expect(screen.getByText('逐局小比分：11-7 / 9-11 / 11-8')).toBeTruthy()
  })

  it('半局数据（只填一边）被拦下，不发请求', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    fireEvent.click(screen.getByRole('button', { name: '+ 录入逐局小比分（可选）' }))
    fireEvent.change(screen.getByLabelText('第1局张三得分'), { target: { value: '11' } })

    await submitNormalScore()

    await screen.findByText('第 1 局的双方分数都要填写（不能只填一边）。')
    expect(scorePosts).toEqual([])
  })

  it('删除局分后可以重新提交，不再携带被删除的局', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    fireEvent.click(screen.getByRole('button', { name: '+ 录入逐局小比分（可选）' }))
    // 展开后默认 3 行（按大比分 2:1 推导），删到 2 行再补齐
    fireEvent.click(screen.getByRole('button', { name: '删除第 3 局' }))
    fireEvent.change(screen.getByLabelText('第1局张三得分'), { target: { value: '11' } })
    fireEvent.change(screen.getByLabelText('第1局李四得分'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('第2局张三得分'), { target: { value: '11' } })
    fireEvent.change(screen.getByLabelText('第2局李四得分'), { target: { value: '5' } })

    await submitNormalScore()
    await screen.findByText('比分已保存')

    expect(scorePosts[0].games).toEqual([
      { side_a_score: 11, side_b_score: 5 },
      { side_a_score: 11, side_b_score: 5 },
    ])
  })
})

describe('异常结果', () => {
  it.each([
    ['FORFEIT', '主动弃权'],
    ['NO_SHOW', '未到场'],
    ['WALKOVER', '直接晋级（对手未到场）'],
    ['DISQUALIFIED', '取消资格'],
  ])('%s：携带 result_type + forfeit_entry_id，且不伪造 games', async (type, label) => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fireEvent.click(screen.getByRole('button', { name: '异常结果' }))
    fireEvent.change(screen.getByLabelText('结果类型'), { target: { value: type } })
    fireEvent.click(screen.getByRole('radio', { name: '李四' }))
    fireEvent.click(screen.getByRole('button', { name: '提交异常结果' }))

    // 提交前必须二次确认
    await screen.findByText(new RegExp(`确认将本场比赛记录为「${label}」`))
    expect(scorePosts).toEqual([])

    fireEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await screen.findByText('比分已保存')

    expect(scorePosts).toHaveLength(1)
    expect(scorePosts[0].result_type).toBe(type)
    // 李四 = entry_b_id = 102
    expect(scorePosts[0].forfeit_entry_id).toBe(102)
    expect('games' in scorePosts[0]).toBe(false)
    expect(scorePosts[0].player_a_score).toBeUndefined()
  })

  it('未选择异常方时不提交', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fireEvent.click(screen.getByRole('button', { name: '异常结果' }))
    fireEvent.click(screen.getByRole('button', { name: '提交异常结果' }))

    await screen.findByText('请选择异常结果对应的一方。')
    expect(scorePosts).toEqual([])
  })

  it('异常结果完成态显示「李四弃权」，不显示成 2:1 这种正常比分', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    // 小组赛弃权：服务端会为排名写入行政比分 2:0，但页面必须区分展示
    server.onScorePost = (body) =>
      acceptAbnormalResult({
        player_a_score: 2,
        player_b_score: 0,
        winner_id: 1,
        winner_entry_id: 101,
        result_type: 'FORFEIT',
        forfeit_entry_id: Number(body.forfeit_entry_id),
        games: [],
      })

    fireEvent.click(screen.getByRole('button', { name: '异常结果' }))
    fireEvent.click(screen.getByRole('radio', { name: '李四' }))
    fireEvent.click(screen.getByRole('button', { name: '提交异常结果' }))
    fireEvent.click(await screen.findByRole('button', { name: '确认提交' }))

    await screen.findByText('比分已保存')
    expect(screen.getByText('李四弃权')).toBeTruthy()
    expect(screen.getByText('异常结果，没有逐局小比分。')).toBeTruthy()
    expect(screen.getByText(/排名用行政比分：张三 2 : 0 李四/)).toBeTruthy()
    expect(screen.queryByText('2 : 1')).toBeNull()
  })
})

describe('错误处理与防重复提交', () => {
  it('后端 422 业务错误原样展示，且不清空已输入数据', async () => {
    server.onScorePost = () => jsonResponse({ detail: '逐局小比分与大比分不一致' }, 422)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    await screen.findByText('服务端未接受本次比分：逐局小比分与大比分不一致')
    // 输入未被清空，裁判可以直接改
    expect(scoreInput('张三').value).toBe('2')
    expect(scoreInput('李四').value).toBe('1')
    // 页面不得假装成功
    expect(screen.queryByText('比分已保存')).toBeNull()
  })

  it('后端 409 冲突错误展示为“当前比赛状态不允许这样操作”', async () => {
    server.onScorePost = () => jsonResponse({ detail: '只有进行中或待安排的比赛可以录入比分' }, 409)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '0')
    await submitNormalScore()

    await screen.findByText('当前比赛状态不允许这样操作：只有进行中或待安排的比赛可以录入比分')
  })

  it('结构化 401（AUTH_REQUIRED）展示服务端真实 message，而不是“请求失败 (401)”', async () => {
    // A 轨认证契约合入后的真实 401 形状：detail 是对象，由共享 api.ts 统一解析
    server.onScorePost = () =>
      jsonResponse({ detail: { code: 'AUTH_REQUIRED', message: '请先登录' } }, 401)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    await screen.findByText('请先登录后再提交：请先登录')
    expect(document.body.textContent).not.toContain('请求失败 (401)')
    // 输入保留，登录后可以立即重试
    expect(scoreInput('张三').value).toBe('2')
    expect(scoreInput('李四').value).toBe('1')
  })

  it('结构化 404（RESOURCE_NOT_FOUND）原样展示“资源不存在”，不得改写成权限推断', async () => {
    // 跨赛事 / 未授权资源统一 404 RESOURCE_NOT_FOUND，用于防资源枚举。
    // 页面不得把它翻译成“你没有某赛事权限”之类的推断文案。
    server.onScorePost = () =>
      jsonResponse({ detail: { code: 'RESOURCE_NOT_FOUND', message: '资源不存在' } }, 404)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    await screen.findByText('服务端拒绝了本次录分：资源不存在')
    const text = document.body.textContent ?? ''
    expect(text).not.toContain('权限')
    expect(text).not.toContain('请求失败 (404)')
  })

  it('结构化 403（FORBIDDEN）展示服务端 message', async () => {
    server.onScorePost = () =>
      jsonResponse({ detail: { code: 'FORBIDDEN', message: '需要赛事管理员权限' } }, 403)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    await screen.findByText('当前账号没有该操作的权限：需要赛事管理员权限')
  })

  it('网络失败提示检查局域网，且不清空已输入数据', async () => {
    server.onScorePost = () => {
      throw new TypeError('Failed to fetch')
    }

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    await screen.findByText('网络连接失败，请检查局域网连接后重试')
    expect(scoreInput('张三').value).toBe('2')
    expect(scoreInput('李四').value).toBe('1')
  })

  it('score POST 成功但随后刷新失败：必须报“比分已保存 + 刷新失败”，绝不能报“本次未保存”', async () => {
    // review 返工回归：POST 成功、reload 网络失败 —— 旧实现把两者放在同一个 try/catch，
    // 会显示“网络连接失败…”并诱导裁判重复提交，而比分其实已经落库。
    const savedMatch = finishedMatch()
    let reloadShouldFail = false
    server.onScorePost = () => {
      // 服务端接受了本次比分：后续任何一次 GET 都进入“网络故障”状态
      reloadShouldFail = true
      return jsonResponse(savedMatch)
    }

    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const path = raw.replace(/^https?:\/\/[^/]+/, '')
      const method = init?.method ?? 'GET'
      if (reloadShouldFail && method === 'GET' && path.includes('/api/')) {
        return Promise.reject(new TypeError('Failed to fetch'))
      }
      return realFetch(input as RequestInfo, init)
    })

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()

    // 1) 必须明确告诉裁判比分已经保存（提示条与完成卡都会出现该文案）
    expect((await screen.findAllByText('比分已保存')).length).toBeGreaterThan(0)
    // 2) 必须明确提示最新状态刷新失败 / 请重新加载
    expect((await screen.findAllByText(/最新状态刷新失败/)).length).toBeGreaterThan(0)
    expect((await screen.findAllByText(/请重新加载/)).length).toBeGreaterThan(0)
    // 提示条本身必须存在，且不是红色错误样式
    const banner = document.querySelector('.ms-refresh-warning')
    expect(banner).not.toBeNull()
    expect(document.querySelector('.ms-error')).toBeNull()
    // 3) 绝不能出现“本次未保存 / 提交失败”类文案
    expect(document.body.textContent).not.toContain('网络连接失败')
    expect(document.body.textContent).not.toContain('本次比分未保存')
    expect(document.body.textContent).not.toContain('服务端出错')
    // 4) score POST 只发出一次，且完成态里不再存在录分提交按钮（不可能再触发第二次提交）
    expect(scorePosts).toHaveLength(1)
    expect(screen.queryByRole('button', { name: '确认提交大比分' })).toBeNull()
  })

  it('提交期间按钮 disabled 且显示“提交中…”，连点只发出一次请求', async () => {
    // 手动闸门：让 POST 请求悬停在“进行中”，以便观察连点行为
    const gate: { release: (() => void) | null } = { release: null }
    const pending = new Promise<void>((resolve) => {
      gate.release = resolve
    })

    server.onScorePost = async () => {
      await pending
      return jsonResponse(finishedMatch())
    }

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    const button = screen.getByRole('button', { name: '确认提交大比分' })

    // 同一个事件循环内连点 3 次：ref 锁必须只放行一次
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(scorePosts).toHaveLength(1))
    expect((screen.getByRole('button', { name: '提交中…' }) as HTMLButtonElement).disabled).toBe(true)

    gate.release?.()
    await waitFor(() => expect(screen.queryByRole('button', { name: '提交中…' })).toBeNull())
    expect(scorePosts).toHaveLength(1)
  })

  it('被拒绝后可以修改并重新提交（锁被正确释放）', async () => {
    // 服务端拒绝：比赛已被别处改分（409 冲突）
    server.onScorePost = () => jsonResponse({ detail: '只有进行中或待安排的比赛可以录入比分' }, 409)

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '1')
    await submitNormalScore()
    await screen.findByText('当前比赛状态不允许这样操作：只有进行中或待安排的比赛可以录入比分')

    // 解除拒绝后必须还能再提交一次（说明提交锁已释放，页面没有被“卡死”）
    server.onScorePost = undefined
    await submitNormalScore()

    await screen.findByText('比分已保存')
    expect(scorePosts).toHaveLength(2)
    expect(scorePosts[1].player_a_score).toBe(2)
    expect(scorePosts[1].player_b_score).toBe(1)
  })
})

describe('操作人留痕', () => {
  it('填写操作人后随请求提交，并记忆到 localStorage', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fireEvent.change(screen.getByLabelText('操作人（选填）'), { target: { value: '王裁判' } })
    fillBigScore('2', '0')
    await submitNormalScore()

    await screen.findByText('比分已保存')
    expect(scorePosts[0].operator_name).toBe('王裁判')
    expect(localStorage.getItem(OPERATOR_KEY)).toBe('王裁判')
  })

  it('不填操作人时不发送 operator_name（留空不冒充操作人）', async () => {
    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)
    await waitForReady()

    fillBigScore('2', '0')
    await submitNormalScore()

    await screen.findByText('比分已保存')
    expect('operator_name' in scorePosts[0]).toBe(false)
  })
})

describe('已结束比赛：不重开改分流程', () => {
  it('已结束比赛只展示结果，并指向赛事管理端改分', async () => {
    server.matches = [finishedMatch()]

    renderAt(`/admin/t/${URL_TID}/matches/${MATCH_ID}/score`)

    await screen.findByText('比分已保存')
    expect(screen.getByText('比赛已结束')).toBeTruthy()
    expect(screen.getByText(/如需修改结果，请前往赛事管理端/)).toBeTruthy()
    // 本页不提供第二次录分入口
    expect(screen.queryByRole('button', { name: '确认提交大比分' })).toBeNull()
    expect(screen.queryByRole('button', { name: '异常结果' })).toBeNull()
  })
})
