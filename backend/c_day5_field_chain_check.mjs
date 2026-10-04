/**
 * C 轨 Day5 Phase 4：16 人 / 6 台现场主链（Console 视角的端到端验收）。
 *
 * ## 与 D6D 的分工
 *
 * D6D 已经覆盖「手机端提交比分本身」（正常 / 异常 / 断网 / 并发）。
 * 本脚本验收的是**管理端 Console 在现场能不能顺序走完一整场赛事**：
 *
 * ```text
 * 自动排台 → 录分 → Console 自动刷新（不手动刷新页面）
 *   → 小组赛全部结束 → 阶段收口（不再显示无效排台）
 *   → 生成淘汰签 → Console 恢复排台能力 → Schedule 显示淘汰轮次
 * ```
 *
 * 关键断言都指向 C-D5 收口的两个真实缺陷：
 * 1. Console 不再"统计比赛条数自己判断小组赛是否结束"，而是消费后端 `completion`；
 * 2. 过渡窗口（小组赛完成、淘汰签未生成）必须**没有**排台入口，
 *    而进入淘汰赛后必须**恢复**排台能力（旧代码在这里会永久锁死或错误放开）。
 *
 * 用法：
 * ```powershell
 * node .\c_day5_field_chain_check.mjs <base> <tid> <user> <pass> [mode]
 *
 * # mode = blocked：只录大比分 → 后端报告 QUALIFICATION_UNRESOLVED，
 * #                 验收 Console 不诱导生成淘汰签（需要干净 fixture）
 * # mode = ranked ：带逐局小分并按组内顺序胜负 → 走完 排台→录分→阶段收口→淘汰赛
 * ```
 */

import { sleep } from './day3_cdp_auth.mjs'

const CDP_PORT = process.env.CDP_PORT ?? '9333'
const base = (process.argv[2] ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
const TID = Number(process.argv[3] ?? '1')
const USER = process.argv[4] ?? 'c5d-admin'
const PASS = process.argv[5] ?? 'c5d-admin-pass1'
const MODE = process.argv[6] === 'blocked' ? 'raw' : 'ranked'

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
  const handlers = []
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return }
    if (msg.method) for (const fn of handlers) fn(msg)
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
    on: (fn) => handlers.push(fn),
    close: () => ws.close(),
  }
}

async function openConsole(browser) {
  const browserContextId = (await browser.send('Target.createBrowserContext', {})).result.browserContextId
  const targetId = (await browser.send('Target.createTarget', { url: 'about:blank', browserContextId })).result.targetId
  const sessionId = (await browser.send('Target.attachToTarget', { targetId, flatten: true })).result.sessionId
  const send = (method, params = {}) => browser.send(method, params, sessionId)
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Network.enable')
  await send('Network.setCacheDisabled', { cacheDisabled: true })
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false })

  const evaluate = async (expression) => {
    const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (out.result?.exceptionDetails) {
      throw new Error(out.result.exceptionDetails.exception?.description ?? 'evaluate failed')
    }
    return out.result?.result?.value
  }

  await send('Page.navigate', { url: `${base}/?tid=${TID}` })
  await sleep(800)
  const status = await evaluate(`(async () => {
    const resp = await fetch('/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify({ username: ${JSON.stringify(USER)}, password: ${JSON.stringify(PASS)}, mode: 'browser' })
    })
    return resp.status
  })()`)
  if (status !== 200) throw new Error(`登录失败: HTTP ${status}`)

  return {
    evaluate,
    goto: async (path) => { await send('Page.navigate', { url: `${base}${path}` }); await sleep(700) },
    close: () => browser.send('Target.closeTarget', { targetId }),
  }
}

const CONSOLE_STATE = `(() => {
  const text = document.body.innerText || ''
  const progress = text.match(/比赛进度\\s*(\\d+)\\s*\\/\\s*(\\d+)/)
  const buttons = [...document.querySelectorAll('button')].map((b) => b.textContent.trim())
  const assignButtons = [...document.querySelectorAll('.live-table-card .live-assign')].map((b) => b.textContent.trim())
  return {
    finished: progress ? Number(progress[1]) : null,
    total: progress ? Number(progress[2]) : null,
    playingTables: document.querySelectorAll('.live-table-card.is-playing').length,
    freeTables: document.querySelectorAll('.live-table-card.is-free').length,
    hasBatch: buttons.some((t) => t.includes('自动安排下一批比赛')),
    notice: (document.querySelector('.console-notice')?.innerText ?? '').replace(/\\s+/g, ' ').trim(),
    noticeTitle: (document.querySelector('.console-notice strong')?.textContent ?? '').trim(),
    noticeAction: (document.querySelector('.console-notice a')?.textContent ?? '').trim(),
    assignButtons,
    knockoutLink: !!([...document.querySelectorAll('a')].some((a) => a.textContent.trim() === '进入淘汰赛')),
    syncText: (document.querySelector('.console-sync')?.innerText ?? '').replace(/\\s+/g, ' ').trim(),
  }
})()`

/**
 * 用页面自己的会话调用真实 API（相当于主裁在手机上录分，Console 端只负责自动刷新）。
 *
 * `mode=raw`    —— 只录大比分、不带逐局小分（现场常见的快速录法）。
 *                  4 人小组里容易出现真实并列，后端会诚实地报告
 *                  `QUALIFICATION_UNRESOLVED`；此时 Console **必须**拒绝诱导生成淘汰签。
 * `mode=ranked` —— 按组内 Entry 顺序决定胜负（低 id 恒胜 → 严格 3/2/1/0 胜场，无并列），
 *                  并带上逐局小分。这是"打满整场赛事"需要的完整现场数据。
 */
const SCORE_ALL_PLAYING = (gamesToWin, mode) => `(async () => {
  const get = async (path) => (await fetch(path, { credentials: 'same-origin' })).json()
  const dash = await get('/api/tournaments/${TID}/dashboard')
  const playing = dash.tables.filter((t) => t.match).map((t) => t.match)

  // 组内排名：同组 Entry 按 id 升序 → 低 id 恒胜，保证小组内胜场严格递减。
  const rank = {}
  if (${JSON.stringify(mode)} === 'ranked') {
    const entries = await get('/api/tournaments/${TID}/entries')
    const groups = await get('/api/tournaments/${TID}/groups')
    for (const g of groups.groups ?? []) {
      entries.filter((e) => e.group_id === g.id).sort((a, b) => a.id - b.id)
        .forEach((e, i) => { rank[e.id] = i })
    }
  }

  const games = (aWins) => Array.from({ length: ${gamesToWin} }, (_, i) => (
    aWins ? { side_a_score: 11, side_b_score: 5 + i } : { side_a_score: 5 + i, side_b_score: 11 }
  ))

  const results = []
  for (const m of playing) {
    const aKey = rank[m.entry_a_id] ?? m.entry_a_id ?? 0
    const bKey = rank[m.entry_b_id] ?? m.entry_b_id ?? 0
    const aWins = aKey < bKey
    const payload = aWins
      ? { player_a_score: ${gamesToWin}, player_b_score: 0 }
      : { player_a_score: 0, player_b_score: ${gamesToWin} }
    if (${JSON.stringify(mode)} === 'ranked') payload.games = games(aWins)
    const resp = await fetch('/api/matches/' + m.id + '/score', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify(payload),
    })
    results.push({ id: m.id, status: resp.status, body: resp.ok ? null : (await resp.text()).slice(0, 140) })
  }
  return results
})()`

const CLICK_BATCH = `(() => {
  const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('自动安排下一批比赛'))
  if (!btn) return false
  btn.click()
  return true
})()`

async function waitForConsole(page, predicateSource, tries = 60) {
  for (let i = 0; i < tries; i += 1) {
    await sleep(300)
    const state = await page.evaluate(CONSOLE_STATE)
    if (predicateSource(state)) return state
  }
  return await page.evaluate(CONSOLE_STATE)
}

async function main() {
  const browser = await connect()
  const page = await openConsole(browser)

  // ---------------------------------------------------------- 0. 取本赛事局制
  const gamesToWin = await page.evaluate(
    `(async () => (await (await fetch('/api/tournaments/${TID}', { credentials: 'same-origin' })).json()).games_to_win)()`,
  )
  note('games_to_win', String(gamesToWin))

  await page.goto(`/console?tid=${TID}`)
  let state = await waitForConsole(page, (s) => s.total !== null)
  check('C-D5 现场链：Console 载入真实赛事', state.total === 24,
    `进度 ${state.finished}/${state.total} 空闲台=${state.freeTables}`)
  check('C-D5 现场链：未排台时提供"自动安排下一批比赛"', state.hasBatch === true, `hasBatch=${state.hasBatch}`)

  // ---------------------------------------------------------- 1. 排台（浏览器真实点击）
  const clicked = await page.evaluate(CLICK_BATCH)
  check('C-D5 现场链：点击"自动安排下一批比赛"', clicked === true, `clicked=${clicked}`)
  state = await waitForConsole(page, (s) => s.playingTables > 0)
  check('C-D5 现场链：6 张球台全部进入进行中', state.playingTables === 6 && state.freeTables === 0,
    `进行中=${state.playingTables} 空闲=${state.freeTables}`)

  // ---------------------------------------------------------- 2. 录分 + Console 自动刷新
  const beforeFinished = state.finished
  const config = await page.evaluate(
    `(async () => (await (await fetch('/api/tournaments/${TID}/dashboard', { credentials: 'same-origin' })).json()).stats)()`,
  )
  note('排台后 stats', JSON.stringify(config))

  const scored = await page.evaluate(SCORE_ALL_PLAYING(gamesToWin, MODE))
  const badScores = scored.filter((r) => r.status !== 200)
  check('C-D5 现场链：录分全部落库', badScores.length === 0,
    badScores.length ? JSON.stringify(badScores.slice(0, 2)) : `${scored.length} 场 200`)

  // 不刷新页面：只等 Console 自己的 5 秒轮询
  const refreshed = await waitForConsole(page, (s) => s.finished > beforeFinished)
  check('C-D5 现场链：Console 无需手动刷新即反映录分结果',
    refreshed.finished > beforeFinished,
    `已完成 ${beforeFinished} → ${refreshed.finished}/${refreshed.total}，${refreshed.syncText}`)

  // ---------------------------------------------------------- 3. 推进到小组赛结束
  let guard = 0
  while (guard < 30) {
    guard += 1
    const s = await page.evaluate(CONSOLE_STATE)
    if (s.finished === s.total) break
    if (s.hasBatch) {
      await page.evaluate(CLICK_BATCH)
      await sleep(600)
    }
    const playing = await page.evaluate(
      `(async () => (await (await fetch('/api/tournaments/${TID}/dashboard', { credentials: 'same-origin' })).json()).stats.playing)()`,
    )
    if (playing > 0) {
      await page.evaluate(SCORE_ALL_PLAYING(gamesToWin, MODE))
    } else if (!s.hasBatch) {
      break
    }
    await sleep(400)
  }

  state = await waitForConsole(page, (s) => s.finished === s.total, 80)
  check('C-D5 现场链：24 场小组赛全部完成', state.finished === 24 && state.total === 24,
    `进度 ${state.finished}/${state.total}`)

  // ---------------------------------------------------------- 3b. 后端阻断时必须诚实
  const completionState = await page.evaluate(
    `(async () => (await (await fetch('/api/tournaments/${TID}/dashboard', { credentials: 'same-origin' })).json()).completion)()`,
  )
  note('后端 completion', JSON.stringify(completionState))

  if (MODE === 'raw') {
    // 「只录大比分」是现场常见的快速录法，会留下真实并列：
    // 后端可能报告 QUALIFICATION_UNRESOLVED，也可能并列恰好被胜负关系解开而报告 KNOCKOUT_READY。
    // 两种结果都合法，因此这里不赌某个具体 state，而是锁定**不变量**：
    //   界面上"能不能推进 / 能不能排台"必须与后端 completion 完全一致。
    const canAdvance = completionState.can_advance === true
    check('C-D5 不变量：可推进入口与后端 completion 完全一致',
      state.knockoutLink === canAdvance,
      `can_advance=${completionState.can_advance} UI进入淘汰赛=${state.knockoutLink} state=${completionState.state}`)
    check('C-D5 不变量：小组赛结束后不再提供"自动安排下一批比赛"', state.hasBatch === false,
      `hasBatch=${state.hasBatch}`)
    check('C-D5 不变量：阶段横幅与后端 state 一致',
      canAdvance
        ? state.noticeTitle.includes('小组赛已全部完成')
        : (state.noticeTitle.length > 0 && !state.noticeTitle.includes('小组赛已全部完成')),
      `state=${completionState.state} notice="${state.noticeTitle}"`)

    const rejected = await page.evaluate(`(async () => {
      const resp = await fetch('/api/tournaments/${TID}/generate-knockout', { method: 'POST', credentials: 'same-origin' })
      return { status: resp.status, body: (await resp.text()).slice(0, 140) }
    })()`)
    if (canAdvance) {
      check('C-D5 不变量：后端确实允许生成淘汰签（前端入口不是无效按钮）',
        rejected.status === 200, `HTTP ${rejected.status}`)
    } else {
      check('C-D5 不变量：后端确实拒绝生成淘汰签（前端没有给出无效按钮）',
        rejected.status === 409, `HTTP ${rejected.status} ${rejected.body}`)
      check('C-D5 不变量：阻断时引导到排名页而不是淘汰赛',
        state.noticeAction !== '进入淘汰赛', `noticeAction="${state.noticeAction}"`)
    }
    await page.close()
    browser.close()
    return report()
  }

  check('C-D5 现场链：小组赛完成后后端报告可推进',
    completionState.state === 'KNOCKOUT_READY' && completionState.can_advance === true,
    `state=${completionState.state} can_advance=${completionState.can_advance}`)

  // ---------------------------------------------------------- 4. 过渡窗口收口
  check('C-D5 现场链：过渡窗口不再显示"自动安排下一批比赛"', state.hasBatch === false,
    `hasBatch=${state.hasBatch}`)
  check('C-D5 现场链：过渡窗口显示阶段结束提示', state.noticeTitle.includes('小组赛已全部完成'),
    `notice="${state.noticeTitle}"`)
  check('C-D5 现场链：过渡窗口给出"进入淘汰赛"入口', state.knockoutLink === true,
    `noticeAction="${state.noticeAction}"`)
  check('C-D5 现场链：过渡窗口空闲球台不可排台并给出原因',
    state.assignButtons.length > 0 && state.assignButtons.every((t) => t === '本阶段已结束'),
    `assign buttons=[${state.assignButtons.join(', ')}]`)

  // ---------------------------------------------------------- 5. 生成淘汰签
  const generated = await page.evaluate(`(async () => {
    const resp = await fetch('/api/tournaments/${TID}/generate-knockout', { method: 'POST', credentials: 'same-origin' })
    return { status: resp.status, body: resp.ok ? null : (await resp.text()).slice(0, 160) }
  })()`)
  check('C-D5 现场链：后端允许生成淘汰签', generated.status === 200, `HTTP ${generated.status} ${generated.body ?? ''}`)

  await page.goto(`/console?tid=${TID}`)
  state = await waitForConsole(page, (s) => s.total !== null)
  check('C-D5 现场链：进入淘汰赛后恢复排台能力（不被小组赛逻辑锁死）',
    state.hasBatch === true, `hasBatch=${state.hasBatch} 等待=${state.total - state.finished}`)
  check('C-D5 现场链：淘汰赛阶段不再显示阶段结束横幅', state.noticeTitle === '',
    `notice="${state.noticeTitle}"`)

  const knockoutBatch = await page.evaluate(CLICK_BATCH)
  check('C-D5 现场链：淘汰赛可自动排台', knockoutBatch === true, `clicked=${knockoutBatch}`)
  await sleep(1200)
  const knockoutPlaying = await page.evaluate(`document.querySelectorAll('.live-table-card.is-playing').length`)
  check('C-D5 现场链：淘汰赛比赛进入球台', knockoutPlaying > 0, `进行中球台=${knockoutPlaying}`)

  // ---------------------------------------------------------- 6. Schedule 反映淘汰轮次
  await page.goto(`/schedule?tid=${TID}`)
  await sleep(900)
  const schedule = await page.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.schedule-table tbody tr')]
    const stages = rows.map((r) => r.children[1].textContent.trim())
    const statuses = [...document.querySelectorAll('.schedule-status')].map((s) => s.textContent.trim())
    const meta = (document.querySelector('.print-snapshot-meta')?.innerText ?? '').replace(/\\s+/g, ' ')
    return {
      rows: rows.length,
      knockoutLabels: [...new Set(stages.filter((s) => !s.includes('小组赛')))],
      finished: statuses.filter((s) => s === '已结束').length,
      meta,
    }
  })()`)
  check('C-D5 现场链：Schedule 显示全部 31 场（24 小组 + 7 淘汰）', schedule.rows === 31,
    `rows=${schedule.rows}`)
  check('C-D5 现场链：Schedule 使用后端签表轮次名', schedule.knockoutLabels.length > 0
    && schedule.knockoutLabels.every((l) => !l.includes('R1') && !l.includes('第')), 
    `labels=[${schedule.knockoutLabels.join(', ')}]`)
  check('C-D5 现场链：Schedule 显示已完成比分', schedule.finished === 24, `已结束=${schedule.finished}`)
  check('C-D5 现场链：Schedule 打印快照语义齐全',
    schedule.meta.includes('生成时间') && schedule.meta.includes('实时系统快照') && schedule.meta.includes('非官方秩序册'),
    schedule.meta.slice(0, 120))

  // ---------------------------------------------------------- 7. 排名与秩序册
  await page.goto(`/orderbook?tid=${TID}`)
  await sleep(900)
  const orderBook = await page.evaluate(`(() => {
    const rows = document.querySelectorAll('.order-schedule tbody tr').length
    const notice = (document.querySelector('.order-official-notice')?.innerText ?? '').includes('暂未关联官方秩序册')
    return { rows, notice }
  })()`)
  check('C-D5 现场链：秩序册含完整赛程', orderBook.rows === 31, `rows=${orderBook.rows}`)
  check('C-D5 现场链：秩序册仍明确非官方发布版本', orderBook.notice === true, `notice=${orderBook.notice}`)

  await page.close()
  browser.close()
  return report()
}

function report() {
  console.log('')
  const passed = lines.filter((l) => l.startsWith('[PASS]')).length
  const total = passed + failures.length
  console.log(`C-D5 FIELD CHAIN GATE (${MODE}): ${passed}/${total} PASS`)
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
