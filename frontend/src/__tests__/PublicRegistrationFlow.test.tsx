/**
 * Public 报名正式链路回归测试（D 轨 Day5D）。
 *
 * ## 这组测试要证明的唯一结论
 *
 * ```text
 * Public 用户提交报名 ≠ 直接成为参赛选手
 * ```
 *
 * 而是：
 *
 * ```text
 * Public → POST /api/tournaments/{tid}/registrations
 *        → Registration = PENDING
 *        → 等待赛事组织者确认
 * ```
 *
 * ## 测试策略
 *
 * 与 `PublicRoutes.test.tsx` / `PublicViewStates.test.tsx` 一致：渲染**真实** `App`
 * （不 mock 页面、不 mock `api` 模块），只把网络层换成可控录制器，因此断言落在
 * “页面真正发出的请求”上 —— 这正是本次改造的核心契约。
 *
 * ⚠️ 关键断言不是“页面看起来变了”，而是：
 * - `POST /registrations` 恰好 1 次；
 * - `POST /players`（`api.addPlayer`，V0.2 legacy 报名路径）**0** 次；
 * - 报名关闭时两者都是 0 次。
 */

/// <reference types="vitest/globals" />
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { Tournament } from '../api'
import TournamentSettingsPage from '../pages/TournamentSettingsPage'

const TID = 12
const REGISTER_PATH = `/public/t/${TID}/register`
const OTHER_TID = 99
const STORAGE_KEY = 'pingpong_active_tournament_id'

const DASHBOARD = { stats: { total: 0, finished: 0, playing: 0, waiting: 0 }, tables: [], next_playable: [] }

function tournament(overrides: Record<string, unknown> = {}) {
  return {
    id: TID,
    name: 'Day5D 报名测试赛事',
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
    registration_enabled: true,
    format_code: 'GROUP_KNOCKOUT',
    rule_config: {},
    ...overrides,
  }
}

interface RecordedCall {
  method: string
  path: string
  body: unknown
}

let calls: RecordedCall[] = []
/** 后端 `TournamentOut.registration_enabled` */
let registrationEnabled = true
/** 赛事是否存在（404 场景） */
let tournamentMissing = false
/** 报名提交的响应 */
let submitStatus = 201
let submitBody: unknown = {
  registration_id: 501,
  status: 'PENDING',
  name: '张三',
  created_at: '2026-09-23 10:00:00',
}
/** 手动闸门：让 POST /registrations 悬停在“进行中”，用于观察连点行为 */
let submitGate: Promise<void> | null = null

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const registrationPosts = () => calls.filter((c) => c.method === 'POST' && /\/registrations$/.test(c.path))
/** V0.2 legacy 报名路径：`api.addPlayer` → POST /players */
const playerPosts = () => calls.filter((c) => c.method === 'POST' && /\/players$/.test(c.path))

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
    calls.push({ method, path, body })

    if (method === 'POST' && /\/registrations$/.test(path)) {
      if (submitGate) await submitGate
      return jsonResponse(submitBody, submitStatus)
    }
    if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) {
      if (tournamentMissing) {
        return jsonResponse({ detail: { code: 'RESOURCE_NOT_FOUND', message: '资源不存在' } }, 404)
      }
      return jsonResponse(tournament({ registration_enabled: registrationEnabled }))
    }
    if (/\/dashboard$/.test(path)) return jsonResponse(DASHBOARD)
    return jsonResponse([])
  })
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

/** 等报名表渲染完成（报名开启态） */
async function waitForForm() {
  return screen.findByLabelText('姓名（必填）')
}

function fillForm(values: { name?: string; affiliation?: string; contact?: string; rating?: string }) {
  if (values.name !== undefined) {
    fireEvent.change(screen.getByLabelText('姓名（必填）'), { target: { value: values.name } })
  }
  if (values.affiliation !== undefined) {
    fireEvent.change(screen.getByLabelText('所属单位 / 学校 / 学院 / 俱乐部（选填）'), {
      target: { value: values.affiliation },
    })
  }
  if (values.contact !== undefined) {
    fireEvent.change(screen.getByLabelText('联系方式（可选）'), { target: { value: values.contact } })
  }
  if (values.rating !== undefined) {
    fireEvent.change(screen.getByLabelText('运动员积分'), { target: { value: values.rating } })
  }
}

function submitForm() {
  fireEvent.click(screen.getByRole('button', { name: '提交报名' }))
}

beforeEach(() => {
  localStorage.clear()
  registrationEnabled = true
  tournamentMissing = false
  submitStatus = 201
  submitBody = { registration_id: 501, status: 'PENDING', name: '张三', created_at: '2026-09-23 10:00:00' }
  submitGate = null
  installFetchRecorder()
})

afterEach(() => {
  // 本仓库 vitest 未开启 globals，@testing-library/react 的自动 cleanup 不会生效；
  // 不显式 cleanup 会让上一个用例的 DOM 残留，产生 "Found multiple elements" 假失败。
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('场景 1：报名开启（registration_enabled = true）', () => {
  it('显示报名表，且加载阶段不发出任何写请求', async () => {
    renderAt(REGISTER_PATH)

    await waitForForm()
    expect(screen.getByRole('button', { name: '提交报名' })).toBeTruthy()
    expect(screen.getByLabelText('联系方式（可选）')).toBeTruthy()
    expect(registrationPosts()).toHaveLength(0)
    expect(playerPosts()).toHaveLength(0)
  })

  it('联系方式旁显示轻量隐私说明', async () => {
    renderAt(REGISTER_PATH)

    await waitForForm()
    expect(screen.getByText('联系方式仅供赛事组织者用于赛务联系，不会在公开赛事页面展示。')).toBeTruthy()
  })
})

describe('场景 2：报名关闭（registration_enabled = false）', () => {
  it('只显示只读关闭态：没有可提交表单、没有输入框、POST registration = 0', async () => {
    registrationEnabled = false
    renderAt(REGISTER_PATH)

    await screen.findByText('当前赛事暂未开放报名')
    expect(screen.getByText('请等待赛事组织者开放报名，或联系赛事组织者了解参赛方式。')).toBeTruthy()

    // 不是“保留整张可编辑表单、只 disable 按钮”
    expect(screen.queryByRole('button', { name: /提交报名/ })).toBeNull()
    expect(screen.queryByLabelText('姓名（必填）')).toBeNull()
    expect(document.querySelectorAll('input')).toHaveLength(0)

    expect(registrationPosts()).toHaveLength(0)
    expect(playerPosts()).toHaveLength(0)
  })
})

describe('场景 3：正式提交', () => {
  it('提交张三：POST /registrations 一次、api.addPlayer 零次，回执为“等待赛事组织者确认”', async () => {
    renderAt(REGISTER_PATH)
    await waitForForm()

    fillForm({ name: '张三', affiliation: 'XX学院', contact: '13800000000', rating: '1200' })
    submitForm()

    await waitFor(() => expect(registrationPosts()).toHaveLength(1))
    expect(registrationPosts()[0].path).toBe(`/api/tournaments/${TID}/registrations`)
    // 请求体严格使用 generated contract 的 RegistrationCreate 字段，没有多余字段
    expect(registrationPosts()[0].body).toEqual({
      name: '张三',
      affiliation: 'XX学院',
      contact: '13800000000',
      rating_points: 1200,
    })

    // legacy 报名路径必须归零
    expect(playerPosts()).toHaveLength(0)

    await screen.findByText('报名已提交')
    expect(screen.getByText('等待赛事组织者确认')).toBeTruthy()
    expect(screen.getByText('#501')).toBeTruthy()

    // 绝不能出现“已参赛 / 已加入正式名单”这类 V0.2 语义
    const text = document.body.textContent ?? ''
    expect(text).not.toContain('已正式参赛')
    expect(text).not.toContain('已加入')
    expect(text).not.toContain('报名成功，管理员可直接分组')
  })

  it('所属单位与联系方式留空时提交 null（不发送空字符串）', async () => {
    renderAt(REGISTER_PATH)
    await waitForForm()

    fillForm({ name: '李四' })
    submitForm()

    await waitFor(() => expect(registrationPosts()).toHaveLength(1))
    expect(registrationPosts()[0].body).toEqual({
      name: '李四',
      affiliation: null,
      contact: null,
      rating_points: 1000,
    })
  })
})

describe('场景 4：快速重复点击', () => {
  it('连点 3 次只发出 1 次请求，且提交期间按钮 disabled', async () => {
    const gate: { release: (() => void) | null } = { release: null }
    submitGate = new Promise<void>((resolve) => {
      gate.release = resolve
    })

    renderAt(REGISTER_PATH)
    await waitForForm()
    fillForm({ name: '张三' })

    const button = screen.getByRole('button', { name: '提交报名' })
    // 同一个事件循环内连点 3 次：同步 ref 锁必须只放行一次
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(registrationPosts()).toHaveLength(1))
    expect((screen.getByRole('button', { name: '提交中…' }) as HTMLButtonElement).disabled).toBe(true)

    gate.release?.()
    await screen.findByText('报名已提交')
    // 请求结束后没有补发第二次
    expect(registrationPosts()).toHaveLength(1)
  })
})

describe('场景 5：服务端错误', () => {
  it('报名已关闭（409 结构化错误）时展示服务端真实 message，并保留用户已填内容', async () => {
    submitStatus = 409
    submitBody = { detail: { code: 'REGISTRATION_CLOSED', message: '赛事已开赛，报名已关闭' } }

    renderAt(REGISTER_PATH)
    await waitForForm()
    fillForm({ name: '张三', affiliation: 'XX学院' })
    submitForm()

    await screen.findByText('赛事已开赛，报名已关闭')
    // 不白屏：表单仍在，且输入内容保留
    expect((screen.getByLabelText('姓名（必填）') as HTMLInputElement).value).toBe('张三')
    expect((screen.getByLabelText('所属单位 / 学校 / 学院 / 俱乐部（选填）') as HTMLInputElement).value).toBe('XX学院')
    // 锁已释放，可以再次提交
    expect((screen.getByRole('button', { name: '提交报名' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('网络失败时给出可读提示且不白屏', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const path = raw.replace(/^https?:\/\/[^/]+/, '')
      if ((init?.method ?? 'GET').toUpperCase() === 'POST' && /\/registrations$/.test(path)) {
        throw new TypeError('Failed to fetch')
      }
      if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) return jsonResponse(tournament())
      if (/\/dashboard$/.test(path)) return jsonResponse(DASHBOARD)
      return jsonResponse([])
    })

    renderAt(REGISTER_PATH)
    await waitForForm()
    fillForm({ name: '张三' })
    submitForm()

    await screen.findByText('报名提交失败，请检查网络后重试')
    expect((screen.getByLabelText('姓名（必填）') as HTMLInputElement).value).toBe('张三')
  })

  it('赛事不存在（404）时复用 Public 错误态，且不回退到 localStorage 里的其他赛事', async () => {
    localStorage.setItem(STORAGE_KEY, String(OTHER_TID))
    tournamentMissing = true

    renderAt(REGISTER_PATH)

    await screen.findByRole('heading', { name: '赛事不可用' })
    expect(calls.filter((c) => c.path.includes(`/tournaments/${OTHER_TID}`))).toEqual([])
    expect(registrationPosts()).toHaveLength(0)
  })
})

describe('场景 6：Public 隐私', () => {
  it('提交成功后不回显联系方式，也不额外请求报名列表', async () => {
    renderAt(REGISTER_PATH)
    await waitForForm()

    fillForm({ name: '张三', contact: '13800000000' })
    submitForm()

    await screen.findByText('报名已提交')

    const text = document.body.textContent ?? ''
    expect(text).not.toContain('13800000000')

    // 不得通过其他接口把联系方式重新查出来
    const registrationReads = calls.filter((c) => c.method === 'GET' && /\/registrations/.test(c.path))
    expect(registrationReads).toEqual([])
    // 也不得触碰确认接口
    expect(calls.filter((c) => /\/confirm$/.test(c.path))).toEqual([])
  })

  it('请求体之外的任何位置都不展示 contact（回执只含 contract 的四个字段）', async () => {
    renderAt(REGISTER_PATH)
    await waitForForm()
    fillForm({ name: '张三', contact: 'secret-contact' })
    submitForm()

    await screen.findByText('报名已提交')
    expect(submitBody).toEqual({
      registration_id: 501,
      status: 'PENDING',
      name: '张三',
      created_at: '2026-09-23 10:00:00',
    })
    expect(document.body.textContent ?? '').not.toContain('secret-contact')
  })
})

describe('场景 7：二维码', () => {
  it('二维码与文本地址都等于「当前 origin + /public/t/:tid/register」', async () => {
    renderAt(REGISTER_PATH)
    await waitForForm()

    const expected = `${window.location.origin}${REGISTER_PATH}`
    // 文本地址
    expect(screen.getByText(expected)).toBeTruthy()
    // 二维码编码的字符串（组件把同一个 url 同时交给二维码与文本）
    const qrTitle = document.querySelector('.reg-qr-frame svg title')?.textContent ?? ''
    expect(qrTitle).toContain(expected)
    expect(qrTitle).toContain(window.location.origin)
  })

  it('报名关闭时不展示二维码入口（避免分发已关闭的报名地址）', async () => {
    registrationEnabled = false
    renderAt(REGISTER_PATH)

    await screen.findByText('当前赛事暂未开放报名')
    expect(document.querySelector('.reg-qr')).toBeNull()
  })
})

describe('场景 8：管理端开关 ↔ Public 状态（同一个 TournamentOut.registration_enabled 事实源）', () => {
  /** 与前端组件同类型的赛事夹具（管理端页面接收 `Tournament` prop） */
  function settingsTournament(enabled: boolean): Tournament {
    return {
      id: TID,
      name: 'Day5D 报名测试赛事',
      date: '2026-01-01',
      table_count: 4,
      group_count: 2,
      qualify_per_group: 2,
      stage: 'REGISTRATION',
      created_at: '2026-01-01T00:00:00Z',
      event_type: 'SINGLES',
      bronze_mode: 'JOINT_BRONZE',
      placement_mode: 'OFF',
      games_to_win: 2,
      points_to_win: 11,
      roster_confirmed: false,
      operation_mode: 'LIVE',
      registration_enabled: enabled,
    }
  }

  it('管理端开启 → Public 报名表单出现；管理端关闭 → Public 只读关闭且 POST registration = 0', async () => {
    // 单一内存服务端：registration_enabled 是两页共用的唯一事实源
    const server = { enabled: false }
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
      calls.push({ method, path, body })

      if (method === 'PUT' && /\/registration$/.test(path)) {
        server.enabled = Boolean((body as { enabled?: boolean } | undefined)?.enabled)
        return jsonResponse(tournament({ registration_enabled: server.enabled }))
      }
      if (method === 'POST' && /\/registrations$/.test(path)) {
        return jsonResponse(
          { registration_id: 9, status: 'PENDING', name: '张三', created_at: '2026-09-23 10:00:00' },
          201,
        )
      }
      if (/\/api\/tournaments\/\d+(\?|$)/.test(path)) {
        return jsonResponse(tournament({ registration_enabled: server.enabled }))
      }
      if (/\/dashboard$/.test(path)) return jsonResponse(DASHBOARD)
      return jsonResponse([])
    })

    // 1) Public 初始：关闭态
    const publicClosed = renderAt(REGISTER_PATH)
    await screen.findByText('当前赛事暂未开放报名')
    publicClosed.unmount()

    // 2) 管理端「赛事设置 → 报名设置 → 开启报名」（真实 PUT）
    const adminEnable = render(<TournamentSettingsPage tournament={settingsTournament(false)} />)
    fireEvent.click(screen.getByRole('tab', { name: '报名设置' }))
    fireEvent.click(screen.getByRole('button', { name: '开启报名' }))
    await screen.findByText('报名中')
    adminEnable.unmount()

    // 3) Public 再读取同一赛事：报名表单可用
    const publicOpen = renderAt(REGISTER_PATH)
    await screen.findByLabelText('姓名（必填）')
    publicOpen.unmount()

    // 4) 管理端关闭报名
    const adminDisable = render(<TournamentSettingsPage tournament={settingsTournament(true)} />)
    fireEvent.click(screen.getByRole('tab', { name: '报名设置' }))
    fireEvent.click(screen.getByRole('button', { name: '关闭报名' }))
    await screen.findByText('已关闭')
    adminDisable.unmount()

    // 5) Public 回到只读关闭态，且没有任何提交
    renderAt(REGISTER_PATH)
    await screen.findByText('当前赛事暂未开放报名')
    expect(screen.queryByLabelText('姓名（必填）')).toBeNull()
    expect(registrationPosts()).toHaveLength(0)
    expect(playerPosts()).toHaveLength(0)

    // 两次开关都是真实写入，且顺序正确
    const writes = calls.filter((call) => call.method === 'PUT')
    expect(writes.map((call) => call.body)).toEqual([{ enabled: true }, { enabled: false }])
  })
})
