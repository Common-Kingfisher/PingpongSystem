/**
 * C 轨 Day5 Phase 4：管理端现场运行验收（1280×900 / 1440×900）。
 *
 * ## 本脚本只负责「C 轨特有、D6D harness 没覆盖」的部分
 *
 * D6D（`day6d_field_simulation.mjs` / `day6d_public_viewport_check.mjs`）已经覆盖：
 * 报名 → 名单 → 分组 → 生成比赛 → 排台 → 手机录分 → Public/BigScreen 同步 → 重启续赛，
 * 以及 360–430px 的 Public/移动端布局。**本脚本不重做那些流程**，只补管理端桌面端：
 *
 * ```text
 * /            赛事总览：无白屏、无 console error、无横向溢出
 * /console     5 秒轮询真实发生；hidden 暂停；断网保留快照 + stale；恢复后自动清除
 * /schedule    实时赛程默认展示；打印快照语义齐全；A4 打印下导航与按钮被隐藏
 * /orderbook   明确"暂未关联官方秩序册"；不冒充官方发布版本
 * ```
 *
 * ## 判定原则
 *
 * * 不把「好看」当 PASS：只判定可操作性与事实正确性；
 * * `console.error` 必须为 0（D 轨的 `[api] ... -> 4xx` 诊断是预期日志，按 URL 白名单区分）；
 * * 横向溢出只在**真的够不到**时算失败（页面本就有合法横向滚动区）；
 * * 需要特殊环境的项目（真实手机 / 真实路由器）明确记为 NOT RUN，不写成 PASS。
 *
 * 用法：
 * ```powershell
 * node .\c_day5_admin_field_check.mjs <base> <tid> <user> <pass>
 * ```
 */

import { sleep } from './day3_cdp_auth.mjs'

const CDP_PORT = process.env.CDP_PORT ?? '9333'
const base = (process.argv[2] ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
const TID = Number(process.argv[3] ?? '1')
const USER = process.argv[4] ?? 'd6d-admin'
const PASS = process.argv[5] ?? 'd6d-admin-pass1'

const VIEWPORTS = [
  { width: 1280, height: 900, label: '1280x900' },
  { width: 1440, height: 900, label: '1440x900' },
]

const failures = []
const lines = []

function check(name, ok, detail) {
  const line = `[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`
  lines.push(line)
  console.log(line)
  if (!ok) failures.push(name)
}

function note(name, detail) {
  const line = `[NOTE] ${name} :: ${detail}`
  lines.push(line)
  console.log(line)
}

async function connect() {
  const version = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`)).json()
  const ws = new WebSocket(version.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  /** sessionId → 事件处理器列表（CDP flatten 模式下事件带 sessionId）。 */
  const subscribers = new Map()
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg)
      pending.delete(msg.id)
      return
    }
    if (!msg.method) return
    const sessionId = msg.sessionId ?? ''
    for (const fn of subscribers.get(sessionId) ?? []) fn(msg)
    for (const fn of subscribers.get('*') ?? []) fn(msg, sessionId)
  })
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve)
    ws.addEventListener('error', reject)
  })
  return {
    send: (method, params = {}, sessionId) =>
      new Promise((resolve) => {
        const i = ++id
        pending.set(i, resolve)
        ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }))
      }),
    subscribe: (sessionId, fn) => {
      const key = sessionId ?? '*'
      if (!subscribers.has(key)) subscribers.set(key, [])
      subscribers.get(key).push(fn)
    },
    close: () => ws.close(),
  }
}

async function openPage(browser, viewport, { login = false } = {}) {
  const browserContextId = (await browser.send('Target.createBrowserContext', {})).result.browserContextId
  const targetId = (await browser.send('Target.createTarget', { url: 'about:blank', browserContextId })).result.targetId
  const sessionId = (await browser.send('Target.attachToTarget', { targetId, flatten: true })).result.sessionId
  const send = (method, params = {}) => browser.send(method, params, sessionId)

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Network.enable')
  await send('Network.setCacheDisabled', { cacheDisabled: true })

  const consoleErrors = []
  const pageExceptions = []
  const requests = []
  browser.subscribe(sessionId, (msg) => {
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
      const text = (msg.params.args ?? []).map((a) => a.value ?? a.description ?? '').join(' ')
      consoleErrors.push(text)
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      pageExceptions.push(msg.params?.exceptionDetails?.exception?.description ?? 'unknown exception')
    }
    if (msg.method === 'Network.requestWillBeSent') requests.push(msg.params?.request?.url ?? '')
  })

  const evaluate = async (expression) => {
    const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (out.result?.exceptionDetails) {
      throw new Error(out.result.exceptionDetails.exception?.description ?? 'evaluate failed')
    }
    return out.result?.result?.value
  }

  if (login) {
    await send('Page.navigate', { url: `${base}/` })
    await sleep(700)
    const status = await evaluate(`(async () => {
      const resp = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username: ${JSON.stringify(USER)}, password: ${JSON.stringify(PASS)}, mode: 'browser' })
      })
      return resp.status
    })()`)
    if (status !== 200) throw new Error(`登录失败: HTTP ${status}`)
  }

  await send('Emulation.setDeviceMetricsOverride', {
    width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false,
  })

  return {
    evaluate,
    sessionId,
    consoleErrors,
    pageExceptions,
    requests,
    navigate: async (url) => {
      consoleErrors.length = 0
      pageExceptions.length = 0
      await send('Page.navigate', { url })
      await sleep(400)
    },
    setOffline: (offline) => send('Network.emulateNetworkConditions', {
      offline, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
    }),
    close: () => browser.send('Target.closeTarget', { targetId }),
  }
}

async function waitFor(page, selector, tries = 80) {
  for (let i = 0; i < tries; i += 1) {
    await sleep(150)
    const ok = await page.evaluate(`!!document.querySelector(${JSON.stringify(selector)})`).catch(() => false)
    if (ok) return true
  }
  return false
}

async function waitForText(page, text, tries = 80) {
  for (let i = 0; i < tries; i += 1) {
    await sleep(150)
    const ok = await page.evaluate(`(document.body.innerText || '').includes(${JSON.stringify(text)})`).catch(() => false)
    if (ok) return true
  }
  return false
}

/** 布局事实：无「够不到」的横向溢出，且关键元素与正文都真的渲染了。 */
const MEASURE = (critical) => `(() => {
  const reachableByScrolling = (el) => {
    let p = el.parentElement
    while (p && p !== document.documentElement) {
      const cs = getComputedStyle(p)
      if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && p.scrollWidth > p.clientWidth + 1) return true
      p = p.parentElement
    }
    return false
  }
  const name = (el) => (typeof el.className === 'string' && el.className.trim()
    ? '.' + el.className.trim().split(/\\s+/)[0]
    : el.tagName)
  const overflow = [...document.querySelectorAll('body *')]
    .filter((el) => {
      const r = el.getBoundingClientRect()
      return r.width > 0 && r.height > 0 && r.right > window.innerWidth + 0.5
    })
    .filter((el) => !reachableByScrolling(el))
    .slice(0, 6)
    .map(name)
  return {
    innerWidth: window.innerWidth,
    docScrollWidth: document.documentElement.scrollWidth,
    overflow,
    bodyLength: (document.body.innerText || '').length,
    critical: Object.fromEntries(${JSON.stringify(critical)}.map((s) => [s, !!document.querySelector(s)])),
  }
})()`

// --------------------------------------------------------------- 场景

async function main() {
  const browser = await connect()

  note('base', base)
  note('tid', String(TID))

  const admin = await openPage(browser, VIEWPORTS[0], { login: true })

  // ---------------------------------------------------------- 1. 四个管理端页面
  const PAGES = [
    {
      url: `${base}/?tid=${TID}`,
      name: '赛事总览 /',
      ready: '.admin-dashboard',
      critical: ['.admin-dashboard', '.admin-progress-panel', '.admin-table-summary'],
      expectText: '比赛进度',
    },
    {
      url: `${base}/console?tid=${TID}`,
      name: '比赛控制台 /console',
      ready: '.live-table-card',
      critical: ['.console-sync', '.live-table-stack', '.console-actions'],
      expectText: '比赛现场',
    },
    {
      url: `${base}/schedule?tid=${TID}`,
      name: '实时赛程 /schedule',
      ready: '.schedule-table, .card',
      critical: ['.print-snapshot-meta', '.schedule-tools'],
      expectText: '实时赛程',
    },
    {
      url: `${base}/orderbook?tid=${TID}`,
      name: '赛程与秩序 /orderbook',
      ready: '.order-book',
      critical: ['.order-official-notice', '.order-book'],
      expectText: '暂未关联官方秩序册',
    },
  ]

  for (const viewport of VIEWPORTS) {
    for (const spec of PAGES) {
      const page = await openPage(browser, viewport, { login: true })
      await page.navigate(spec.url)
      const ready = await waitFor(page, spec.ready)
      const found = await waitForText(page, spec.expectText)
      const m = await page.evaluate(MEASURE(spec.critical))

      check(`${viewport.label} ${spec.name} 渲染完成`, ready && m.bodyLength > 200,
        `ready=${ready} bodyLength=${m.bodyLength}`)
      check(`${viewport.label} ${spec.name} 关键内容`, found, `expect="${spec.expectText}"`)
      for (const [selector, present] of Object.entries(m.critical)) {
        check(`${viewport.label} ${spec.name} ${selector}`, present, present ? 'present' : 'MISSING')
      }
      check(`${viewport.label} ${spec.name} 无够不到的横向溢出`, m.overflow.length === 0,
        `docScrollWidth=${m.docScrollWidth} innerWidth=${m.innerWidth} overflow=[${m.overflow.join(', ')}]`)
      // D 轨的 [api] 4xx 诊断是预期日志；其余 console.error 一律算失败。
      const unexpected = page.consoleErrors.filter((t) => !t.startsWith('[api]'))
      check(`${viewport.label} ${spec.name} 无未处理 console error`, unexpected.length === 0,
        unexpected.length ? unexpected.slice(0, 2).join(' | ') : '0')
      check(`${viewport.label} ${spec.name} 无未捕获异常`, page.pageExceptions.length === 0,
        page.pageExceptions.length ? page.pageExceptions[0].slice(0, 160) : '0')
      await page.close()
    }
  }

  // ---------------------------------------------------------- 2. Console 5 秒轮询
  {
    const page = await openPage(browser, VIEWPORTS[0], { login: true })
    await page.navigate(`${base}/console?tid=${TID}`)
    await waitFor(page, '.console-sync')
    const countDashboard = () => page.requests.filter((u) => u.includes('/dashboard')).length

    const t0 = countDashboard()
    await sleep(12_000)
    const t1 = countDashboard()
    // 12 秒内应发生 2–4 次轮询（首次 + 5s + 10s），留出调度余量
    const polls = t1 - t0
    check('Console 5 秒轮询真实发生', polls >= 2 && polls <= 5,
      `12s 内 /dashboard 请求 = ${polls}（期望 2–5）`)

    const syncText = await page.evaluate(`document.querySelector('.console-sync')?.textContent ?? ''`)
    check('Console 显示自动同步与最近同步时间', syncText.includes('5 秒') && syncText.includes('最近同步'),
      syncText.replace(/\s+/g, ' ').slice(0, 80))

    // 切后台 → 暂停
    await page.evaluate(`Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
      document.dispatchEvent(new Event('visibilitychange')); true`)
    const beforeHidden = countDashboard()
    await sleep(7_000)
    const afterHidden = countDashboard()
    check('Console hidden 时暂停轮询', afterHidden - beforeHidden === 0,
      `hidden 7s 内新增 /dashboard 请求 = ${afterHidden - beforeHidden}`)

    // 断网 → stale，且保留已有内容
    await page.setOffline(true)
    await page.evaluate(`Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
      document.dispatchEvent(new Event('visibilitychange')); true`)
    const staleShown = await waitForText(page, '当前显示可能不是最新状态', 60)
    const kept = await page.evaluate(`(() => ({
      tables: document.querySelectorAll('.live-table-card').length,
      progress: (document.body.innerText.match(/比赛进度\\s*\\d+\\s*\\/\\s*\\d+/) ?? [''])[0],
      synced: (document.querySelector('.console-sync')?.textContent ?? '').includes('最近同步'),
    }))()`)
    check('Console 断网后显示 stale', staleShown, staleShown ? 'shown' : 'NOT shown')
    check('Console 断网后保留最后成功快照', kept.tables > 0 && kept.progress !== '',
      `球台卡片=${kept.tables} ${kept.progress.trim()} 最近同步=${kept.synced}`)

    // 恢复网络 → 自动清除 stale
    await page.setOffline(false)
    const recovered = await page.evaluate(`(async () => {
      for (let i = 0; i < 60; i += 1) {
        await new Promise((r) => setTimeout(r, 250))
        const el = document.querySelector('.console-sync')
        if (el && !el.classList.contains('is-stale')) return true
      }
      return false
    })()`)
    check('Console 恢复网络后自动清除 stale', recovered === true, String(recovered))
    await page.close()
  }

  // ---------------------------------------------------------- 3. 排台操作后数据更新
  {
    const page = await openPage(browser, VIEWPORTS[0], { login: true })
    await page.navigate(`${base}/console?tid=${TID}`)
    await waitFor(page, '.live-table-card')
    const hasBatch = await page.evaluate(`!!([...document.querySelectorAll('button')].find((b) => b.textContent.includes('自动安排下一批比赛')))`)
    if (hasBatch) {
      const before = await page.evaluate(`(document.body.innerText.match(/比赛进度\\s*(\\d+)\\s*\\/\\s*(\\d+)/) ?? []).slice(1).join('/')`)
      await page.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.includes('自动安排下一批比赛')).click(); true`)
      let after = before
      for (let i = 0; i < 40; i += 1) {
        await sleep(250)
        after = await page.evaluate(`(document.body.innerText.match(/比赛进度\\s*(\\d+)\\s*\\/\\s*(\\d+)/) ?? []).slice(1).join('/')`)
        const playing = await page.evaluate(`(document.querySelectorAll('.live-table-card.is-playing').length)`)
        if (playing > 0) break
      }
      const playingCards = await page.evaluate(`document.querySelectorAll('.live-table-card.is-playing').length`)
      const playingStat = await page.evaluate(`(document.body.innerText.match(/正在进行\\s*(\\d+)/) ?? [])[1] ?? '?'`)
      check('Console 自动排台后现场状态更新', playingCards > 0,
        `进行中球台=${playingCards} 后端正在比赛=${playingStat} 已完成 ${before} → ${after}`)
    } else {
      note('Console 自动排台', '当前无待安排比赛（阶段已收口或比赛已排满），跳过点击验证')
    }
    await page.close()
  }

  // ---------------------------------------------------------- 4. A4 打印
  {
    const page = await openPage(browser, VIEWPORTS[1], { login: true })
    await page.navigate(`${base}/schedule?tid=${TID}`)
    await waitFor(page, '.print-snapshot-meta')
    await browser.send('Emulation.setEmulatedMedia', { media: 'print' }, page.sessionId)
    await sleep(400)
    const printState = await page.evaluate(`(() => {
      const vis = (sel) => {
        const el = document.querySelector(sel)
        if (!el) return 'absent'
        return getComputedStyle(el).display === 'none' ? 'hidden' : 'visible'
      }
      return {
        sidebar: vis('.admin-sidebar'),
        topbar: vis('.admin-topbar'),
        tools: vis('.schedule-tools'),
        meta: vis('.print-snapshot-meta'),
        table: vis('.schedule-table'),
        metaText: (document.querySelector('.print-snapshot-meta')?.textContent ?? '').replace(/\\s+/g, ' '),
        tableWidth: document.querySelector('.schedule-table')?.getBoundingClientRect().width ?? 0,
      }
    })()`)
    check('打印时隐藏管理端导航', printState.sidebar === 'hidden' && printState.topbar === 'hidden',
      `sidebar=${printState.sidebar} topbar=${printState.topbar}`)
    check('打印时隐藏交互控件', printState.tools === 'hidden', `schedule-tools=${printState.tools}`)
    check('打印内容包含快照时间与数据状态', printState.meta === 'visible'
      && printState.metaText.includes('生成时间') && printState.metaText.includes('实时系统快照')
      && printState.metaText.includes('非官方秩序册'), printState.metaText.slice(0, 120))
    check('打印时比赛表格可见且未横向溢出', printState.table === 'visible' && printState.tableWidth <= 1440,
      `table=${printState.table} width=${Math.round(printState.tableWidth)}`)
    await browser.send('Emulation.setEmulatedMedia', { media: '' }, page.sessionId)
    await page.close()
  }

  // ---------------------------------------------------------- 5. 秩序册语义
  {
    const page = await openPage(browser, VIEWPORTS[0], { login: true })
    await page.navigate(`${base}/orderbook?tid=${TID}`)
    await waitFor(page, '.order-official-notice')
    const text = await page.evaluate(`document.querySelector('.order-official-notice').textContent`)
    const footer = await page.evaluate(`document.querySelector('.order-book footer')?.textContent ?? ''`)
    check('秩序册页明确"暂未关联官方秩序册"', text.includes('暂未关联官方秩序册'), text.replace(/\s+/g, ' ').slice(0, 90))
    check('秩序册页不冒充官方发布版本',
      text.includes('不是') && !text.includes('已生成官方秩序册'), 'notice semantics')
    check('秩序册页打印快照带生成时间与实时状态',
      footer.includes('生成时间') && footer.includes('实时系统快照') && footer.includes('非官方秩序册'),
      footer.replace(/\s+/g, ' ').slice(0, 140))
    await page.close()
  }

  // ---------------------------------------------------------- 6. 失效 tid
  {
    const page = await openPage(browser, VIEWPORTS[0], { login: true })
    await page.navigate(`${base}/console?tid=999999`)
    const bounded = await waitForText(page, '现场数据加载失败', 60)
    const stillLoading = await page.evaluate(`(document.body.innerText || '').includes('正在加载赛事数据')`)
    check('失效 tid 不无限 loading', bounded && !stillLoading,
      `error=${bounded} stillLoading=${stillLoading}`)
    await page.close()
  }

  await admin.close()
  browser.close()

  console.log('')
  const passed = lines.filter((l) => l.startsWith('[PASS]')).length
  const total = passed + failures.length
  console.log(`C-D5 ADMIN FIELD GATE: ${passed}/${total} PASS`)
  if (failures.length) {
    console.log('FAILED:')
    for (const f of failures) console.log(`  - ${f}`)
    return 1
  }
  return 0
}

main().then((code) => process.exit(code)).catch((error) => {
  console.error('HARNESS ERROR:', error)
  process.exit(2)
})
