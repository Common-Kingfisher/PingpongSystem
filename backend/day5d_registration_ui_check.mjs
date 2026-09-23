/**
 * D 轨 Day5D 验收：Public 报名页的真实浏览器检查（真实 Chrome CDP + 真实后端）。
 *
 * ## 为什么需要它（自动化测试之外）
 *
 * 前端 vitest 已经证明「点了提交发的是什么请求」，但证明不了布局事实：
 * 360 / 375 / 390 / 430px 下是否出现横向滚动、触摸目标是否 >= 44px、
 * 超长赛事名是否撑破容器、二维码旁展示的**真实地址字符串**是什么。
 * 这些只能在没有 JS 假设的真浏览器里量出来。
 *
 * ## 检查项
 *
 * 1. 4 个手机断点：无横向滚动、关键元素不被挤出右边界；
 * 2. `#reg-name` / `#reg-affiliation` / `#reg-contact` / `.reg-submit` / `.reg-qr-copy`
 *    实际高度 >= 44px（手机可点）；
 * 3. 报名地址 = `<当前访问 origin>/public/t/<tid>/register`，且二维码编码同一字符串；
 * 4. 用报名地址重新打开 → 落到同一个 Public 报名页（“扫码能打开”）；
 * 5. 超长赛事名（中文 + ASCII 各超长）不撑破页面；
 * 6. 管理员关闭报名后刷新 → 只读关闭态（没有可提交表单）。
 *
 * ## 用法
 *
 * ```powershell
 * # 1. 后端（frontend/dist 必须是当前构建产物）+ 独立验收库
 * cd backend
 * $env:PINGPONG_DB_PATH='data\d5d_acceptance.db'
 * .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8099
 *
 * # 2. 先跑契约层 smoke（会建好 d5d-admin 与赛事）
 * .\.venv\Scripts\python.exe day5d_registration_smoke.py http://127.0.0.1:8099
 *
 * # 3. 起一个开了 CDP 的 Chrome
 * & "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
 *     --remote-debugging-port=9333 --user-data-dir=<临时目录> about:blank
 *
 * # 4. 测量
 * node .\day5d_registration_ui_check.mjs http://127.0.0.1:8099 1
 * ```
 */

const CDP_PORT = process.env.CDP_PORT ?? '9333'
const baseUrl = (process.argv[2] ?? 'http://127.0.0.1:8099').replace(/\/$/, '')
const tid = Number(process.argv[3] ?? '1')
const loginUsername = process.argv[4] ?? 'd5d-admin'
const loginPassword = process.argv[5] ?? 'd5d-admin-pass1'
const viewports = [360, 375, 390, 430]

const failures = []
const lines = []
/** 只统计被 check() 判定的检查项（lines 里还含 `#` 说明行） */
let checks = 0

function check(name, ok, detail) {
  checks += 1
  const line = `[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`
  lines.push(line)
  // 逐条即时输出：脚本被中断时也能看到已完成到哪一步
  console.log(line)
  if (!ok) failures.push(name)
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function httpJson(path) {
  const resp = await fetch(`http://127.0.0.1:${CDP_PORT}${path}`)
  return resp.json()
}

// ------------------------------------------------------------------ 后端准备

async function loginBearer() {
  const r = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: loginUsername, password: loginPassword, mode: 'bearer' }),
  })
  if (!r.ok) throw new Error(`登录失败 HTTP ${r.status}`)
  return (await r.json()).access_token
}

async function setRegistrationEnabled(token, tournamentId, enabled) {
  const r = await fetch(`${baseUrl}/api/tournaments/${tournamentId}/registration`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ enabled }),
  })
  return r.status
}

async function createTournament(token, name) {
  const r = await fetch(`${baseUrl}/api/tournaments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      name,
      date: '2026-01-01',
      table_count: 4,
      group_count: 2,
      qualify_per_group: 2,
      event_type: 'SINGLES',
      operation_mode: 'LIVE',
      games_to_win: 2,
      points_to_win: 11,
    }),
  })
  if (!r.ok) throw new Error(`创建赛事失败 HTTP ${r.status}`)
  return (await r.json()).id
}

// ---------------------------------------------------------------- CDP client

class Cdp {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.pending = new Map()
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(JSON.stringify(msg.error)))
        else resolve(msg.result)
      }
    })
  }

  send(method, params = {}) {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    ws.addEventListener('open', () => resolve(new Cdp(ws)))
    ws.addEventListener('error', (err) => reject(err))
  })
}

/** 页面侧测量脚本（返回可序列化事实，不做任何断言） */
const MEASURE = `(() => {
  const rect = (selector) => {
    const el = document.querySelector(selector)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return {
      top: Math.round(r.top * 10) / 10,
      right: Math.round(r.right * 10) / 10,
      left: Math.round(r.left * 10) / 10,
      width: Math.round(r.width * 10) / 10,
      height: Math.round(r.height * 10) / 10,
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }
  }
  const scope = document.querySelector('.reg-card') || document.body
  const overflowRight = [...scope.querySelectorAll('*')]
    .map((el) => ({ cls: (el.className || '').toString().slice(0, 40), right: Math.round(el.getBoundingClientRect().right) }))
    .filter((item) => item.right > window.innerWidth + 1)
  return {
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    docScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    name: rect('#reg-name'),
    affiliation: rect('#reg-affiliation'),
    contact: rect('#reg-contact'),
    rating: rect('#reg-rating'),
    submit: rect('.reg-submit'),
    copyBtn: rect('.reg-qr-copy'),
    qrFrame: rect('.reg-qr-frame'),
    qrUrl: document.querySelector('.reg-qr-url')?.textContent ?? null,
    qrSvgTitle: document.querySelector('.reg-qr-frame svg title')?.textContent ?? null,
    heading: rect('.reg-heading h2'),
    headingScrollWidth: document.querySelector('.reg-heading h2')?.scrollWidth ?? null,
    headingClientWidth: document.querySelector('.reg-heading h2')?.clientWidth ?? null,
    closedText: document.querySelector('.reg-closed h3')?.textContent ?? null,
    hasForm: !!document.querySelector('.reg-form'),
    overflowRight: overflowRight.slice(0, 6),
  }
})()`

async function main() {
  console.log(`# 后端 ${baseUrl}，赛事 tid=${tid}`)
  const token = await loginBearer()
  console.log('# 已登录（bearer）')

  // 主赛事：开启报名
  check('后端开启报名（PUT /registration）', (await setRegistrationEnabled(token, tid, true)) === 200, `tid=${tid}`)

  // 后端 TournamentCreate.name 上限 100 字符：这里构造一个「合法但极长」的名字（96 字符），
  // 用来验证超长赛事名不会把 Public 报名页撑破。
  const longName = `D5D ${'超长赛事名称'.repeat(10)}${'LONGNAME'.repeat(4)}`
  const longTid = await createTournament(token, longName)
  await setRegistrationEnabled(token, longTid, true)

  const version = await httpJson('/json/version')
  lines.push(`# chrome: ${version.Browser}`)
  const cdp = await connect(version.webSocketDebuggerUrl)
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true })

  const session = { seq: 0, pending: new Map() }
  cdp.ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && session.pending.has(msg.id)) {
      const { resolve, reject } = session.pending.get(msg.id)
      session.pending.delete(msg.id)
      if (msg.error) reject(new Error(JSON.stringify(msg.error)))
      else resolve(msg.result)
    }
  })
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++session.seq
      session.pending.set(id, { resolve, reject })
      cdp.ws.send(JSON.stringify({ id, method, params, sessionId }))
    })
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
    return result.result.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Network.enable')
  await send('Network.setCacheDisabled', { cacheDisabled: true })

  const goto = async (path, readyExpression, label) => {
    await send('Page.navigate', { url: `${baseUrl}${path}` })
    for (let i = 0; i < 60; i += 1) {
      await sleep(150)
      const ready = await evaluate(readyExpression).catch(() => false)
      if (ready) return true
    }
    check(`${label} 页面就绪`, false, '超时未渲染')
    return false
  }

  // ------------------------------------------------------- 主赛事 × 4 断点
  let observedUrl = null
  for (const width of viewports) {
    const height = width === 360 ? 740 : width === 375 ? 812 : width === 390 ? 844 : 932
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: true })

    const ready = await goto(`/public/t/${tid}/register`, `!!document.querySelector('.reg-submit')`, `${width}px`)
    if (!ready) continue

    const m = await evaluate(MEASURE)
    lines.push(`# ${width}px: inner=${m.innerWidth}x${m.innerHeight} scrollWidth=${m.docScrollWidth}`)
    observedUrl = m.qrUrl

    check(`${width}px 无横向滚动`, m.docScrollWidth <= width && m.bodyScrollWidth <= width, `doc=${m.docScrollWidth} body=${m.bodyScrollWidth} viewport=${width}`)
    check(`${width}px 报名卡片内没有元素被挤出右边界`, m.overflowRight.length === 0, m.overflowRight.length === 0 ? 'none' : JSON.stringify(m.overflowRight))
    check(`${width}px 姓名输入框 >= 44px 可点`, !!m.name && m.name.height >= 44, `height=${m.name?.height}`)
    check(`${width}px 所属单位输入框 >= 44px 可点`, !!m.affiliation && m.affiliation.height >= 44, `height=${m.affiliation?.height}`)
    check(`${width}px 联系方式输入框 >= 44px 可点`, !!m.contact && m.contact.height >= 44, `height=${m.contact?.height}`)
    check(`${width}px 提交按钮 >= 44px 可点`, !!m.submit && m.submit.height >= 44, `height=${m.submit?.height}`)
    check(`${width}px 复制链接按钮 >= 44px 可点`, !!m.copyBtn && m.copyBtn.height >= 44, `height=${m.copyBtn?.height}`)
    check(`${width}px 二维码已渲染`, !!m.qrFrame && m.qrFrame.width > 0 && m.qrFrame.width <= width, `width=${m.qrFrame?.width}`)
    check(
      `${width}px 报名地址 = 当前 origin + /public/t/${tid}/register`,
      m.qrUrl === `${baseUrl}/public/t/${tid}/register`,
      `qrUrl=${m.qrUrl}`,
    )
    check(`${width}px 二维码编码同一地址`, (m.qrSvgTitle ?? '').includes(`${baseUrl}/public/t/${tid}/register`), `title=${m.qrSvgTitle}`)
    check(`${width}px 超长赛事名不撑破标题`, m.headingScrollWidth !== null && m.headingScrollWidth <= width, `heading.scrollWidth=${m.headingScrollWidth}`)
  }

  // ------------------------------------------------- 超长赛事名 × 4 断点
  for (const width of viewports) {
    const height = width === 360 ? 740 : width === 375 ? 812 : width === 390 ? 844 : 932
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: true })
    const ready = await goto(`/public/t/${longTid}/register`, `!!document.querySelector('.reg-submit')`, `超长名 ${width}px`)
    if (!ready) continue
    const m = await evaluate(MEASURE)
    check(`${width}px 超长名赛事无横向滚动`, m.docScrollWidth <= width && m.bodyScrollWidth <= width, `doc=${m.docScrollWidth} viewport=${width}`)
    check(`${width}px 超长名赛事无元素溢出右边界`, m.overflowRight.length === 0, m.overflowRight.length === 0 ? 'none' : JSON.stringify(m.overflowRight))
  }

  // ------------------------------------------------- D 用报名地址打开同一页
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  if (observedUrl) {
    await send('Page.navigate', { url: observedUrl })
    let same = false
    for (let i = 0; i < 60; i += 1) {
      await sleep(150)
      same = await evaluate(`!!document.querySelector('.reg-submit') && location.pathname === '/public/t/${tid}/register'`).catch(() => false)
      if (same) break
    }
    check('D 用二维码/文本地址打开 → 落到同一个 Public 报名页（可提交）', same, `url=${observedUrl}`)
  } else {
    check('D 用二维码/文本地址打开 → 落到同一个 Public 报名页（可提交）', false, '未取到报名地址')
  }

  // ------------------------------------------------- C 关闭报名后的只读态
  await setRegistrationEnabled(token, tid, false)
  const closed = await goto(`/public/t/${tid}/register`, `!!document.querySelector('.reg-closed')`, '报名关闭态')
  const closedState = closed ? await evaluate(MEASURE) : null
  check(
    'C 关闭报名后刷新 → 显示「当前赛事暂未开放报名」且没有可提交表单',
    !!closedState && closedState.closedText === '当前赛事暂未开放报名' && closedState.hasForm === false && closedState.submit === null,
    `closedText=${closedState?.closedText} hasForm=${closedState?.hasForm}`,
  )
  check('C 关闭态不展示二维码入口', closedState !== null && closedState.qrFrame === null, `qrFrame=${JSON.stringify(closedState?.qrFrame ?? null)}`)

  console.log(`\n=== D5D UI check: ${checks - failures.length}/${checks} PASS ===`)
  if (failures.length > 0) {
    console.log('FAILED:')
    for (const name of failures) console.log(`  - ${name}`)
    process.exitCode = 1
  }
}

main().catch((err) => {
  console.error(err)
  process.exitCode = 1
})
