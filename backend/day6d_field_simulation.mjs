/**
 * D 轨 Day6D 现场模拟：真实 Chrome（多 BrowserContext = 多台手机）× 真实 production 单服务。
 *
 * ## 这一轮要证明的事情
 *
 * 不是「页面能打开」，而是：
 *
 * ```text
 * 一台普通 Windows 电脑 + 普通无线路由器 + 多台手机 + 同一个 PingpongSystem 服务
 * → 能完成一场小型赛事的主要现场流程（报名 / 名单 / 抽签 / 录分 / 查看 / 掉线恢复）
 * ```
 *
 * ## 客户端模型（必须与真实手机数量区分）
 *
 * 每个「手机」= 一个独立的 **Chrome BrowserContext**（独立 cookie jar / localStorage /
 * 缓存），而不是同一个 profile 里的多个标签页 —— 否则无法证明「Public 刷新不依赖别的
 * 页面写过的 localStorage」。
 *
 * ```text
 * 真实手机数量：0（本机 headless Chrome，没有真实无线网卡与路由器）
 * 模拟客户端数量：脚本末尾打印的 CLIENTS simulated=N
 * ```
 *
 * ## 与 A6/D6A 的关系
 *
 * 并发正确性的**规则层**证据已在 `tests/test_d6a_concurrency.py` 冻结（同 request_id
 * 幂等、不同 payload 409、同一球台抢占只放行一个）。本脚本不重复那套 service 层测试，
 * 只验证**现场形态**：两个真实浏览器会话同时提交、同一场比赛多端打开、断网重试，
 * 最终数据库里不会出现互相矛盾的最终事实。
 *
 * ## 用法
 *
 * ```powershell
 * # 1. production 单服务（必须是 FastAPI + frontend/dist 单进程）
 * $env:PINGPONG_DB_PATH='data\d6d_field.db'
 * .\start_pingpong.ps1 -NoBrowser
 * # 2. 造干净赛事
 * cd backend; .\.venv\Scripts\python.exe .\day6d_field_fixture.py http://127.0.0.1:8000
 * # 3. 起 CDP Chrome
 * & "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
 *     --remote-debugging-port=9333 --user-data-dir=<临时目录> about:blank
 * # 4. 跑现场模拟（base 用**真实 LAN 地址**，才能证明 Public URL 从访问 origin 派生）
 * node .\day6d_field_simulation.mjs http://10.0.0.5:8000 1 d6d-admin d6d-admin-pass1
 * ```
 */

import { sleep } from './day3_cdp_auth.mjs'

const CDP_PORT = process.env.CDP_PORT ?? '9333'
const base = (process.argv[2] ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
const TID = Number(process.argv[3] ?? '1')
const USER = process.argv[4] ?? 'd6d-admin'
const PASS = process.argv[5] ?? 'd6d-admin-pass1'

const failures = []
const lines = []
/** 模拟客户端计数：只统计「手机」，管理电脑 / 大屏不计入。 */
let phoneCount = 0

function check(name, ok, detail) {
  const line = `[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`
  lines.push(line)
  // 立即输出：脚本中途抛错时，已完成的现场事实不能跟着一起丢。
  console.log(line)
  if (!ok) failures.push(name)
}
function section(title) {
  lines.push('')
  lines.push(`### ${title}`)
  console.log('')
  console.log(`### ${title}`)
}

// ---------------------------------------------------------------- 多 context CDP 客户端

class Browser {
  constructor(ws, send) {
    this.ws = ws
    this.send = send
  }

  static async connect(port = CDP_PORT) {
    const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
    const ws = new WebSocket(version.webSocketDebuggerUrl)
    let id = 0
    const pending = new Map()
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data)
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg)
        pending.delete(msg.id)
      }
    })
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve)
      ws.addEventListener('error', reject)
    })
    const send = (method, params = {}, sessionId) =>
      new Promise((resolve) => {
        const i = ++id
        pending.set(i, resolve)
        ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }))
      })
    return new Browser(ws, send)
  }

  /** 独立 BrowserContext（= 独立 cookie jar / storage），对应“另一台手机”。 */
  async newContext() {
    const res = await this.send('Target.createBrowserContext', {})
    if (res.error) throw new Error(`createBrowserContext: ${res.error.message}`)
    return res.result.browserContextId
  }

  async newPage(contextId, { width = 390, height = 844, count = true } = {}) {
    const res = await this.send('Target.createTarget', { url: 'about:blank', browserContextId: contextId })
    if (res.error) throw new Error(`createTarget: ${res.error.message}`)
    const targetId = res.result.targetId
    const attached = await this.send('Target.attachToTarget', { targetId, flatten: true })
    const sessionId = attached.result.sessionId
    if (count) phoneCount += 1
    return new Page(this, targetId, sessionId, width, height)
  }

  async disposeContext(contextId) {
    await this.send('Target.disposeBrowserContext', { browserContextId: contextId }).catch(() => {})
  }
}

class Page {
  constructor(browser, targetId, sessionId, width, height) {
    this.browser = browser
    this.targetId = targetId
    this.sessionId = sessionId
    this.width = width
    this.height = height
  }

  send(method, params = {}) {
    return this.browser.send(method, params, this.sessionId)
  }

  async prepare() {
    await this.send('Page.enable')
    await this.send('Runtime.enable')
    await this.send('Network.enable')
    await this.send('Network.setCacheDisabled', { cacheDisabled: true })
    await this.send('Emulation.setDeviceMetricsOverride', {
      width: this.width,
      height: this.height,
      deviceScaleFactor: 1,
      mobile: true,
    })
  }

  async evaluate(expression) {
    const out = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    const details = out.result?.exceptionDetails
    if (details) throw new Error(`eval error: ${details.text} ${details.exception?.description ?? ''}`)
    return out.result?.result?.value
  }

  async goto(url, waitFor) {
    await this.send('Page.navigate', { url })
    if (waitFor) return this.waitForSelector(waitFor)
    await sleep(400)
  }

  async reload(waitFor) {
    await this.send('Page.reload', { ignoreCache: false })
    if (waitFor) return this.waitForSelector(waitFor)
    await sleep(400)
  }

  async waitForSelector(selector, tries = 80) {
    for (let i = 0; i < tries; i += 1) {
      await sleep(150)
      const ok = await this.evaluate(`!!document.querySelector(${JSON.stringify(selector)})`).catch(() => false)
      if (ok) return true
    }
    return false
  }

  async waitForText(substring, tries = 80) {
    for (let i = 0; i < tries; i += 1) {
      await sleep(150)
      const ok = await this.evaluate(
        `(document.body?.innerText ?? '').includes(${JSON.stringify(substring)})`,
      ).catch(() => false)
      if (ok) return true
    }
    return false
  }

  /** 按可见文本点击按钮 / tab（默认只认 button / a / role=tab）。 */
  async clickByText(text, { tag = null, exact = true, sel = null } = {}) {
    return this.evaluate(`(() => {
      const t = ${JSON.stringify(text)}
      const nodes = [...document.querySelectorAll(${sel ? JSON.stringify(sel) : tag ? JSON.stringify(tag) : `'button,a,[role=tab],[role=button]'`})]
      const hit = nodes.find((n) => {
        const s = (n.textContent || '').trim()
        return ${exact} ? s === t : s.includes(t)
      })
      if (!hit) return 'NOT_FOUND'
      if (hit.disabled) return 'DISABLED'
      hit.click()
      return true
    })()`)
  }

  async click(selector) {
    return this.evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)})
      if (!el) return 'NOT_FOUND'
      if (el.disabled) return 'DISABLED'
      el.click()
      return true
    })()`)
  }

  async text() {
    return this.evaluate(`document.body?.innerText ?? ''`)
  }

  /** 用 placeholder 精确填表单（RegisterPage 的输入框只带 id + placeholder，无 aria-label）。 */
  async setBySelector(selector, value) {
    return this.evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)})
      if (!el) return 'NOT_FOUND'
      const proto = el instanceof window.HTMLTextAreaElement
        ? window.HTMLTextAreaElement.prototype
        : el instanceof window.HTMLSelectElement
          ? window.HTMLSelectElement.prototype
          : window.HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)})
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
      return el.value
    })()`)
  }

  /** 按下标给带 aria-label 子串的输入框赋值（MobileScorePage 的 `.ms-score-input`）。 */
  async setByLabel(labelSubstring, occurrence, value) {
    const index = await this.evaluate(`(() => {
      const all = [...document.querySelectorAll('input')]
      const hits = all.filter((i) => (i.getAttribute('aria-label') || '').includes(${JSON.stringify(labelSubstring)}))
      if (hits.length <= ${occurrence}) return -1
      return all.indexOf(hits[${occurrence}])
    })()`)
    if (index < 0) return 'NOT_FOUND'
    return this.evaluate(`(() => {
      const el = document.querySelectorAll('input')[${index}]
      if (!el) return 'NOT_FOUND'
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)})
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
      return el.value
    })()`)
  }

  /** 浏览器自己的真实登录（`pp_session` HttpOnly Cookie）。 */
  async login(username, password) {
    await this.goto(`${base}/`)
    await sleep(500)
    return this.evaluate(`(async () => {
      const resp = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username: ${JSON.stringify(username)}, password: ${JSON.stringify(password)}, mode: 'browser' })
      })
      return resp.status
    })()`)
  }

  async setOffline(offline) {
    return this.send('Network.emulateNetworkConditions', {
      offline,
      latency: 0,
      downloadThroughput: offline ? 0 : -1,
      uploadThroughput: offline ? 0 : -1,
    })
  }

  async freeze() { await this.send('Page.setWebLifecycleState', { state: 'frozen' }) }
  async activate() { await this.send('Page.setWebLifecycleState', { state: 'active' }) }

  /**
   * 统计某个 path 上真实发出的 POST 次数（用于证明关闭态“0 次提交”）。
   *
   * 必须用 `Page.addScriptToEvaluateOnNewDocument` 在**文档创建前**注入：
   * 用 `Runtime.evaluate` 打的补丁会在下一次导航时随旧 document 一起消失，
   * 那样测到的永远是 0 —— 也就是一个永远 PASS 的假证据。
   */
  async watchPosts(pathSuffix) {
    await this.send('Page.addScriptToEvaluateOnNewDocument', {
      source: `(() => {
        window.__posts = []
        const original = window.fetch
        window.fetch = (input, options) => {
          const url = String(input)
          const method = (options?.method ?? 'GET').toUpperCase()
          if (method === 'POST' && url.includes(${JSON.stringify(pathSuffix)})) window.__posts.push(url)
          return original(input, options)
        }
      })()`,
    })
  }

  async postCount() {
    return this.evaluate(`(window.__posts ?? []).length`)
  }

  async close() {
    await this.browser.send('Target.closeTarget', { targetId: this.targetId }).catch(() => {})
  }
}

// ---------------------------------------------------------------- 服务端事实核对（HTTP）

let serverToken = null

async function api(path, options = {}) {
  const headers = { ...(options.headers ?? {}) }
  if (serverToken) headers.Authorization = `Bearer ${serverToken}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const resp = await fetch(`${base}${path}`, {
    method: options.method ?? 'GET',
    headers,
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
  })
  const text = await resp.text()
  let parsed = null
  try { parsed = JSON.parse(text) } catch { parsed = text }
  return { status: resp.status, body: parsed }
}

async function loginServerSide() {
  const resp = await api('/api/v1/auth/login', {
    method: 'POST',
    body: { username: USER, password: PASS, mode: 'bearer' },
  })
  if (resp.status !== 200 || !resp.body?.access_token) {
    throw new Error(`bearer 登录失败: HTTP ${resp.status} ${JSON.stringify(resp.body)}`)
  }
  serverToken = resp.body.access_token
}

/**
 * **不带任何凭据**的请求。
 *
 * 用来验证“Public / 匿名访问者做不到什么”。绝不能复用 `api()`：
 * 那会把管理员 bearer token 一起发出去，把越权检查变成假的 PASS。
 */
async function anonApi(path, options = {}) {
  const headers = { ...(options.headers ?? {}) }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const resp = await fetch(`${base}${path}`, {
    method: options.method ?? 'GET',
    headers,
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
  })
  const text = await resp.text()
  let parsed = null
  try { parsed = JSON.parse(text) } catch { parsed = text }
  return { status: resp.status, body: parsed }
}

const matches = () => api(`/api/tournaments/${TID}/matches`).then((r) => r.body)
const tournament = () => api(`/api/tournaments/${TID}`).then((r) => r.body)
const dashboard = () => api(`/api/tournaments/${TID}/dashboard`).then((r) => r.body)
const playable = (list) =>
  list.filter((m) => m.status === 'PLAYING' && m.entry_a_id != null && m.entry_b_id != null)

/**
 * 现场“排台”的正式批量接口（`POST /api/tournaments/{id}/schedule-next`），
 * 与管理端「比赛控制」页的「自动安排下一批比赛」按钮**同一入口**。
 *
 * 为什么不用手挑比赛 + `assign-table`：后端有一条现场规则
 * 「选手正在参加其他比赛，不能同时上场」（`scheduling.py`，409）。
 * 逐场手排很容易撞上这条规则，而批量排台会一次选出互不冲突的一组比赛 ——
 * 这正是现场组织者真正会按的按钮。
 */
async function scheduleBatch() {
  const before = await matches()
  const beforePlaying = new Set(playable(before).map((m) => m.id))
  const resp = await api(`/api/tournaments/${TID}/schedule-next`, { method: 'POST', body: {} })
  const after = await matches()
  const newly = playable(after).filter((m) => !beforePlaying.has(m.id))
  return { status: resp.status, newly, body: resp.body }
}

/** 反复排台直到至少有 `count` 场互不冲突的比赛处于 PLAYING（上限 6 轮）。 */
async function ensurePlaying(count) {
  let current = playable(await matches())
  for (let i = 0; i < 6 && current.length < count; i += 1) {
    await scheduleBatch()
    current = playable(await matches())
  }
  return current
}

// ---------------------------------------------------------------- 开始

const browser = await Browser.connect()
await loginServerSide()

section('P0 现场基线（production 单服务 + 新赛事默认状态）')
{
  const health = await api('/api/health')
  check('P0-1 服务 /api/health 就绪', health.status === 200, `HTTP ${health.status}`)

  const t = await tournament()
  check(
    'P0-2 赛事为 SINGLES / GROUP_KNOCKOUT / 16 席 4 组',
    t.event_type === 'SINGLES' && t.format_code === 'GROUP_KNOCKOUT' && t.group_count === 4,
    `event=${t.event_type} format=${t.format_code} groups=${t.group_count}`,
  )
  check('P0-3 新赛事报名默认关闭（raw=false）', t.registration_enabled === false, `raw=${t.registration_enabled}`)
  check('P0-4 名单未确认', !t.roster_confirmed, `roster_confirmed=${t.roster_confirmed}`)
  check('P0-5 球台 6 张', (await dashboard()).tables.length === 6, `tables=${(await dashboard()).tables.length}`)

  const root = await fetch(`${base}/`)
  const html = await root.text()
  check('P0-6 前端由同一服务托管（单服务模式，非 Vite 5173）', root.status === 200 && html.includes('id="root"'), `HTTP ${root.status}`)
}

// ---------------------------------------------------------------- P1-A 管理端 UI 开启报名

const adminCtx = await browser.newContext()
// 管理电脑不按“手机”计数
const admin = await browser.newPage(adminCtx, { width: 1280, height: 900, count: false })
await admin.prepare()
await admin.login(USER, PASS)

section('P1-A EVENT_ADMIN 用管理端 UI 开启报名（禁止 SQL / curl / DevTools 改状态）')
{
  await admin.goto(`${base}/settings?tid=${TID}`, '[role=tab]')
  const tabs = await admin.clickByText('报名设置', { tag: '[role=tab]' })
  check('P1-A1 管理端 /settings 可进入「报名设置」', tabs === true, `click=${tabs}`)
  await sleep(500)

  const box = await admin.evaluate(`(() => {
    const el = document.querySelector('.registration-setting input[type=checkbox]')
    return el ? { found: true, disabled: el.disabled, checked: el.checked } : { found: false }
  })()`)
  check('P1-A2 默认关闭态：开关未勾选且可操作', box.found === true && box.checked === false && box.disabled === false, JSON.stringify(box))

  const toggled = await admin.click('.registration-setting input[type=checkbox]')
  check('P1-A3 可勾选报名开关', toggled === true, `click=${toggled}`)
  await sleep(250)

  const saved = await admin.clickByText('保存报名设置')
  check('P1-A4 可点击「保存报名设置」', saved === true, `click=${saved}`)

  let raw = null
  for (let i = 0; i < 40; i += 1) {
    await sleep(250)
    const t = await tournament()
    raw = t.registration_enabled
    if (raw === true) break
  }
  check('P1-A5 服务端 raw registration_enabled=true（UI 真实写入）', raw === true, `raw=${raw}`)

  const notice = await admin.text()
  check('P1-A6 管理端显示开启成功提示', notice.includes('线上报名已开启'), 'notice=线上报名已开启')
}

// ---------------------------------------------------------------- P1-B Public 手机报名

section('P1-B Public 手机报名（真实表单提交）')
const registrationPath = `/public/t/${TID}/register`
const expectedRegisterUrl = `${base}${registrationPath}`
let firstPendingName = ''
{
  const phoneA = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
  await phoneA.prepare()
  await phoneA.goto(expectedRegisterUrl, '.reg-form')

  check('P1-B1 手机打开 Public 报名页渲染真实表单', await phoneA.waitForSelector('.reg-form'), 'form=.reg-form')

  const qr = await phoneA.evaluate(`(() => {
    const title = document.querySelector('.reg-qr-frame svg title')?.textContent ?? null
    const url = document.querySelector('.reg-qr-url')?.textContent ?? null
    return { title, url, hasQr: !!document.querySelector('.reg-qr') }
  })()`)
  check(
    'P1-B2 二维码与文本地址同源，且等于当前访问 origin 派生地址',
    qr.hasQr && qr.url === expectedRegisterUrl && (qr.title ?? '').includes(expectedRegisterUrl),
    `url=${qr.url}`,
  )

  const qrHost = new URL(qr.url ?? 'http://invalid').host
  const accessHost = new URL(base).host
  check(
    'P1-B3 地址 host === 当前访问 host（没有固定 localhost / 192.168.x.x / 公网域名）',
    qrHost === accessHost,
    `qrHost=${qrHost} accessHost=${accessHost}`,
  )

  await phoneA.setBySelector('#reg-name', '现场选手甲')
  await phoneA.setBySelector('#reg-affiliation', '现场单位 A')
  await phoneA.setBySelector('#reg-contact', '13900000001')
  await phoneA.click('.reg-submit')

  const ok = await phoneA.waitForText('等待赛事组织者确认')
  check('P1-B4 提交后进入 PENDING 回执（等待赛事组织者确认）', ok === true, 'receipt=PENDING')

  const receipt = await phoneA.text()
  check('P1-B5 回执不回显联系方式（隐私边界）', !receipt.includes('13900000001'), 'contact hidden')
  check(
    'P1-B6 回执不出现“已参赛 / 已加入正式名单”语义',
    !receipt.includes('已参赛') && !receipt.includes('已加入'),
    'no legacy semantics',
  )

  const pending = await api(`/api/tournaments/${TID}/registrations`)
  const first = (pending.body ?? []).find((r) => r.name === '现场选手甲')
  check('P1-B7 服务端登记为 PENDING（不是 Player）', first?.status === 'PENDING', `status=${first?.status}`)
  firstPendingName = first?.name ?? ''

  const anonList = await anonApi(`/api/tournaments/${TID}/registrations`)
  check('P1-B8 Public 不能读取报名管理列表（匿名 401）', anonList.status === 401, `HTTP ${anonList.status}`)
  const anonConfirm = await anonApi(`/api/tournaments/${TID}/registrations/1/confirm`, { method: 'POST', body: {} })
  check('P1-B9 Public 不能执行 confirm（匿名 401）', anonConfirm.status === 401, `HTTP ${anonConfirm.status}`)
  const anonWrite = await anonApi(`/api/tournaments/${TID}/registration`, { method: 'PUT', body: { enabled: false } })
  check('P1-B11 匿名不能改写报名开关（401）', anonWrite.status === 401, `HTTP ${anonWrite.status}`)

  // 用**同一条正式公开契约**补足到 16 人规模（页面提交已经证明第 1 条走的是同一条路径）
  for (let i = 2; i <= 16; i += 1) {
    const created = await api(`/api/tournaments/${TID}/registrations`, {
      method: 'POST',
      body: {
        name: `现场选手${String(i).padStart(2, '0')}`,
        affiliation: `现场单位 ${i}`,
        contact: null,
        rating_points: 1000 + i,
      },
    })
    if (created.status !== 201) throw new Error(`补齐报名失败: HTTP ${created.status} ${JSON.stringify(created.body)}`)
  }
  const all = await api(`/api/tournaments/${TID}/registrations`)
  check(
    'P1-B10 共 16 条 PENDING（1 条真实 UI 提交 + 15 条同一公开契约补齐）',
    Array.isArray(all.body) && all.body.length === 16,
    `pending=${Array.isArray(all.body) ? all.body.length : 'n/a'} uiSubmitted=${firstPendingName}`,
  )

  await phoneA.close()
}

// ---------------------------------------------------------------- P1-C 管理端确认

section('P1-C EVENT_ADMIN 用管理端 UI 逐条确认报名')
{
  await admin.goto(`${base}/players?tid=${TID}`, '[role=tab]')
  const tab = await admin.clickByText('待确认报名', { tag: '[role=tab]', exact: false })
  check('P1-C1 管理端「待确认报名」tab 可进入', tab === true, `click=${tab}`)
  await sleep(600)

  await admin.waitForSelector('.data-table tbody tr')
  const rowCount = await admin.evaluate(`document.querySelectorAll('.data-table tbody tr').length`)
  check('P1-C2 列表按行渲染 16 条待确认', rowCount === 16, `rows=${rowCount}`)

  let confirmClicks = 0
  let remaining = await admin.evaluate(`document.querySelectorAll('.data-table tbody tr').length`)
  for (let i = 0; i < 60 && remaining > 0; i += 1) {
    const clicked = await admin.clickByText('确认并加入名单', { tag: 'button' })
    if (clicked === 'DISABLED') { await sleep(500); continue }   // 上一笔请求还没结束，等它放开
    if (clicked !== true) break
    confirmClicks += 1
    await sleep(400)
    remaining = await admin.evaluate(`document.querySelectorAll('.data-table tbody tr').length`)
  }
  check('P1-C3 通过管理端 UI 逐条确认直到待确认列表清空', confirmClicks >= 16 && remaining === 0, `clicks=${confirmClicks} remainingRows=${remaining}`)

  await sleep(600)
  const players = await api(`/api/tournaments/${TID}/players`)
  check('P1-C4 确认后正式名单 Player = 16', Array.isArray(players.body) && players.body.length === 16, `players=${players.body?.length}`)

  const after = await api(`/api/tournaments/${TID}/registrations`)
  const stillPending = (after.body ?? []).filter((r) => r.status === 'PENDING').length
  check('P1-C5 不再有 PENDING（全部 CONFIRMED）', stillPending === 0, `pending=${stillPending}`)

  const entries = await api(`/api/tournaments/${TID}/entries`)
  check('P1-C6 Player 未在确认阶段伪造 Entry（Entry 由名单确认建立）', Array.isArray(entries.body) && entries.body.length === 0, `entries=${entries.body?.length}`)
}

// ---------------------------------------------------------------- P1-D 名单确认

section('P1-D 管理端确认正式参赛名单（真实 UI）')
{
  // RosterLaunch 只渲染在「正式名单」tab 里；刚在「待确认报名」tab 逐条确认完，
  // 必须显式切回去，否则这里会因为找不到按钮而误判成产品缺陷。
  const backToOfficial = await admin.clickByText('正式名单', { tag: '[role=tab]', exact: false })
  check('P1-D1 可切回「正式名单」tab', backToOfficial === true, `click=${backToOfficial}`)
  await sleep(700)

  const heading = await admin.waitForText('确认正式参赛名单')
  check('P1-D2 名单页出现「确认正式参赛名单」', heading === true, 'heading found')

  const clicked = await admin.clickByText('确认参赛名单', { tag: 'button' })
  check('P1-D3 可点击「确认参赛名单」', clicked === true, `click=${clicked}`)

  let roster = false
  for (let i = 0; i < 40; i += 1) {
    await sleep(250)
    if ((await tournament()).roster_confirmed === true) { roster = true; break }
  }
  check('P1-D4 服务端 roster_confirmed=true', roster === true, `roster_confirmed=${roster}`)

  const entries = await api(`/api/tournaments/${TID}/entries`)
  check('P1-D5 名单确认后建立正式 Entry（16 个参赛位）', (entries.body ?? []).length === 16, `entries=${entries.body?.length}`)
  check('P1-D6 名单确认不把阶段推进出 REGISTRATION（后续仍需抽签）', (await tournament()).stage === 'REGISTRATION', `stage=${(await tournament()).stage}`)
}

// ---------------------------------------------------------------- P1-E 冻结后 Public 必须 CLOSED

section('P1-E 名单冻结后 Public 必须关闭（raw 仍为 true）')
{
  const t = await tournament()
  check('P1-E1 raw 开关仍为 true（未被自动清零）', t.registration_enabled === true, `raw=${t.registration_enabled}`)

  // 全新 context：没有任何 localStorage / history，才真正证明“Public 自解释”
  const sink = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
  await sink.prepare()
  await sink.watchPosts(`/tournaments/${TID}/registrations`)
  await sink.goto(`${base}${registrationPath}`, '.reg-page')
  await sleep(900)

  const body = await sink.text()
  const posts = await sink.postCount()
  check('P1-E2 关闭态：不显示报名表单', !(await sink.evaluate(`!!document.querySelector('.reg-form')`)), 'form=null')
  check('P1-E3 关闭态：不显示报名二维码入口', (await sink.evaluate(`!!document.querySelector('.reg-qr')`)) === false, 'qr=null')
  check('P1-E4 关闭态：0 次 POST /registrations', posts === 0, `posts=${posts}`)
  check('P1-E5 关闭态文案明确', body.includes('当前赛事暂未开放报名'), 'closed text')

  await sink.close()
}

// ---------------------------------------------------------------- P1-F 抽签与编排

section('P1-F 抽签与编排（真实管理端 UI）')
{
  await admin.goto(`${base}/draw?tid=${TID}`, 'button')
  await sleep(700)

  const grouped = await admin.clickByText('生成分组', { tag: 'button' })
  check('P1-F1 可点击「生成分组」', grouped === true, `click=${grouped}`)
  let groups = []
  for (let i = 0; i < 40; i += 1) {
    await sleep(300)
    groups = (await api(`/api/tournaments/${TID}/groups`)).body?.groups ?? []
    if (groups.length > 0) break
  }
  check('P1-F2 生成 4 个小组', groups.length === 4, `groups=${groups.length}`)

  const gen = await admin.clickByText('生成小组比赛', { tag: 'button' })
  check('P1-F3 可点击「生成小组比赛」', gen === true, `click=${gen}`)
  let list = []
  for (let i = 0; i < 40; i += 1) {
    await sleep(300)
    list = await matches()
    if (list.length > 0) break
  }
  check('P1-F4 小组赛对阵已生成', list.length > 0, `matches=${list.length}`)
  check('P1-F5 小组赛阶段状态未回退', (await tournament()).stage === 'GROUP_STAGE', `stage=${(await tournament()).stage}`)
}

// ---------------------------------------------------------------- P1-G 排台

section('P1-G 排台（真实管理端「自动安排下一批比赛」按钮）')
{
  await admin.goto(`${base}/console?tid=${TID}`, '.console-page, body')
  await sleep(1200)
  const clicked = await admin.clickByText('自动安排下一批比赛', { tag: 'button' })
  check('P1-G1 管理端可点击「自动安排下一批比赛」', clicked === true, `click=${clicked}`)

  let playing = []
  for (let i = 0; i < 30; i += 1) {
    await sleep(400)
    playing = playable(await matches())
    if (playing.length >= 3) break
  }
  check('P1-G2 至少 3 场排上球台并进入 PLAYING', playing.length >= 3, `playing=${playing.length}`)

  const tables = (await dashboard()).tables
  const occupied = tables.filter((t) => t.status === 'OCCUPIED').length
  check('P1-G3 球台占用数与进行中比赛数一致（无错误占台）', occupied === playing.length, `occupied=${occupied} playing=${playing.length}`)
}

// ---------------------------------------------------------------- P1-H Mobile Score 真实录分

section('P1-H Mobile Score 真实录分（正常结果 + 异常结果）')
let scoredNormal = null
let scoredForfeit = null
{
  const list = await matches()
  const ready = list.filter((m) => m.status === 'PLAYING' && m.entry_a_id != null && m.entry_b_id != null)
  const normal = ready[0]
  const abnormal = ready[1]
  // 不用 throw：中途崩溃会让后面所有现场事实一起丢失。记录 FAIL 后继续。
  check('P1-H0 排台后至少有 2 场可录分的进行中比赛', Boolean(normal && abnormal), `playable=${ready.length}`)

  if (normal && abnormal) {
  scoredNormal = normal.id
  scoredForfeit = abnormal.id

  const phoneB = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
  await phoneB.prepare()
  const loginStatus = await phoneB.login(USER, PASS)
  check('P1-H1 手机端建立真实登录会话（pp_session Cookie）', loginStatus === 200, `HTTP ${loginStatus}`)

  // ---- 正常结果
  await phoneB.goto(`${base}/admin/t/${TID}/matches/${normal.id}/score`, '.ms-submit')
  check('P1-H2 录分页在手机视口渲染（大比分输入 + 提交）', await phoneB.waitForSelector('.ms-score-input'), 'ms-score-input')
  await phoneB.setByLabel('大比分', 0, '3')
  await phoneB.setByLabel('大比分', 1, '1')
  await phoneB.click('.ms-submit')
  const doneText = await phoneB.waitForText('比分已保存')
  check('P1-H3 提交后显示「比分已保存」', doneText === true, 'done=true')

  const afterNormal = (await matches()).find((m) => m.id === normal.id)
  check(
    'P1-H4 服务端 FINISHED 且比分正确（3:1）',
    afterNormal.status === 'FINISHED' && afterNormal.player_a_score === 3 && afterNormal.player_b_score === 1,
    `status=${afterNormal.status} ${afterNormal.player_a_score}:${afterNormal.player_b_score}`,
  )
  check('P1-H5 未伪造逐局小比分（只录大比分时 games=0）', afterNormal.games.length === 0, `games=${afterNormal.games.length}`)

  const tableAfter = (await dashboard()).tables.find((t) => t.id === normal.table_id)
  check('P1-H6 比赛结束后球台已释放', tableAfter?.status === 'FREE', `table=${normal.table_id} status=${tableAfter?.status}`)

  // ---- 异常结果（弃权）
  await phoneB.goto(`${base}/admin/t/${TID}/matches/${abnormal.id}/score`, '.ms-submit')
  const toAbnormal = await phoneB.evaluate(`(() => {
    const tabs = [...document.querySelectorAll('.ms-mode-tab')]
    const hit = tabs.find((t) => (t.textContent || '').includes('异常结果'))
    if (!hit) return 'NOT_FOUND'
    hit.click()
    return true
  })()`)
  check('P1-H7 可切换到「异常结果」录入', toAbnormal === true, `click=${toAbnormal}`)
  await sleep(300)

  await phoneB.setBySelector('.ms-field select', 'FORFEIT')
  await phoneB.evaluate(`(() => {
    const radios = [...document.querySelectorAll('input[name="ms-forfeit-side"]')]
    radios[1].click()
    return true
  })()`)
  await sleep(250)
  await phoneB.click('.ms-submit')
  await sleep(400)
  const needConfirm = await phoneB.evaluate(`!!document.querySelector('.ms-confirm')`)
  check('P1-H8 异常结果提交前有二次确认', needConfirm === true, `confirm=${needConfirm}`)
  await phoneB.evaluate(`(() => { const b = [...document.querySelectorAll('.ms-confirm button')]; b[b.length - 1].click(); return true })()`)

  const forfeitDone = await phoneB.waitForText('弃权')
  check('P1-H9 异常结果显示弃权结论', forfeitDone === true, 'forfeit text')
  const afterForfeit = (await matches()).find((m) => m.id === abnormal.id)
  check(
    'P1-H10 服务端 result_type=FORFEIT 且无逐局小分',
    afterForfeit.result_type === 'FORFEIT' && afterForfeit.games.length === 0,
    `result_type=${afterForfeit.result_type} games=${afterForfeit.games.length}`,
  )
  const forfeitTable = (await dashboard()).tables.find((t) => t.id === abnormal.table_id)
  check('P1-H11 异常结果结束后球台同样释放', forfeitTable?.status === 'FREE', `table=${abnormal.table_id} status=${forfeitTable?.status}`)

  await phoneB.close()
  }
}

// ---------------------------------------------------------------- P1-I Public live / BigScreen 更新

section('P1-I Public live 与 BigScreen 反映现场状态')
const readerCtx = await browser.newContext()
const phoneLive = await browser.newPage(readerCtx, { width: 390, height: 844 })
await phoneLive.prepare()
const bigCtx = await browser.newContext()
const bigScreen = await browser.newPage(bigCtx, { width: 1440, height: 900, count: false })
await bigScreen.prepare()

/** 大屏/实况页的进度文案，是“现场事实是否同步”的稳定可判定读数。 */
async function progressTextOf(page) {
  return page.evaluate(`document.querySelector('.bigscreen-progress span')?.textContent ?? null`)
}

{
  await phoneLive.goto(`${base}/public/t/${TID}/live`, '.bigscreen')
  await bigScreen.goto(`${base}/bigscreen?tid=${TID}`, '.bigscreen')
  await sleep(1800)

  const liveText = await phoneLive.text()
  const bigText = await bigScreen.text()
  check('P1-I1 Public live 可访问且渲染赛事信息', liveText.length > 20 && liveText.includes('正在进行'), `len=${liveText.length}`)
  check('P1-I2 BigScreen 可访问且不白屏', bigText.length > 20, `len=${bigText.length}`)
  check('P1-I3 Public live 无 undefined 赛事', !liveText.includes('undefined'), 'no undefined')

  const liveProgress = await progressTextOf(phoneLive)
  const bigProgress = await progressTextOf(bigScreen)
  check('P1-I4 Public live / BigScreen 都显示比赛进度（同一服务端事实）', Boolean(liveProgress) && liveProgress === bigProgress, `live=${liveProgress} big=${bigProgress}`)

  const livePlayingNames = await phoneLive.evaluate(`[...document.querySelectorAll('.bigscreen-table .bigscreen-pair')].map((n) => n.textContent).join('|')`)
  check('P1-I5 Public live 的「正在进行」列出了当前上场的对阵', livePlayingNames.length > 0, `pairs=${livePlayingNames.slice(0, 80)}`)

  // 写操作检查必须**限定在大屏组件内部**：/bigscreen 这层路由外面套着管理端 shell，
  // 它的侧边导航（"比赛控制 · 排台与录分"）和账号菜单（"修改密码"）不属于大屏。
  const bigWrites = await bigScreen.evaluate(`[...document.querySelectorAll('.bigscreen button, .bigscreen a')]
    .filter((n) => /删除|修改|保存|提交|排台|确认参赛|录分/.test(n.textContent || '')).length`)
  check('P1-I6 BigScreen 组件内部不暴露写操作入口', bigWrites === 0, `writeControls=${bigWrites}`)

  const publicWrites = await phoneLive.evaluate(`[...document.querySelectorAll('button,a')]
    .filter((n) => /删除|修改|保存|提交|排台|确认参赛|录分/.test(n.textContent || '')).length`)
  check('P1-I7 Public 实况页整页不暴露写操作入口', publicWrites === 0, `writeControls=${publicWrites}`)
}

// ---------------------------------------------------------------- P2 深链接 / 刷新

section('P2 深链接与刷新（每个终端独立 context，无历史 localStorage）')
{
  const publicPaths = [
    ['Public live', `/public/t/${TID}/live`],
    ['Public schedule', `/public/t/${TID}/schedule`],
    ['Public rankings', `/public/t/${TID}/rankings`],
    ['Public bracket', `/public/t/${TID}/bracket`],
    ['Public register', `/public/t/${TID}/register`],
  ]
  for (const [name, path] of publicPaths) {
    const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await page.prepare()
    const resp = await fetch(`${base}${path}`)
    const html = await resp.text()
    const spa = resp.status === 200 && html.includes('id="root"')
    await page.goto(`${base}${path}`, 'body')
    await sleep(900)
    const first = await page.text()
    await page.reload('body')
    await sleep(900)
    const afterReload = await page.text()
    const clean = first.length > 10 && afterReload.length > 10 && !first.includes('undefined') && !afterReload.includes('undefined')
    check(
      `P2 ${name} 深链接 + 刷新可用（不依赖 localStorage，无 undefined tid）`,
      spa && clean,
      `HTTP ${resp.status} first=${first.length} reload=${afterReload.length}`,
    )
    await page.close()
  }

  const mgrPaths = [
    ['Mobile Score', `/admin/t/${TID}/matches/${scoredNormal ?? (await matches())[0]?.id}/score`],
    ['BigScreen', `/bigscreen?tid=${TID}`],
    ['Console', `/console?tid=${TID}`],
  ]
  for (const [name, path] of mgrPaths) {
    const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await page.prepare()
    await page.login(USER, PASS)
    await page.goto(`${base}${path}`, 'body')
    await sleep(1000)
    const first = await page.text()
    await page.reload('body')
    await sleep(1000)
    const after = await page.text()
    check(
      `P2 ${name} 深链接 + 刷新可用`,
      first.length > 20 && after.length > 20,
      `first=${first.length} reload=${after.length}`,
    )
    await page.close()
  }
}

// ---------------------------------------------------------------- P3-A 多 Public 只读

section('P3-A 多 Public 只读并发')
{
  const readers = []
  for (const path of [
    `/public/t/${TID}/live`,
    `/public/t/${TID}/rankings`,
    `/public/t/${TID}/bracket`,
    `/public/t/${TID}/schedule`,
  ]) {
    const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await page.prepare()
    readers.push([path, page, page.goto(`${base}${path}`, 'body')])
  }
  await Promise.all(readers.map(([, , promise]) => promise))
  await sleep(1500)

  const results = []
  for (const [path, page] of readers) {
    results.push([path, (await page.text()).length])
  }
  check(
    'P3-A1 4 个只读客户端同时打开均正常渲染',
    results.every(([, len]) => len > 10),
    results.map(([p, l]) => `${p}=${l}`).join(' '),
  )
  for (const [path, page] of readers) {
    await page.reload('body')
    await sleep(700)
    const len = (await page.text()).length
    check(`P3-A2 ${path} 刷新后仍有内容（不丢赛事）`, len > 10, `len=${len}`)
    await page.close()
  }
}

// ---------------------------------------------------------------- P3-B Public + BigScreen + Console 同步

section('P3-B 管理端录入比分时 Public / BigScreen 在刷新周期内更新')
{
  const playing = await ensurePlaying(1)
  const target = playing[0]
  check('P3-B0 有一场可录分比赛已排台', Boolean(target), `match=${target?.id}`)

  if (target) {
    const beforeLive = await progressTextOf(phoneLive)
    const beforeBig = await progressTextOf(bigScreen)
    const beforeFinished = (await dashboard()).stats.finished

    const scorePhone = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await scorePhone.prepare()
    await scorePhone.login(USER, PASS)
    await scorePhone.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-submit')
    await scorePhone.setByLabel('大比分', 0, '3')
    await scorePhone.setByLabel('大比分', 1, '2')
    await scorePhone.click('.ms-submit')
    const ok = await scorePhone.waitForText('比分已保存')
    check('P3-B1 管理端（手机）录入新比分成功', ok === true, 'saved')

    await sleep(4000) // 大屏轮询周期约 2s
    const afterLive = await progressTextOf(phoneLive)
    const afterBig = await progressTextOf(bigScreen)
    const afterFinished = (await dashboard()).stats.finished
    check(
      'P3-B2 Public live 在刷新周期内推进进度',
      beforeLive !== afterLive && afterFinished === beforeFinished + 1,
      `before=${beforeLive} after=${afterLive} finished ${beforeFinished}->${afterFinished}`,
    )
    check(
      'P3-B3 BigScreen 在刷新周期内同步到同一事实',
      afterBig === afterLive,
      `live=${afterLive} big=${afterBig}`,
    )

    const afterLiveBody = await phoneLive.text()
    check('P3-B4 Public live 仍在正常渲染（未因同步而白屏）', afterLiveBody.length > 20, `len=${afterLiveBody.length}`)

    await scorePhone.close()
  }
}

// ---------------------------------------------------------------- P3-C 两台手机同时录不同比赛

section('P3-C 两台手机同时录不同比赛')
{
  const playing = await ensurePlaying(2)
  const first = playing[0]
  const second = playing[1]
  check('P3-C0 已排好两场互不冲突的不同比赛', Boolean(first && second && first.id !== second.id), `m1=${first?.id} m2=${second?.id}`)

  if (first && second) {
    const p1 = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    const p2 = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await p1.prepare(); await p2.prepare()
    await p1.login(USER, PASS)
    await p2.login(USER, PASS)

    await p1.goto(`${base}/admin/t/${TID}/matches/${first.id}/score`, '.ms-submit')
    await p2.goto(`${base}/admin/t/${TID}/matches/${second.id}/score`, '.ms-submit')
    await p1.setByLabel('大比分', 0, '3')
    await p1.setByLabel('大比分', 1, '2')
    await p2.setByLabel('大比分', 0, '1')
    await p2.setByLabel('大比分', 1, '3')

    await Promise.all([
      p1.click('.ms-submit').then(() => p1.waitForText('比分已保存')),
      p2.click('.ms-submit').then(() => p2.waitForText('比分已保存')),
    ])

    const after = await matches()
    const a1 = after.find((m) => m.id === first.id)
    const a2 = after.find((m) => m.id === second.id)
    check('P3-C1 两台手机并发提交不同比赛均成功', a1.status === 'FINISHED' && a2.status === 'FINISHED', `m1=${a1.status} m2=${a2.status}`)
    check(
      'P3-C2 比分未串场（各自比分正确）',
      a1.player_a_score === 3 && a1.player_b_score === 2 && a2.player_a_score === 1 && a2.player_b_score === 3,
      `m1=${a1.player_a_score}:${a1.player_b_score} m2=${a2.player_a_score}:${a2.player_b_score}`,
    )
    check('P3-C3 两场比赛归属与球台未互换', a1.id !== a2.id && a1.table_id !== a2.table_id, `tables ${a1.table_id} vs ${a2.table_id}`)
    const tables = (await dashboard()).tables
    const t1 = tables.find((t) => t.id === a1.table_id)
    const t2 = tables.find((t) => t.id === a2.table_id)
    check('P3-C4 两场比赛对应的球台都已正确释放', t1?.status === 'FREE' && t2?.status === 'FREE', `${t1?.status}/${t2?.status}`)
    await p1.close(); await p2.close()
  }
}

// ---------------------------------------------------------------- P3-D 同一场比赛多端并发 / 重复提交

section('P3-D 两台手机同时操作同一场比赛')
{
  const playing = await ensurePlaying(1)
  const target = playing[0]
  check('P3-D0 有一场可录分比赛已排台', Boolean(target), `match=${target?.id}`)

  if (target) {
    const q1 = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    const q2 = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await q1.prepare(); await q2.prepare()
    await q1.login(USER, PASS)
    await q2.login(USER, PASS)
    await q1.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-submit')
    await q2.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-submit')

    // 两端给出**不同**比分并同时提交：数据库最终只能是其中一方，不能出现互相矛盾的最终事实
    await q1.setByLabel('大比分', 0, '3')
    await q1.setByLabel('大比分', 1, '0')
    await q2.setByLabel('大比分', 0, '3')
    await q2.setByLabel('大比分', 1, '2')
    await Promise.all([q1.click('.ms-submit'), q2.click('.ms-submit')])
    await sleep(3000)

    const final = (await matches()).find((m) => m.id === target.id)
    const isOneOfThem =
      final.player_a_score === 3 && (final.player_b_score === 0 || final.player_b_score === 2)
    check(
      'P3-D1 同场并发提交不产生矛盾的最终事实',
      final.status === 'FINISHED' && isOneOfThem,
      `status=${final.status} ${final.player_a_score}:${final.player_b_score}`,
    )

    const audits = await api(`/api/matches/${target.id}/score-audits`)
    const records = Array.isArray(audits.body) ? audits.body.filter((a) => a.action === 'RECORD') : []
    check('P3-D2 审计账本只有一条 RECORD（不静默覆盖）', records.length === 1, `RECORD=${records.length}`)

    // 已结束的比赛：UI 不再提供提交入口
    await q1.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-shell')
    await sleep(800)
    const hasSubmit = await q1.evaluate(`!!document.querySelector('.ms-submit')`)
    const showsDone = await q1.waitForText('比分已保存')
    check('P3-D3 已结束比赛的录分页不再提供提交入口', hasSubmit === false && showsDone === true, `submit=${hasSubmit} done=${showsDone}`)

    // 服务端层：不同 request_id 重复提交必须被拒绝，且不改变最终比分
    const dup = await api(`/api/matches/${target.id}/score`, {
      method: 'POST',
      body: { player_a_score: 3, player_b_score: 2, result_type: 'NORMAL', request_id: crypto.randomUUID() },
    })
    const again = (await matches()).find((m) => m.id === target.id)
    check(
      'P3-D4 已结束比赛重复提交被服务端拒绝，比分不变',
      dup.status >= 400 && again.player_a_score === final.player_a_score && again.player_b_score === final.player_b_score,
      `HTTP ${dup.status} score=${again.player_a_score}:${again.player_b_score}`,
    )

    // 幂等：同一 request_id 重放同一载荷 → 不产生第二条事实
    const requestId = crypto.randomUUID()
    const payload = { player_a_score: 3, player_b_score: 0, result_type: 'NORMAL', request_id: requestId }
    const before = (await matches()).find((m) => m.id === target.id)
    await api(`/api/matches/${target.id}/score`, { method: 'POST', body: payload })
    await api(`/api/matches/${target.id}/score`, { method: 'POST', body: payload })
    const afterReplay = (await matches()).find((m) => m.id === target.id)
    const auditsAfter = await api(`/api/matches/${target.id}/score-audits`)
    const recordCount = Array.isArray(auditsAfter.body) ? auditsAfter.body.filter((a) => a.action === 'RECORD').length : -1
    check(
      'P3-D5 同一 request_id 重放（网络抖动重试）不产生第二条事实',
      before.player_a_score === afterReplay.player_a_score
        && before.player_b_score === afterReplay.player_b_score
        && recordCount === 1,
      `score=${afterReplay.player_a_score}:${afterReplay.player_b_score} RECORD=${recordCount}`,
    )

    await q1.close(); await q2.close()
  }
}

// ---------------------------------------------------------------- P5 Public 断网 / 恢复

section('P5 Public 页面断网 → 恢复')
{
  const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
  await page.prepare()
  await page.goto(`${base}/public/t/${TID}/live`, '.bigscreen')
  await sleep(1200)
  const beforeOffline = await page.text()

  await page.setOffline(true)
  await sleep(7000)
  const offText = await page.text()
  check(
    'P5-1 断网后页面不崩溃（已有内容保留，不白屏）',
    offText.length >= 10 && offText.length >= beforeOffline.length * 0.5,
    `before=${beforeOffline.length} offline=${offText.length}`,
  )
  check('P5-2 断网后不出现 undefined / 未捕获错误页', !offText.includes('undefined'), 'no undefined')

  await page.setOffline(false)
  await sleep(5000)
  const recovered = await page.text()
  check('P5-3 恢复网络后页面可继续使用（无需清缓存 / 重新登录）', recovered.length > 10, `len=${recovered.length}`)
  await page.close()
}

// ---------------------------------------------------------------- P5b Mobile Score 断网提交

section('P5b Mobile Score 断网提交必须明确失败且不清空输入')
{
  const playing = await ensurePlaying(1)
  const target = playing[0]
  check('P5b-0 有一场可录分比赛已排台', Boolean(target), `match=${target?.id}`)

  if (target) {
    const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await page.prepare()
    await page.login(USER, PASS)
    await page.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-submit')
    await page.setByLabel('大比分', 0, '3')
    await page.setByLabel('大比分', 1, '1')

    await page.setOffline(true)
    await page.click('.ms-submit')
    await sleep(6000)

    const error = await page.evaluate(`document.querySelector('.ms-error')?.textContent ?? null`)
    const inputs = await page.evaluate(`[...document.querySelectorAll('.ms-score-input')].map((i) => i.value).join(',')`)
    const savedClaim = await page.evaluate(`!!document.querySelector('.ms-done-title')`)
    check('P5b-1 断网提交不会假装成功', savedClaim === false, `doneCard=${savedClaim}`)
    check('P5b-2 断网提交显示明确失败提示', typeof error === 'string' && error.length > 0, `error=${error}`)
    check('P5b-3 断网失败后输入未被清空', inputs === '3,1', `inputs=${inputs}`)

    const serverSide = (await matches()).find((m) => m.id === target.id)
    check('P5b-4 服务端没有写入这笔未成功的提交', serverSide.status !== 'FINISHED', `status=${serverSide.status}`)

    await page.setOffline(false)
    await sleep(800)
    await page.click('.ms-submit')
    const ok = await page.waitForText('比分已保存')
    check('P5b-5 恢复网络后重新提交成功', ok === true, 'saved after reconnect')
    const after = (await matches()).find((m) => m.id === target.id)
    check(
      'P5b-6 服务端最终比分正确',
      after.status === 'FINISHED' && after.player_a_score === 3 && after.player_b_score === 1,
      `${after.player_a_score}:${after.player_b_score}`,
    )
    await page.close()
  }
}

// ---------------------------------------------------------------- P5c 已保存但刷新失败（回归）

section('P5c 「比分已保存，但最新状态刷新失败」不得被报成本次提交失败')
{
  const playing = await ensurePlaying(1)
  const target = playing[0]
  check('P5c-0 有一场可录分比赛已排台', Boolean(target), `match=${target?.id}`)

  if (target) {
    const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await page.prepare()
    await page.login(USER, PASS)
    // 在页面内拦截“提交后重新拉取比赛”的 GET，让 POST 成功后 reload 失败
    await page.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-submit')
    await page.evaluate(`(() => {
      window.__blockReload = false
      const original = window.fetch
      window.fetch = (input, options) => {
        const url = String(input)
        if (window.__blockReload && url.includes('/api/tournaments/${TID}/matches') && (options?.method ?? 'GET') === 'GET') {
          return Promise.reject(new TypeError('Failed to fetch (D6D injected)'))
        }
        return original(input, options)
      }
      return true
    })()`)
    await page.setByLabel('大比分', 0, '3')
    await page.setByLabel('大比分', 1, '0')
    await page.evaluate(`(window.__blockReload = true)`)
    await page.click('.ms-submit')
    await sleep(3500)

    const warning = await page.evaluate(`document.querySelector('.ms-refresh-warning')?.textContent ?? null`)
    const formError = await page.evaluate(`document.querySelector('.ms-error')?.textContent ?? null`)
    check('P5c-1 POST 成功、reload 失败时给出「比分已保存…刷新失败」提示', typeof warning === 'string' && warning.includes('比分已保存'), `warning=${warning}`)
    check('P5c-2 不得提示“本次比分提交失败”（否则诱导重复提交）', formError === null, `formError=${formError}`)

    const after = (await matches()).find((m) => m.id === target.id)
    check('P5c-3 服务端确实已保存该比分', after.status === 'FINISHED' && after.player_a_score === 3 && after.player_b_score === 0, `status=${after.status} ${after.player_a_score}:${after.player_b_score}`)
    await page.close()
  }
}

// ---------------------------------------------------------------- P6 后台 / 恢复

section('P6 手机切后台 35s 后回前台')
{
  const page = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
  await page.prepare()
  await page.goto(`${base}/public/t/${TID}/live`, '.bigscreen')
  await sleep(1000)
  await page.freeze()
  await sleep(35000)
  await page.activate()
  await sleep(5000)
  const text = await page.text()
  check('P6-1 后台恢复后页面仍可用（无无限 loading）', text.length > 10 && !text.includes('正在加载'), `len=${text.length}`)
  await page.reload('.bigscreen')
  await sleep(1200)
  check('P6-2 后台恢复后可重新取到最新状态', (await page.text()).length > 10, `len=${(await page.text()).length}`)

  // 录分页切后台后仍能完成一次录分
  const playing = await ensurePlaying(1)
  const target = playing[0]
  if (target) {
    const scorePage = await browser.newPage(await browser.newContext(), { width: 390, height: 844 })
    await scorePage.prepare()
    await scorePage.login(USER, PASS)
    await scorePage.goto(`${base}/admin/t/${TID}/matches/${target.id}/score`, '.ms-submit')
    await scorePage.freeze()
    await sleep(35000)
    await scorePage.activate()
    await sleep(3000)
    await scorePage.setByLabel('大比分', 0, '3')
    await scorePage.setByLabel('大比分', 1, '0')
    await scorePage.click('.ms-submit')
    const ok = await scorePage.waitForText('比分已保存')
    check('P6-3 切后台 35s 后仍能完成一次录分', ok === true, 'scored after foreground')
    await scorePage.close()
  } else {
    check('P6-3 切后台 35s 后仍能完成一次录分', false, 'no WAITING match left')
  }
  await page.close()
}

// ---------------------------------------------------------------- 汇总

lines.push('')
lines.push(`CLIENTS simulated=${phoneCount} (real phones=0; 管理电脑与大屏不计入)`)
const passCount = lines.filter((l) => l.startsWith('[PASS]')).length
const totalCount = lines.filter((l) => l.startsWith('[PASS]') || l.startsWith('[FAIL]')).length
lines.push('')
lines.push(`=== D6D field simulation: ${passCount}/${totalCount} PASS ===`)
if (failures.length) lines.push(`FAILURES: ${failures.join(' | ')}`)

const snapshotPath = process.env.D6D_SNAPSHOT ?? `${process.env.TEMP ?? '.'}/d6d_snapshot.json`
const finalTournament = await tournament()
const finalMatches = await matches()
const { writeFileSync } = await import('node:fs')
writeFileSync(
  snapshotPath,
  JSON.stringify(
    {
      tid: TID,
      base,
      capturedAt: new Date().toISOString(),
      roster_confirmed: finalTournament.roster_confirmed,
      stage: finalTournament.stage,
      registration_enabled: finalTournament.registration_enabled,
      players: (await api(`/api/tournaments/${TID}/players`)).body?.length ?? null,
      entries: (await api(`/api/tournaments/${TID}/entries`)).body?.length ?? null,
      matches: finalMatches.length,
      finished: finalMatches.filter((m) => m.status === 'FINISHED').map((m) => ({ id: m.id, a: m.player_a_score, b: m.player_b_score, result_type: m.result_type })),
      playing: finalMatches.filter((m) => m.status === 'PLAYING').map((m) => m.id),
      waiting: finalMatches.filter((m) => m.status === 'WAITING').map((m) => m.id),
    },
    null,
    2,
  ),
)
lines.push(`SNAPSHOT=${snapshotPath}`)

console.log(lines.join('\n'))

for (const ctx of [adminCtx, readerCtx, bigCtx]) await browser.disposeContext(ctx)
process.exit(failures.length ? 1 : 0)
