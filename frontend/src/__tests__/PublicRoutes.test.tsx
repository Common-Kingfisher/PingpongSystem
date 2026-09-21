/**
 * Public 路由 tid 来源回归测试（PR #44 P1）。
 *
 * 背景：React Router 的 `useParams()` 只能读取**当前组件已经处于的**匹配 Route 及祖先 Route
 * 的参数，看不到 descendant（后代）Route 的 param。`/public/t/:tid` 是 `PublicRoutes()` 内部
 * `<Routes>` 声明的 Route，因此早期实现在 `PublicRoutes()` 顶层调用 `useTidFromPath()` 只能
 * 拿到 `null`（实测 `params={}`），`tid` 变成 `undefined` 传给旧页面；旧页面按
 * `prop > ?tid= > localStorage` 兼容链回退到 `localStorage.activeTournamentId`
 * —— 复制出去的 Public 链接会打开管理员浏览器里上一次选中的赛事。
 *
 * 测试策略：直接渲染真实 `App`（不 mock 页面、不 mock api 模块），只把网络层换成记录器。
 *
 * ⚠️ 断言必须落在**页面自己发起**的请求上（dashboard / groups / rankings / knockout 等）。
 * `PublicLayout` 头部也会请求 `/api/tournaments/:tid`，而它本来就在匹配上下文内、
 * 任何时候都会用正确的 tid —— 若只断言它，即使 Public 路由漏传 tid 也会“通过”，
 * 从而掩盖本 bug（这个坑在编写本测试时真实踩到过）。
 */

/// <reference types="vitest/globals" />
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

/** URL 里指定的赛事 */
const URL_TID = 12
/** localStorage 里预置的“另一场赛事”，用于证明 path 优先 */
const STORAGE_TID = 99
const STORAGE_KEY = 'pingpong_active_tournament_id'

const TOURNAMENT_12 = {
  id: URL_TID,
  name: 'URL-TARGET-12',
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
}

const TOURNAMENT_99 = { ...TOURNAMENT_12, id: STORAGE_TID, name: 'LOCALSTORAGE-TRAP-99' }

const DASHBOARD = { stats: { total: 0, finished: 0, playing: 0, waiting: 0 }, tables: [], next_playable: [] }
const EMPTY_KNOCKOUT = {
  tournament: TOURNAMENT_12,
  rounds: [],
  champion: null,
  runner_up: null,
  placements: [],
  placement_matches: [],
  champion_path_match_ids: [],
}

/** 被请求过的 URL 路径 */
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
    // 只回放被断言需要的形状；其余返回空结构即可
    if (/\/api\/tournaments\/(\d+)(\?|$)/.test(path)) {
      return Promise.resolve(jsonResponse(id === URL_TID ? TOURNAMENT_12 : TOURNAMENT_99))
    }
    if (/\/dashboard$/.test(path)) return Promise.resolve(jsonResponse(DASHBOARD))
    if (/\/rankings$/.test(path)) return Promise.resolve(jsonResponse({ rankings: [] }))
    if (/\/groups$/.test(path)) return Promise.resolve(jsonResponse({ groups: [] }))
    if (/\/knockout$/.test(path)) return Promise.resolve(jsonResponse(EMPTY_KNOCKOUT))
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

/**
 * 每个 Public 页面在加载时**由页面自身**发起的请求。
 *
 * 刻意不含 `/api/tournaments/:id`（那是 PublicLayout 的请求，无法区分本 bug）。
 */
const CASES: Array<{ name: string; path: string; pageRequest: RegExp; label: string }> = [
  { name: 'live', path: `/public/t/${URL_TID}/live`, pageRequest: /\/dashboard$/, label: 'dashboard' },
  { name: 'schedule', path: `/public/t/${URL_TID}/schedule`, pageRequest: /\/groups$/, label: 'groups' },
  { name: 'rankings', path: `/public/t/${URL_TID}/rankings`, pageRequest: /\/rankings$/, label: 'rankings' },
  { name: 'bracket', path: `/public/t/${URL_TID}/bracket`, pageRequest: /\/knockout$/, label: 'knockout' },
  { name: 'champion', path: `/public/t/${URL_TID}/champion`, pageRequest: /\/knockout$/, label: 'knockout' },
]

beforeEach(() => {
  localStorage.clear()
  installFetchRecorder()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Public 路由：赛事 id 必须来自 URL path', () => {
  describe('Case A：URL 与 localStorage 冲突时，URL path 获胜', () => {
    // 模拟“管理员浏览器里上一次选中的赛事”
    beforeEach(() => localStorage.setItem(STORAGE_KEY, String(STORAGE_TID)))

    for (const { name, path, pageRequest, label } of CASES) {
      it(`${name}：${label} 请求命中 ${URL_TID}，且绝不出现 ${STORAGE_TID}`, async () => {
        renderAt(path)

        // 页面自身的请求必须落在 URL 指定的赛事上
        await waitFor(() =>
          expect(requestedPaths.some((p) => pageRequest.test(p) && p.includes(`/tournaments/${URL_TID}`))).toBe(true),
        )
        // 任何请求都不得指向 localStorage 里的另一场赛事
        expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
        void name
      })
    }

    it('register：不渲染 legacy 报名表单提交到别的赛事（无赛事数据请求）', async () => {
      renderAt(`/public/t/${URL_TID}/register`)

      await waitFor(() => expect(requestedPaths.length).toBeGreaterThan(0))
      expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
    })
  })

  describe('Case B：全新浏览器（localStorage 为空）仍使用 URL path', () => {
    for (const { name, path, pageRequest, label } of CASES) {
      it(`${name}：${label} 请求命中 ${URL_TID}`, async () => {
        expect(localStorage.getItem(STORAGE_KEY)).toBeNull()

        renderAt(path)

        await waitFor(() =>
          expect(requestedPaths.some((p) => pageRequest.test(p) && p.includes(`/tournaments/${URL_TID}`))).toBe(true),
        )
        expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
        void name
      })
    }

    it('register：同样不会请求其他赛事', async () => {
      renderAt(`/public/t/${URL_TID}/register`)

      await waitFor(() => expect(requestedPaths.length).toBeGreaterThan(0))
      expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
    })
  })

  it('非法 :tid 不渲染 legacy 页面，因此不会回退到 localStorage 里的其他赛事', async () => {
    localStorage.setItem(STORAGE_KEY, String(STORAGE_TID))

    renderAt('/public/t/not-a-number/live')

    // 非法 tid 时 adapter 只显示“链接不可用”，不得发出任何赛事数据请求
    await waitFor(() => expect(requestedPaths.filter((p) => p.includes('/tournaments/'))).toEqual([]))
    expect(requestedPaths.filter((p) => p.includes(`/tournaments/${STORAGE_TID}`))).toEqual([])
  })
})
