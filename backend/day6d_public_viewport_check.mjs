/**
 * D 轨 Day6D Phase 9：移动 / Public 小屏与超长文本检查（360 / 375 / 390 / 430）。
 *
 * ## 覆盖页面（D 轨负责的移动端 / Public 端）
 *
 * ```text
 * Public Live      /public/t/{playTid}/live            超长赛事名 + 超长选手名
 * Public Rankings  /public/t/{playTid}/rankings
 * Public Bracket   /public/t/{playTid}/bracket
 * Public Register  /public/t/{openTid}/register        报名**表单态**（不是关闭态）
 * Mobile Score     /admin/t/{playTid}/matches/{mid}/score   需真实登录
 * ```
 *
 * ## 判定的是「现场能不能操作」，不是「好不好看」
 *
 * * 无横向溢出（`documentElement.scrollWidth <= 视口宽`）；
 * * 没有元素被挤出右边界；
 * * 关键触摸目标高度 >= 44px（手机可点）；
 * * 指定的**长文本容器**自己也没有被文字硬撑破（`scrollWidth <= clientWidth + 1`）；
 * * 关键按钮存在且可见（不会因为布局被吞掉）。
 *
 * 刻意不做全局 `scrollWidth > clientWidth` 扫描：页面上本来就有合法的横向滚动容器
 * （Public 顶部导航、数据表格），全局扫描只会产出假失败。
 *
 * ## 用法
 *
 * ```powershell
 * # 前置：production 单服务已启动 + Chrome 已开 CDP（端口 9333）
 * node .\day6d_public_viewport_check.mjs <base> <playTid> <user> <pass> <matchId> <openTid>
 * ```
 */

import { sleep } from './day3_cdp_auth.mjs'

const CDP_PORT = process.env.CDP_PORT ?? '9333'
const base = (process.argv[2] ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
const PLAY_TID = Number(process.argv[3] ?? '1')
const USER = process.argv[4] ?? 'd6d-admin'
const PASS = process.argv[5] ?? 'd6d-admin-pass1'
const MATCH_ID = Number(process.argv[6] ?? '0') || null
const OPEN_TID = Number(process.argv[7] ?? String(PLAY_TID))

const VIEWPORTS = [
  { width: 360, height: 740 },
  { width: 375, height: 812 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
]

const failures = []
const lines = []

function check(name, ok, detail) {
  const line = `[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`
  lines.push(line)
  console.log(line)
  if (!ok) failures.push(name)
}

/**
 * 记录一条**已知且本轮不改**的现场观察（P2 / 设计如此），不计入失败。
 *
 * 用来把「量到的真实数值」留证，同时不让 gate 被已知的非阻塞问题拖红。
 */
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
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
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
  return { send }
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

  const evaluate = async (expression) => {
    const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    return out.result?.result?.value
  }

  if (login) {
    await send('Page.navigate', { url: `${base}/` })
    await sleep(600)
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
    width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: true,
  })
  return {
    evaluate,
    navigate: (url) => send('Page.navigate', { url }),
    close: () => browser.send('Target.closeTarget', { targetId }),
  }
}

/** 等某个选择器出现（页面真的渲染完成），最多 ~12s。 */
async function waitFor(page, selector, tries = 80) {
  for (let i = 0; i < tries; i += 1) {
    await sleep(150)
    const ok = await page.evaluate(`!!document.querySelector(${JSON.stringify(selector)})`).catch(() => false)
    if (ok) return true
  }
  return false
}

/**
 * 量测当前视口的布局事实。
 *
 * `longText` 是必须「自己也没被文字撑破」的长文本容器选择器。
 *
 * ⚠️ 「超出右边界」只在**够不到**时才算失败：
 * 页面里本来就有合法的横向滚动区域（Public 顶部导航 `.pub-nav-inner`、
 * 窄屏下的 `.card` 包着宽表格）。判断方法是向上找有没有
 * `overflow-x: auto|scroll` **且真的可滚** 的祖先 ——
 * `overflow-x: hidden`（如 `.pub-shell`）不算，那种情况内容是**被静默裁掉**的。
 */
const MEASURE = (critical, longText, mustFit, gridTracks) => `(() => {
  const criticalSels = ${JSON.stringify(critical)}
  const longTextSels = ${JSON.stringify(longText)}
  const mustFitSels = ${JSON.stringify(mustFit)}
  const box = (el) => {
    const r = el.getBoundingClientRect()
    return {
      w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10,
      right: Math.round(r.right * 10) / 10,
    }
  }
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
      if (r.width === 0 || r.height === 0) return false
      return r.right > window.innerWidth + 0.5
    })
    .filter((el) => !reachableByScrolling(el))
    .slice(0, 6)
    .map(name)
  return {
    innerWidth: window.innerWidth,
    docScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    overflow,
    mustFit: Object.fromEntries(mustFitSels.map((s) => {
      const els = [...document.querySelectorAll(s)]
      const worst = els.map((el) => el.getBoundingClientRect().right).sort((a, b) => b - a)[0]
      return [s, els.length ? { count: els.length, worstRight: Math.round(worst * 10) / 10 } : null]
    })),
    gridTracks: ${JSON.stringify(gridTracks ?? '')}
      ? (() => {
        const el = document.querySelector(${JSON.stringify(gridTracks ?? '')})
        if (!el) return null
        const raw = getComputedStyle(el).gridTemplateColumns
        const tracks = raw.split(' ').map((v) => Math.round(parseFloat(v) * 10) / 10).filter((v) => !Number.isNaN(v))
        return { raw, tracks, widest: tracks.length ? Math.max(...tracks) : null }
      })()
      : null,
    critical: Object.fromEntries(criticalSels.map((s) => {
      const el = document.querySelector(s)
      return [s, el ? box(el) : null]
    })),
    longText: Object.fromEntries(longTextSels.map((s) => {
      const el = document.querySelector(s)
      if (!el) return [s, null]
      return [s, { clientWidth: el.clientWidth, scrollWidth: el.scrollWidth, text: (el.textContent || '').slice(0, 24) }]
    })),
    bodyLength: (document.body.innerText || '').length,
  }
})()`

const PAGES = [
  {
    name: 'Public Live',
    url: `${base}/public/t/${PLAY_TID}/live`,
    ready: '.bigscreen',
    critical: ['.pub-header', '.pub-nav'],
    // 实况卡片必须真的装进手机屏幕：这是 Day6D 小屏 gate 的核心断言
    mustFit: ['.bigscreen-tables', '.bigscreen-table', '.bigscreen-pair > div'],
    // 直接量网格轨道宽度：这就是 Day6D P1 的根因读数
    // （`grid-template-columns: 1fr` = minmax(auto, 1fr) → 轨道被超长姓名撑到 835px）
    gridTracks: '.bigscreen-tables',
    longText: [],
    notes: ['.bigscreen-header h1'],
  },
  {
    name: 'Public Rankings',
    url: `${base}/public/t/${PLAY_TID}/rankings`,
    ready: '.pub-nav',
    critical: ['.pub-header', '.pub-nav'],
    mustFit: ['.pub-main'],
    longText: [],
  },
  {
    name: 'Public Bracket',
    url: `${base}/public/t/${PLAY_TID}/bracket`,
    ready: '.pub-nav',
    critical: ['.pub-header', '.pub-nav'],
    mustFit: ['.pub-main'],
    longText: [],
  },
  {
    name: 'Public Register（表单态）',
    url: `${base}/public/t/${OPEN_TID}/register`,
    ready: '.reg-form',
    critical: ['.pub-header', '.pub-nav', '.reg-submit'],
    mustFit: ['.reg-form', '.reg-submit'],
    longText: [],
  },
]
if (MATCH_ID) {
  PAGES.push({
    name: 'Mobile Score',
    url: `${base}/admin/t/${PLAY_TID}/matches/${MATCH_ID}/score`,
    ready: '.ms-submit',
    critical: ['.ms-submit', '.ms-score-input', '.ms-step'],
    mustFit: ['.ms-submit', '.ms-side-name'],
    longText: ['.ms-header-title strong', '.ms-side-name'],
    login: true,
  })
}

const browser = await connect()

for (const pageDef of PAGES) {
  lines.push('')
  lines.push(`### ${pageDef.name}`)
  console.log('')
  console.log(`### ${pageDef.name}`)

  for (const viewport of VIEWPORTS) {
    const page = await openPage(browser, viewport, { login: pageDef.login })
    await page.navigate(pageDef.url)
    const ready = await waitFor(page, pageDef.ready)
    await sleep(900)

    if (!ready) {
      check(`${pageDef.name} ${viewport.width}px 页面就绪`, false, `未渲染 ${pageDef.ready}`)
      await page.close()
      continue
    }

    const measureTargets = [...pageDef.longText, ...(pageDef.notes ?? [])]
    const m = await page.evaluate(
      MEASURE(pageDef.critical, measureTargets, pageDef.mustFit ?? [], pageDef.gridTracks ?? ''),
    )

    if (pageDef.gridTracks) {
      const tracks = m.gridTracks
      check(
        `${pageDef.name} ${viewport.width}px ${pageDef.gridTracks} 网格轨道未被内容撑破`,
        Boolean(tracks) && tracks.widest !== null && tracks.widest <= viewport.width + 0.5,
        tracks ? `raw="${tracks.raw}" widest=${tracks.widest}` : 'NOT_FOUND',
      )
    }

    check(
      `${pageDef.name} ${viewport.width}px 无横向溢出`,
      m.docScrollWidth <= viewport.width && m.bodyScrollWidth <= viewport.width,
      `doc=${m.docScrollWidth} body=${m.bodyScrollWidth} viewport=${viewport.width}`,
    )
    check(
      `${pageDef.name} ${viewport.width}px 没有元素被静默挤出右边界`,
      m.overflow.length === 0,
      m.overflow.length ? JSON.stringify(m.overflow) : 'none',
    )
    for (const [selector, r] of Object.entries(m.mustFit)) {
      check(
        `${pageDef.name} ${viewport.width}px ${selector} 完整落在视口内（${r?.count ?? 0} 个）`,
        Boolean(r) && r.count > 0 && r.worstRight <= viewport.width + 0.5,
        JSON.stringify(r),
      )
    }

    for (const selector of pageDef.critical) {
      const r = m.critical[selector]
      check(
        `${pageDef.name} ${viewport.width}px 关键元素 ${selector} 可见且未出界`,
        Boolean(r) && r.w > 0 && r.h > 0 && r.right <= viewport.width + 0.5,
        JSON.stringify(r),
      )
    }

    const isScorePage = pageDef.name === 'Mobile Score'
    for (const selector of pageDef.longText) {
      const r = m.longText[selector]
      check(
        `${pageDef.name} ${viewport.width}px 长文本容器 ${selector} 未被文字撑破`,
        Boolean(r) && r.scrollWidth <= r.clientWidth + 1,
        r ? `client=${r.clientWidth} scroll=${r.scrollWidth} text="${r.text}"` : 'NOT_FOUND',
      )
    }
    for (const selector of pageDef.notes ?? []) {
      const r = m.longText[selector]
      note(
        `${pageDef.name} ${viewport.width}px ${selector} 超长无断点文本的当前表现（P2，本轮不改）`,
        r ? `client=${r.clientWidth} scroll=${r.scrollWidth} text="${r.text}"` : 'NOT_FOUND',
      )
    }

    if (isScorePage) {
      const sizes = (await page.evaluate(`Object.fromEntries(${JSON.stringify(['.ms-score-input', '.ms-step', '.ms-submit'])}.map((s) => {
        const el = document.querySelector(s)
        const r = el ? el.getBoundingClientRect() : null
        return [s, r ? Math.round(r.height * 10) / 10 : null]
      }))`)) ?? {}
      for (const [selector, height] of Object.entries(sizes)) {
        check(
          `Mobile Score ${viewport.width}px ${selector} 触摸高度 >= 44px`,
          typeof height === 'number' && height >= 44,
          `height=${height}`,
        )
      }
    }

    check(`${pageDef.name} ${viewport.width}px 页面非白屏`, m.bodyLength > 10, `bodyText=${m.bodyLength}`)

    await page.close()
  }
}

lines.push('')
const passCount = lines.filter((l) => l.startsWith('[PASS]')).length
const totalCount = lines.filter((l) => l.startsWith('[PASS]') || l.startsWith('[FAIL]')).length
lines.push(`=== D6D public viewport check: ${passCount}/${totalCount} PASS ===`)
if (failures.length) lines.push(`FAILURES: ${failures.join(' | ')}`)
console.log('')
console.log(`=== D6D public viewport check: ${passCount}/${totalCount} PASS ===`)
if (failures.length) console.log(`FAILURES: ${failures.join(' | ')}`)

process.exit(failures.length ? 1 : 0)
