/**
 * D 轨 Day 3 小屏适配验收：用真实 Chrome（CDP）+ 真实后端测量手机断点下的布局事实。
 *
 * ## 配套脚本（Day 3 验收四件套）
 *
 * | 脚本 | 作用 | 依赖 |
 * | --- | --- | --- |
 * | `day3_mobile_score_acceptance.ps1` | 后端契约层：4 类载荷 + 非法载荷 + 幂等 | 纯 HTTP |
 * | `day3_longname_fixture.py` | 造“超长中文名 + 超长 ASCII 名”赛事 | API |
 * | `day3_e2e_fixture.py` | 造干净的 A/C/D 三场景赛事 | API |
 * | `day3_mobile_e2e.mjs` | 真机视口端到端：输入 → 提交 → 服务端核对 | Chrome CDP |
 * | `scripts_mobile_viewport_check.mjs`（本文件） | 360/375/390/430 布局事实测量 | Chrome CDP |
 *
 * ## 为什么不用截图人工看
 *
 * 截图无法给出「是否出现横向滚动」「触摸目标真实高度」「名字有没有撑破容器」
 * 这类可判定事实。这里直接量 DOM，并把这些事实变成 PASS/FAIL。
 *
 * ## 用法
 *
 * ```powershell
 * # 1. 后端（frontend/dist 必须是构建产物，见 PR #44 单服务托管）
 * cd backend
 * $env:DEMO_DB_PATH='data\d3_acceptance.db'
 * .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8099
 *
 * # 2. 造一个超长名字的赛事，拿到录分页路径
 * .\.venv\Scripts\python.exe .\day3_longname_fixture.py
 *
 * # 3. 起一个开了 CDP 的 Chrome
 * & "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
 *     --remote-debugging-port=9333 --user-data-dir=<临时目录> about:blank
 *
 * # 4. 测量（第二个参数为录分页路径）
 * node .\scripts_mobile_viewport_check.mjs http://127.0.0.1:8099 /admin/t/5/matches/13/score
 * ```
 *
 * 测量项（每个断点都独立设置 viewport，模拟真机视口）：
 *   1. documentElement.scrollWidth <= innerWidth  -> 不横向滚动
 *   2. .ms-score-input / .ms-submit / .ms-step 实际高度 >= 44px -> 手机可点
 *   3. 每个关键元素 right <= innerWidth + 0.5 -> 没有被挤出屏幕
 *   4. .ms-side-name 的 scrollWidth <= clientWidth -> 长名字不破版
 *   5. 点击「+ 录入逐局小比分（可选）」后再次测量 -> 扩展区域也不溢出
 *   6. 点击提交后 .ms-error 可见 -> 错误文字不会被布局吞掉
 */

const CDP_PORT = process.env.CDP_PORT ?? '9333'
const baseUrl = process.argv[2] ?? 'http://127.0.0.1:8099'
const pagePath = process.argv[3] ?? '/admin/t/1/matches/3/score'
const viewports = [360, 375, 390, 430]

const failures = []
const lines = []

function check(name, ok, detail) {
  lines.push(`[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`)
  if (!ok) failures.push(name)
}

async function httpJson(path) {
  const resp = await fetch(`http://127.0.0.1:${CDP_PORT}${path}`)
  return resp.json()
}

/** 最小 CDP 客户端：够用即可（Page.navigate / Runtime.evaluate / Input / Emulation） */
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

  async eval(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    if (result.exceptionDetails) {
      throw new Error(`eval failed: ${result.exceptionDetails.text}`)
    }
    return result.result.value
  }
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    ws.addEventListener('open', () => resolve(new Cdp(ws)))
    ws.addEventListener('error', (err) => reject(err))
  })
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** 页面侧测量脚本（在浏览器里执行，返回可序列化事实）。 */
const MEASURE = `(() => {
  const rect = (selector) => {
    const el = document.querySelector(selector)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return {
      top: Math.round(r.top * 10) / 10,
      right: Math.round(r.right * 10) / 10,
      bottom: Math.round(r.bottom * 10) / 10,
      left: Math.round(r.left * 10) / 10,
      width: Math.round(r.width * 10) / 10,
      height: Math.round(r.height * 10) / 10,
      clientWidth: el.clientWidth,
      scrollWidth: el.scrollWidth,
    }
  }
  const names = [...document.querySelectorAll('.ms-side-name, .ms-score-who')].map((el) => ({
    text: el.textContent,
    clientWidth: el.clientWidth,
    scrollWidth: el.scrollWidth,
    height: Math.round(el.getBoundingClientRect().height),
  }))
  const all = [...document.querySelectorAll('.ms-shell *')]
  const overflowRight = all
    .map((el) => ({ cls: el.className && el.className.toString().slice(0, 40), right: Math.round(el.getBoundingClientRect().right) }))
    .filter((item) => item.right > window.innerWidth + 1)
  return {
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    scoreInput: rect('.ms-score-input'),
    step: rect('.ms-step'),
    submit: rect('.ms-submit'),
    submitBar: rect('.ms-submit-bar'),
    versus: rect('.ms-versus'),
    sideName: rect('.ms-side-name'),
    gameToggle: rect('.ms-games-toggle'),
    gameInput: rect('.ms-game-inputs input'),
    gameRemove: rect('.ms-game-remove'),
    errorBox: rect('.ms-error'),
    errorText: document.querySelector('.ms-error') ? document.querySelector('.ms-error').textContent : null,
    visibleText: document.body.innerText.slice(0, 400),
    names,
    overflowRight: overflowRight.slice(0, 5),
  }
})()`

async function main() {
  const version = await httpJson('/json/version')
  lines.push(`# chrome: ${version.Browser}`)

  const cdp = await connect(version.webSocketDebuggerUrl)

  // 复用同一个标签页：每次用 Emulation 覆盖视口，避免反复开新 tab
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true })
  const session = {
    send: (method, params) =>
      new Promise((resolve, reject) => {
        const id = ++session.seq
        session.pending.set(id, { resolve, reject })
        cdp.ws.send(JSON.stringify({ id, method, params, sessionId }))
      }),
    seq: 0,
    pending: new Map(),
  }
  cdp.ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && session.pending.has(msg.id)) {
      const { resolve, reject } = session.pending.get(msg.id)
      session.pending.delete(msg.id)
      if (msg.error) reject(new Error(JSON.stringify(msg.error)))
      else resolve(msg.result)
    }
  })
  const send = (method, params = {}) => session.send(method, params)
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
    return result.result.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  // 关闭 HTTP 缓存：否则重新 build 之后仍会加载上一次的 hash 资源，
  // 让“修复后仍失败”的假象进入验收结论（实测踩过一次）。
  await send('Network.enable')
  await send('Network.setCacheDisabled', { cacheDisabled: true })

  for (const width of viewports) {
    const height = width === 360 ? 740 : width === 375 ? 812 : width === 390 ? 844 : 932
    await send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: true,
    })
    await send('Page.navigate', { url: `${baseUrl}${pagePath}` })

    // 等真实页面就绪（React 挂载 + 网络请求完成）
    let ready = false
    for (let i = 0; i < 60; i += 1) {
      await sleep(150)
      const ok = await evaluate(
        `!!document.querySelector('.ms-submit') && !document.querySelector('.ms-loading')`,
      ).catch(() => false)
      if (ok) {
        ready = true
        break
      }
    }
    check(`${width}px 页面就绪`, ready, ready ? 'MobileScorePage 已渲染' : '超时未渲染')

    const m = await evaluate(MEASURE)
    lines.push(`# ${width}px viewport: inner=${m.innerWidth}x${m.innerHeight} scrollWidth=${m.scrollWidth}`)

    check(
      `${width}px 无横向滚动`,
      m.scrollWidth <= width && m.bodyScrollWidth <= width,
      `documentElement.scrollWidth=${m.scrollWidth} body.scrollWidth=${m.bodyScrollWidth} (viewport=${width})`,
    )
    check(
      `${width}px 没有元素被挤出右边界`,
      m.overflowRight.length === 0,
      m.overflowRight.length === 0 ? 'none' : JSON.stringify(m.overflowRight),
    )
    check(`${width}px 大比分输入框可点`, m.scoreInput && m.scoreInput.height >= 44, `height=${m.scoreInput?.height}`)
    check(`${width}px 步进按钮可点`, m.step && m.step.height >= 44, `height=${m.step?.height}`)
    check(`${width}px 提交按钮可点`, m.submit && m.submit.height >= 44, `height=${m.submit?.height}`)
    check(
      `${width}px 提交按钮未被布局吞掉（在视口内或页面可滚动到）`,
      m.submit && m.submit.width > 100 && m.submit.height > 0,
      `width=${m.submit?.width} height=${m.submit?.height}`,
    )
    check(
      `${width}px 双方名字不破版`,
      m.names.every((n) => n.scrollWidth <= n.clientWidth + 1),
      JSON.stringify(m.names),
    )

    // 展开逐局小比分后再测一次（Day 3 要求小屏展开后仍可用）
    const toggle = await evaluate(
      `(() => { const b = document.querySelector('.ms-games-toggle'); if (!b) return false; b.click(); return true })()`,
    )
    check(`${width}px 可展开逐局小比分入口`, toggle === true, `clicked=${toggle}`)
    await sleep(200)

    const m2 = await evaluate(MEASURE)
    check(
      `${width}px 展开小比分后仍无横向滚动`,
      m2.scrollWidth <= width,
      `scrollWidth=${m2.scrollWidth}`,
    )
    check(`${width}px 小比分输入框可点`, m2.gameInput && m2.gameInput.height >= 44, `height=${m2.gameInput?.height}`)
    check(`${width}px 删除局按钮可点`, m2.gameRemove && m2.gameRemove.height >= 36, `height=${m2.gameRemove?.height}`)
    check(
      `${width}px 展开后没有元素被挤出右边界`,
      m2.overflowRight.length === 0,
      m2.overflowRight.length === 0 ? 'none' : JSON.stringify(m2.overflowRight),
    )

    // 点上「+」一次（只加到 1，不填另一方），再提交：
    // review 返工后步进按钮**不再**用 gamesToWin 当上限，也**不再**自动改写另一方，
    // 因此这里应提示“还有一方的大比分没有填写”，而不是自动补出 2:1。
    await evaluate(`(() => {
      const plus = [...document.querySelectorAll('.ms-step')].find((b) => b.getAttribute('aria-label')?.includes('加一局'))
      plus?.click()
      document.querySelector('.ms-submit')?.click()
      return true
    })()`)
    await sleep(300)
    const m3 = await evaluate(MEASURE)
    check(
      `${width}px 错误文字可见（未被布局吞掉）`,
      m3.errorBox !== null && m3.errorBox.height > 0 && m3.errorBox.top < m3.innerHeight + 600,
      m3.errorText ? `text="${m3.errorText.slice(0, 40)}" height=${m3.errorBox?.height}` : '未出现错误框',
    )
    check(
      `${width}px 步进不动另一方（无 gamesToWin 自动补全）`,
      typeof m3.visibleText === 'string' && m3.visibleText.includes('还有一方的大比分没有填写'),
      `errorText=${m3.errorText}`,
    )
  }

  lines.push('')
  lines.push(`=== summary: FAIL=${failures.length} ===`)
  if (failures.length > 0) lines.push(`failed checks: ${failures.join(' | ')}`)
  console.log(lines.join('\n'))
  await send('Target.closeTarget', { targetId }).catch(() => {})
  process.exit(failures.length > 0 ? 1 : 0)
}

main().catch((err) => {
  console.error('viewport check crashed:', err)
  process.exit(2)
})
