/**
 * 赛事设置页回归测试（PR #58 review 返工）。
 *
 * ## 背景
 *
 * PR #58 review 的唯一 P1 blocker：Public 端已经能读
 * `TournamentOut.registration_enabled`，但 EVENT_ADMIN 没有任何 UI 能真正开启 / 关闭报名。
 *
 * 因此「报名设置」Tab 不再是占位页，而是管理端唯一的报名开关控制面：
 *
 * ```text
 * [开启报名] / [关闭报名]
 *   → PUT /api/tournaments/{tid}/registration  { enabled: boolean }
 *   → 权威 TournamentOut
 *   → UI 状态 = response.registration_enabled（不做乐观置位）
 * ```
 *
 * 旧断言「报名设置 → 等待对应的后端数据与权限契约后接入」已过期，本文件已替换。
 *
 * ⚠️ 组件**直接渲染**（不 mock `api` 模块），只把网络层换成可控录制器，
 * 因此断言的是一次真实 `PUT` 的 method / path / body 与提交后的真实 DOM 状态。
 */

/// <reference types="vitest/globals" />
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Tournament } from '../api'
import AdminLayout from '../layouts/AdminLayout'
import TournamentSettingsPage from '../pages/TournamentSettingsPage'

function tournamentOf(enabled: boolean, id = 12): Tournament {
  return {
    id,
    name: '秋季乒乓赛',
    date: '2026-09-22',
    table_count: 8,
    group_count: 4,
    qualify_per_group: 2,
    stage: 'REGISTRATION',
    created_at: '2026-09-22T09:00:00Z',
    event_type: 'SINGLES',
    bronze_mode: 'BRONZE_MATCH',
    placement_mode: 'TIERED',
    games_to_win: 3,
    points_to_win: 11,
    roster_confirmed: false,
    operation_mode: 'LIVE',
    registration_enabled: enabled,
  }
}

interface RecordedCall {
  method: string
  path: string
  body: unknown
}

type HandlerResult = { status: number; body: unknown }
type Handler = (call: RecordedCall) => HandlerResult

let calls: RecordedCall[] = []
let handler: Handler = (call) => ({ status: 200, body: tournamentOf(Boolean((call.body as { enabled?: boolean })?.enabled)) })
/** 手动闸门：让 PUT 悬停在“进行中”，用于观察连点与保存中状态 */
let gate: Promise<void> | null = null

function installFetchRecorder() {
  calls = []
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = raw.replace(/^https?:\/\/[^/]+/, '')
    const method = (init?.method ?? 'GET').toUpperCase()
    let body: unknown
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body)
      } catch {
        body = init.body
      }
    }
    const call: RecordedCall = { method, path, body }
    calls.push(call)
    if (gate) await gate
    const result = handler(call)
    return new Response(JSON.stringify(result.body), {
      status: result.status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

const puts = () => calls.filter((call) => call.method === 'PUT')
const enableButton = () => screen.getByRole('button', { name: '开启报名' }) as HTMLButtonElement
const disableButton = () => screen.getByRole('button', { name: '关闭报名' }) as HTMLButtonElement

function openRegistrationTab() {
  fireEvent.click(screen.getByRole('tab', { name: '报名设置' }))
}

function renderSettings(tournament: Tournament | null) {
  return render(<TournamentSettingsPage tournament={tournament} />)
}

beforeEach(() => {
  localStorage.clear()
  handler = (call) => ({ status: 200, body: tournamentOf(Boolean((call.body as { enabled?: boolean })?.enabled)) })
  gate = null
  installFetchRecorder()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('赛事设置骨架', () => {
  it('按生成的赛事契约展示真实规则，并将尚无契约的设置保持只读', () => {
    renderSettings(tournamentOf(false))

    expect(screen.getAllByRole('tab')).toHaveLength(5)
    expect(screen.getByRole('tab', { name: '赛制与规则' }).getAttribute('aria-selected')).toBe('true')
    for (const value of ['单打', '4 组', '先胜 3 局', '11 分', '前 2 名', '举行季军赛', '分层名次赛', '等待赛制接口']) {
      expect(screen.getByText(value)).toBeTruthy()
    }
    expect((screen.getByRole('button', { name: '保存设置' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '取消修改' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('没有赛事数据时不伪造规则；仍未接入的分类明确标注待接入', () => {
    renderSettings(null)
    expect(screen.getAllByText('等待赛事数据').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('tab', { name: '基本信息' }))
    expect(screen.getByText(/等待对应的后端数据与权限契约后接入/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '保存设置' })).toBeNull()

    // 报名设置已接入正式契约，因此**不再**是占位页
    openRegistrationTab()
    expect(screen.getByText('等待赛事数据')).toBeTruthy()
    expect(screen.getByText('选择一场赛事后才能开启或关闭公开报名。')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '开启报名' })).toBeNull()
    expect(calls).toEqual([])
  })
})

describe('报名设置：赛事级报名开关（review blocker）', () => {
  it('A 默认关闭：显示「已关闭」与「开启报名」，且加载阶段不发任何写请求', () => {
    renderSettings(tournamentOf(false))
    openRegistrationTab()

    expect(screen.getByText('已关闭')).toBeTruthy()
    expect(enableButton()).toBeTruthy()
    expect(screen.getByText('选手当前无法通过公开报名页面提交报名。')).toBeTruthy()
    expect(screen.getByText(/报名开启后，公开报名页面将允许选手提交报名申请/)).toBeTruthy()
    expect(calls).toEqual([])
  })

  it('B 开启成功：PUT 恰好 1 次、body 正确、UI 状态来自服务端 response', async () => {
    renderSettings(tournamentOf(false))
    openRegistrationTab()
    fireEvent.click(enableButton())

    await screen.findByText('报名中')

    expect(puts()).toHaveLength(1)
    expect(puts()[0].path).toBe('/api/tournaments/12/registration')
    expect(puts()[0].body).toEqual({ enabled: true })
    expect(disableButton()).toBeTruthy()
    expect(screen.getByText('选手可以通过公开报名页面提交报名。报名记录将进入待确认列表。')).toBeTruthy()
  })

  it('B2 服务端状态优先：请求 enabled=true 但服务端返回 false 时 UI 必须显示「已关闭」', async () => {
    const gateRef: { release: (() => void) | null } = { release: null }
    gate = new Promise<void>((resolve) => { gateRef.release = resolve })
    handler = () => ({ status: 200, body: tournamentOf(false) })

    renderSettings(tournamentOf(false))
    openRegistrationTab()
    fireEvent.click(enableButton())
    await screen.findByRole('button', { name: '正在开启…' })

    gateRef.release?.()
    gate = null
    await waitFor(() => expect(screen.getByRole('button', { name: '开启报名' })).toBeTruthy())

    // 没有「点击后自己置位」：按钮绝不能变成「关闭报名」
    expect(screen.queryByRole('button', { name: '关闭报名' })).toBeNull()
    expect(screen.getByText('已关闭')).toBeTruthy()
    expect(puts()).toHaveLength(1)
  })

  it('C 关闭成功：PUT {enabled:false}，服务端确认后显示「已关闭」', async () => {
    renderSettings(tournamentOf(true))
    openRegistrationTab()
    expect(screen.getByText('报名中')).toBeTruthy()

    fireEvent.click(disableButton())
    await screen.findByText('已关闭')

    expect(puts()).toHaveLength(1)
    expect(puts()[0].body).toEqual({ enabled: false })
    expect(enableButton()).toBeTruthy()
  })

  it('D 失败不产生假状态：409 时展示服务端 message、保持原状态、按钮恢复可点', async () => {
    handler = () => ({
      status: 409,
      body: { detail: { code: 'REGISTRATION_LOCKED', message: '当前赛事状态不允许修改报名设置' } },
    })

    renderSettings(tournamentOf(true))
    openRegistrationTab()
    fireEvent.click(disableButton())

    await screen.findByText('当前赛事状态不允许修改报名设置')
    // 状态没有被乐观改掉
    expect(screen.getByText('报名中')).toBeTruthy()
    expect(screen.queryByText('已关闭')).toBeNull()
    // 锁被释放，可以重试
    expect(disableButton().disabled).toBe(false)
    expect(puts()).toHaveLength(1)
  })

  it('E 重复点击：同一事件循环连点 3 次只发出 1 次 PUT', async () => {
    const gateRef: { release: (() => void) | null } = { release: null }
    gate = new Promise<void>((resolve) => { gateRef.release = resolve })

    renderSettings(tournamentOf(false))
    openRegistrationTab()

    const button = enableButton()
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(puts()).toHaveLength(1))
    expect((screen.getByRole('button', { name: '正在开启…' }) as HTMLButtonElement).disabled).toBe(true)

    gateRef.release?.()
    gate = null
    await screen.findByText('报名中')
    expect(puts()).toHaveLength(1)
  })

  it('F 赛事切换：A(true) → B(false) 后不得残留上一场的报名状态', async () => {
    const { rerender } = render(<TournamentSettingsPage tournament={tournamentOf(true, 12)} />)
    openRegistrationTab()
    expect(screen.getByText('报名中')).toBeTruthy()

    rerender(<TournamentSettingsPage tournament={tournamentOf(false, 13)} />)

    await waitFor(() => expect(screen.getByText('已关闭')).toBeTruthy())
    expect(screen.queryByText('报名中')).toBeNull()
    expect(enableButton()).toBeTruthy()
  })

  it('父级刷新回同一赛事的新对象时不改变已确认的服务端状态', async () => {
    const { rerender } = render(<TournamentSettingsPage tournament={tournamentOf(true, 12)} />)
    openRegistrationTab()
    fireEvent.click(disableButton())
    await screen.findByText('已关闭')

    rerender(<TournamentSettingsPage tournament={tournamentOf(false, 12)} />)
    expect(screen.getByText('已关闭')).toBeTruthy()
    expect(puts()).toHaveLength(1)
  })
})

describe('报名设置的错误语义（401 / 403 / 404 / 409）', () => {
  const cases = [
    { status: 401, code: 'AUTH_REQUIRED', message: '请先登录' },
    { status: 403, code: 'FORBIDDEN', message: '没有权限修改该赛事' },
    { status: 404, code: 'RESOURCE_NOT_FOUND', message: '资源不存在' },
    { status: 409, code: 'REGISTRATION_CLOSED', message: '赛事已开赛，报名已关闭' },
  ] as const

  for (const item of cases) {
    it(`${item.status} 展示服务端可读 message，保持原状态且不白屏`, async () => {
      handler = () => ({ status: item.status, body: { detail: { code: item.code, message: item.message } } })

      renderSettings(tournamentOf(false))
      openRegistrationTab()
      fireEvent.click(enableButton())

      const alert = await screen.findByRole('alert')
      expect(alert.textContent).toBe(item.message)
      // 页面结构仍在（不白屏），状态与按钮保持原样
      expect(screen.getByText('已关闭')).toBeTruthy()
      expect(enableButton().disabled).toBe(false)
      expect(puts()).toHaveLength(1)
    })
  }
})

describe('管理端 Public 入口', () => {
  it('选中赛事时以新标签打开对应 Public live 路由', () => {
    render(<MemoryRouter initialEntries={['/settings?tid=12']}><AdminLayout><div /></AdminLayout></MemoryRouter>)
    const link = screen.getByRole('link', { name: '打开 Public 页面' }) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/public/t/12/live')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noreferrer')
  })

  it('未选中赛事时不生成 Public 链接', () => {
    render(<MemoryRouter initialEntries={['/settings']}><AdminLayout><div /></AdminLayout></MemoryRouter>)
    expect(screen.queryByRole('link', { name: '打开 Public 页面' })).toBeNull()
    expect(screen.getByText('打开 Public 页面').getAttribute('aria-disabled')).toBe('true')
  })
})
