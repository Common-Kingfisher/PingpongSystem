/**
 * D 轨 Day 3 —— **Route ownership** 回归测试。
 *
 * ## 被测缺陷
 *
 * 早期实现让 D 轨抢占整个 `/admin/*`：
 *
 * ```tsx
 * if (pathname.startsWith('/admin/')) return <MobileScoreRoutes />
 * // 并且 MobileScoreRoutes 内还声明了 <Route path="/admin/*" element={<AdminScoreInvalidLink />} />
 * ```
 *
 * 后果：A/C 轨后续接入的任何管理端 route（`AdminLayout`、`Login`、`AccessState`、
 * `AuthGuard`、`RequireTournamentAccess`、`/admin/events` 等）都会被 D 轨截断。
 *
 * `/admin` 命名空间的**总体所有权属于 A/C 轨**；D 轨只拥有手机录分的**一条精确 path**：
 *
 * ```text
 * /admin/t/:tid/matches/:matchId/score
 * ```
 *
 * ## 测试为什么这样组织
 *
 * 需要证明的是“**D 轨是否接管了某条路径**”，而这件事有两层：
 *
 * 1. **入口判定**（`App.tsx` 用哪个判断决定是否进入 D 轨）；
 * 2. **D 轨 route 表**（进入之后 D 声明了哪些 route）。
 *
 * ⚠️ 踩过的两个坑（都实测过，写在这里避免后人重犯）：
 *
 * - 在外层 `<Routes>` 放 `/admin/*` 哨兵“证明交给外层”是**假测试**：react-router 按
 *   route 打分而不是声明顺序，`/admin/*` 比 `*` 更具体，会先于 `App` 命中，
 *   `App` 根本不被挂载；
 * - 只断言“页面里没有出现 D 的内容”也是**假测试**：D 若被误挂载但自身 route 表已收窄，
 *   它会渲染一棵**空**树，同样“没有出现任何东西”。
 *
 * 因此这里改用两个真正可观测的判据：
 *
 * - **入口判定**：直接对 `App.tsx` 实际调用的 `isMobileScoreRoutePath()` 做决策表断言，
 *   并额外断言 `App.tsx` 源码确实**只用**这一个判断、且**不含** `startsWith('/admin/')`；
 * - **D 轨 route 表**：单独渲染 `MobileScoreRoutes`，断言它只声明 canonical route ——
 *   非 canonical 的 `/admin/...` 下渲染结果必须为**空**（既不显示录分页，也不显示
 *   D 的“链接不可用”页），并断言**没有任何 API 请求**。
 *
 * 校准（calibration）：本文件的两类断言都在“把入口改回 `startsWith('/admin/')`”
 * 与“把 `/admin/*` catch-all 加回去”两种回归下**确实会失败**（见提交说明中的实测记录）。
 */

/// <reference types="vitest/globals" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import MobileScoreRoutes, {
  MOBILE_SCORE_ROUTE_PATH,
  isMobileScoreRoutePath,
} from '../MobileScoreRoutes'

const TID = 31
const MATCH_ID = 401

const TOURNAMENT = {
  id: TID,
  name: 'ROUTE-OWNERSHIP 赛事',
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

const MATCH = {
  id: MATCH_ID,
  tournament_id: TID,
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
  entry_a_id: 4011,
  entry_b_id: 4012,
  winner_entry_id: null,
  entry_a_name: 'OWN-A',
  entry_b_name: 'OWN-B',
  result_type: null,
  forfeit_entry_id: null,
  result_note: null,
  bracket: 'GROUP',
  games: [],
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

let requestedPaths: string[] = []

function installFetchStub() {
  requestedPaths = []
  vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    requestedPaths.push(`GET ${path}`)
    if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) return Promise.resolve(jsonResponse(TOURNAMENT))
    if (/\/matches$/.test(path)) return Promise.resolve(jsonResponse([MATCH]))
    if (/\/players$/.test(path)) return Promise.resolve(jsonResponse([]))
    if (/\/groups$/.test(path)) return Promise.resolve(jsonResponse({ groups: [] }))
    return Promise.resolve(jsonResponse([]))
  })
}

/** 只渲染 **D 轨自己的 route 表**：用来精确断言“D 声明了哪些路径”。 */
function renderMobileScoreRoutes(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MobileScoreRoutes />
    </MemoryRouter>,
  )
}

/** 渲染真实 `App`：用来验证 canonical 路径的端到端行为。 */
function renderAppAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

/** 当前 container 里是否存在 D 轨渲染出来的任何元素。 */
function dTrackRenderedAnything(container: HTMLElement): boolean {
  return container.querySelector('[class^="ms-"], [class*=" ms-"]') !== null
}

beforeEach(() => {
  localStorage.clear()
  installFetchStub()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('入口判定：D 轨只认自己那一条精确 path', () => {
  it('exported pattern 就是 canonical URL（防止两处路径漂移）', () => {
    expect(MOBILE_SCORE_ROUTE_PATH).toBe('/admin/t/:tid/matches/:matchId/score')
  })

  it('App.tsx 只使用这一处精确匹配判定，且不含 /admin 前缀判断', () => {
    // 源码级护栏：把入口改回 `pathname.startsWith('/admin/')` 会被这里拦下，
    // 因为那种写法在行为上无法与“D 的 route 表已收窄”区分（D 会渲染空树）。
    //
    // 注意：先剥掉注释再断言 —— 本文件与 App.tsx 的注释里会**提到**
    // `startsWith('/admin/')` 来说明为什么不能用它，那不是代码。
    const source = readFileSync(join(process.cwd(), 'src', 'App.tsx'), 'utf8')
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, '') // 块注释
      .replace(/(^|[^:])\/\/.*$/gm, '$1') // 行注释（避开 http:// 这类）

    expect(code).toContain('isMobileScoreRoutePath(pathname)')
    expect(code).not.toContain("startsWith('/admin/')")
    expect(code).not.toContain('startsWith("/admin/")')
    expect(code).not.toContain('/admin/*')
  })

  it.each([
    '/admin/t/12/matches/345/score',
    '/admin/t/31/matches/401/score',
  ])('命中：%s', (path) => {
    expect(isMobileScoreRoutePath(path)).toBe(true)
  })

  it.each([
    // 不属于 D 轨的管理端 route：必须交还 A/C
    '/admin/events',
    '/admin/login',
    '/admin/setup',
    '/admin/t/12/settings',
    '/admin/t/12/matches',
    '/admin/t/12/matches/345',
    '/admin/t/12/players',
    // 多一段：完整匹配，不是前缀匹配
    '/admin/t/12/matches/345/score/extra',
    // 旧的非 canonical 录分 URL
    '/admin/t/12/score/345',
    '/admin/t/12/score',
    // 其它命名空间
    '/',
    '/console',
    '/public/t/12/live',
    '/admin',
    '/admin/',
  ])('不命中：%s', (path) => {
    expect(isMobileScoreRoutePath(path)).toBe(false)
  })
})

describe('D 轨 route 表：只声明 canonical 一条 route', () => {
  it('canonical route 会渲染录分页（说明 route 表接线正确）', async () => {
    const { container } = renderMobileScoreRoutes(`/admin/t/${TID}/matches/${MATCH_ID}/score`)

    await screen.findByText('ROUTE-OWNERSHIP 赛事')
    expect(dTrackRenderedAnything(container)).toBe(true)
    expect(requestedPaths.some((p) => p.includes(`/api/tournaments/${TID}/matches`))).toBe(true)
  })

  it.each([
    '/admin/events',
    '/admin/login',
    '/admin/t/12/settings',
    '/admin/t/12/matches',
    '/admin/t/12/matches/345',
    '/admin/t/12/matches/345/score/extra',
    '/admin/t/12/score/345',
  ])('非 canonical 的 %s 在 D 轨内渲染结果必须为空（没有 catch-all）', async (path) => {
    const { container } = renderMobileScoreRoutes(path)

    // 关键：D 轨既不能渲染录分页，也不能渲染自己的“链接不可用”页
    await waitFor(() => expect(screen.queryByText('链接不可用')).toBeNull())
    expect(screen.queryByText('确认提交大比分')).toBeNull()
    expect(dTrackRenderedAnything(container)).toBe(false)
    // 也不得为这些路径发出任何赛事请求
    expect(requestedPaths.filter((p) => p.includes('/api/'))).toEqual([])
  })
})

describe('D 轨 route 表：非法 param 仍走 adapter 的错误页', () => {
  it('非法 tid 显示“链接不可用”，且不发任何 API 请求', async () => {
    renderMobileScoreRoutes('/admin/t/not-number/matches/401/score')

    await screen.findByText('链接不可用')
    expect(requestedPaths.filter((p) => p.includes('/api/'))).toEqual([])
  })

  it('非法 matchId 显示“链接不可用”，且不发任何 API 请求', async () => {
    renderMobileScoreRoutes('/admin/t/31/matches/xyz/score')

    await screen.findByText('链接不可用')
    expect(requestedPaths.filter((p) => p.includes('/api/'))).toEqual([])
  })

  it('错误页示例地址已更新为 canonical 形式', async () => {
    renderMobileScoreRoutes('/admin/t/abc/matches/401/score')

    await screen.findByText('链接不可用')
    expect(screen.getByText('/admin/t/12/matches/345/score')).toBeTruthy()
  })
})

describe('真实 App：canonical 路径可用，非 canonical 路径不出现 D 的内容', () => {
  it('A. canonical route 进入 MobileScorePage，并使用 URL 里的 tid / matchId', async () => {
    renderAppAt(`/admin/t/${TID}/matches/${MATCH_ID}/score`)

    await screen.findByText('ROUTE-OWNERSHIP 赛事')
    expect(screen.getAllByText('OWN-A').length).toBeGreaterThan(0)
    expect(screen.getAllByText('OWN-B').length).toBeGreaterThan(0)
    // 使用的是 URL 里的 tid，而不是任何 fallback 赛事
    expect(requestedPaths.some((p) => p.includes(`/api/tournaments/${TID}/matches`))).toBe(true)
  })

  it('B. /admin/events 不显示 D 的错误页，也不发赛事请求', async () => {
    const { container } = renderAppAt('/admin/events')

    await waitFor(() => expect(screen.queryByText('链接不可用')).toBeNull())
    expect(dTrackRenderedAnything(container)).toBe(false)
    expect(requestedPaths.filter((p) => p.includes('/api/tournaments/'))).toEqual([])
  })

  it('C. /admin/t/:tid/settings 不显示 D 的内容', async () => {
    const { container } = renderAppAt(`/admin/t/${TID}/settings`)

    await waitFor(() => expect(screen.queryByText('链接不可用')).toBeNull())
    expect(dTrackRenderedAnything(container)).toBe(false)
  })

  it('E. 旧的非 canonical URL 不再进入 MobileScore', async () => {
    const { container } = renderAppAt(`/admin/t/${TID}/score/${MATCH_ID}`)

    await waitFor(() => expect(screen.queryByText('确认提交大比分')).toBeNull())
    expect(screen.queryByText('链接不可用')).toBeNull()
    expect(dTrackRenderedAnything(container)).toBe(false)
    expect(requestedPaths.filter((p) => p.includes('/api/tournaments/'))).toEqual([])
  })

  it('F. 多一段的 /score/extra 不属于 D 轨（完整匹配，不是前缀匹配）', async () => {
    const { container } = renderAppAt(`/admin/t/${TID}/matches/${MATCH_ID}/score/extra`)

    await waitFor(() => expect(screen.queryByText('确认提交大比分')).toBeNull())
    expect(dTrackRenderedAnything(container)).toBe(false)
    expect(requestedPaths.filter((p) => p.includes('/api/tournaments/'))).toEqual([])
  })

  it('H. 录分页本身不渲染管理端 App Shell（顶部 11 个导航）', async () => {
    renderAppAt(`/admin/t/${TID}/matches/${MATCH_ID}/score`)
    await screen.findByText('ROUTE-OWNERSHIP 赛事')

    expect(screen.queryByText('赛事大屏')).toBeNull()
    expect(screen.queryByText('在线报名')).toBeNull()
    expect(screen.queryByText('选手与分组')).toBeNull()
  })
})
