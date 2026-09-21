/**
 * D 轨 Day 3 真机尺寸端到端验收（真实 Chrome + 真实后端）。
 *
 * 用 CDP 在 390×844 的手机视口里**真的用键盘输入 + 点击**，然后回到服务端核对事实：
 *
 *   1. 只录大比分提交 → 服务端该场比赛 FINISHED、比分正确、games 为空（无伪造逐局）
 *   2. 连点提交按钮 3 次 → 服务端只留下 1 条 RECORD 审计（前端重复点击保护 + 后端幂等）
 *   3. 非法小比分（汇总与大比分不一致）→ 页面显示服务端业务文案，服务端状态不变
 *   4. 1:0（不符合本赛事局制）→ 前端不阻断，请求到达后端并展示服务端 422 文案
 *   5. 异常结果（弃权）→ 服务端 result_type/forfeit_entry_id 落库、无逐局小分；
 *      页面显示「XX弃权」而不是正常比分
 *
 * 配套脚本与运行前置见 `scripts_mobile_viewport_check.mjs` 文件头（Day 3 验收四件套）。
 *
 * 用法：
 *   node day3_mobile_e2e.mjs <baseUrl> <tid> <matchIdForA> <matchIdForC> <matchIdForD> <matchIdForB>
 * 前置：后端已启动；`day3_e2e_fixture.py` 已输出上面四个 matchId（每次跑用新 fixture，
 *      因为这些比赛在验收过程中会被真的写成 FINISHED）。
 */

const base = process.argv[2] ?? 'http://127.0.0.1:8099'
const [tid, matchA, matchC, matchD, matchB] = process.argv.slice(3).map(Number)
const CDP = 'http://127.0.0.1:9333'

const failures = []
const lines = []
function check(name, ok, detail) {
  lines.push(`[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`)
  if (!ok) failures.push(name)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function api(path) {
  const resp = await fetch(`${base}${path}`)
  return resp.json()
}

const version = await (await fetch(`${CDP}/json/version`)).json()
const ws = new WebSocket(version.webSocketDebuggerUrl)
let msgId = 0
const pending = new Map()
ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data)
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg)
    pending.delete(msg.id)
  }
})
await new Promise((resolve) => ws.addEventListener('open', resolve))

function rawSend(method, params = {}, sessionId) {
  return new Promise((resolve) => {
    const id = ++msgId
    pending.set(id, resolve)
    ws.send(JSON.stringify({ id, method, params, sessionId }))
  })
}

const target = await rawSend('Target.createTarget', { url: 'about:blank' })
const attached = await rawSend('Target.attachToTarget', { targetId: target.result.targetId, flatten: true })
const sid = attached.result.sessionId
const send = (method, params = {}) => rawSend(method, params, sid)

async function evaluate(expression) {
  const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (out.result.exceptionDetails) {
    throw new Error(`eval error: ${out.result.exceptionDetails.text} ${JSON.stringify(out.result.exceptionDetails.exception ?? {})}`)
  }
  return out.result.result.value
}

async function openMatch(matchId) {
  await send('Page.navigate', { url: `${base}/admin/t/${tid}/score/${matchId}` })
  for (let i = 0; i < 80; i += 1) {
    await sleep(150)
    const ok = await evaluate(`!!document.querySelector('.ms-submit')`).catch(() => false)
    if (ok) return
  }
  throw new Error(`page did not render for match ${matchId}`)
}

/** React 受控数字/文本输入：用原生 setter + input/change 事件驱动 onChange。 */
async function setInputAt(index, value, scope = 'input') {
  return evaluate(`(() => {
    const el = document.querySelectorAll(${JSON.stringify(scope)})[${index}]
    if (!el) return 'NOT_FOUND'
    const proto = el instanceof window.HTMLSelectElement ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
    setter.call(el, ${JSON.stringify(value)})
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
    return el.value
  })()`)
}

async function setSelect(selector, value) {
  return setInputAt(0, value, selector)
}

/** 按 aria-label 子串过滤后取第几个输入框（比写死 index 稳，也比加 id 稳 —— React 会抹掉手写的 id）。 */
async function setInputByLabel(labelSubstring, occurrence, value) {
  const index = await evaluate(`(() => {
    const all = [...document.querySelectorAll('input')]
    const hits = all.filter((i) => (i.getAttribute('aria-label') || '').includes(${JSON.stringify(labelSubstring)}))
    if (hits.length <= ${occurrence}) return -1
    return all.indexOf(hits[${occurrence}])
  })()`)
  if (index < 0) return 'NOT_FOUND'
  return setInputAt(index, value)
}

/** 当前所有输入框的值（诊断用）。 */
async function readInputs() {
  return evaluate(`[...document.querySelectorAll('input')].map((i) => (i.getAttribute('aria-label') || i.type) + '=' + i.value).join(' | ')`)
}

async function click(selector) {
  return evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true })()`)
}

await send('Page.enable')
await send('Runtime.enable')
await send('Network.enable')
await send('Network.setCacheDisabled', { cacheDisabled: true })
await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })

// ---------------------------------------------------------------- 1 + 2：只录大比分 + 连点
lines.push('### scenario A: big score only, with triple-click on submit')
await openMatch(matchA)
const before = await api(`/api/tournaments/${tid}/matches`)
const targetBefore = before.find((m) => m.id === matchA)
check('A 开局状态可录分', ['WAITING', 'PLAYING'].includes(targetBefore.status), `status=${targetBefore.status}`)

const typedA = await setInputByLabel('大比分', 0, '2')
const typedB = await setInputByLabel('大比分', 1, '1')
check('A 可以用手机键盘输入大比分', typedA === '2' && typedB === '1', `a=${typedA} b=${typedB} inputs=[${await readInputs()}]`)

// 同一事件循环内连点 3 次
await evaluate(`(() => { const b = document.querySelector('.ms-submit'); b.click(); b.click(); b.click(); return true })()`)
let finishedText = null
for (let i = 0; i < 40; i += 1) {
  await sleep(200)
  finishedText = await evaluate(`document.querySelector('.ms-done-title')?.textContent ?? null`)
  if (finishedText) break
}
check('A 页面显示「比分已保存」', finishedText === '比分已保存', `text=${finishedText}`)

const after = await api(`/api/tournaments/${tid}/matches`)
const targetAfter = after.find((m) => m.id === matchA)
check('A 服务端真的 FINISHED', targetAfter.status === 'FINISHED', `status=${targetAfter.status}`)
check('A 服务端比分正确', targetAfter.player_a_score === 2 && targetAfter.player_b_score === 1, `${targetAfter.player_a_score}:${targetAfter.player_b_score}`)
check('A 服务端没有伪造逐局小比分', targetAfter.games.length === 0, `games=${targetAfter.games.length}`)

const audits = await api(`/api/matches/${matchA}/score-audits`)
const records = audits.filter((a) => a.action === 'RECORD')
check('A 连点 3 次只写入 1 条 RECORD', records.length === 1, `RECORD=${records.length}`)
check('A 完成态显示真实比分与结束语', await evaluate(`document.body.innerText.includes('2 : 1') && document.body.innerText.includes('比赛已结束')`) === true, 'done card')

// ---------------------------------------------------------------- 3：非法小比分
lines.push('')
lines.push('### scenario C: invalid per-game scores (aggregate vs games mismatch)')
await openMatch(matchC)
await setInputByLabel('大比分', 0, '2')
await setInputByLabel('大比分', 1, '1')
await click('.ms-games-toggle')
await sleep(300)
// 展开后默认 3 行；先删掉第 3 局，再填成 B 直落两局（7:11 / 9:11）
// 这样逐局汇总 = 0:2，与大比分 A 胜 2:1 冲突 —— 正好触发服务端的“一致性”校验。
await evaluate(`(() => {
  const btns = [...document.querySelectorAll('.ms-game-remove')]
  btns[btns.length - 1].click()
  return true
})()`)
await sleep(200)
const gameFills = [
  ['第1局', 0, '7'], ['第1局', 1, '11'],
  ['第2局', 0, '9'], ['第2局', 1, '11'],
]
for (const [label, occurrence, value] of gameFills) {
  const typed = await setInputByLabel(label, occurrence, value)
  if (typed === 'NOT_FOUND') {
    check(`C 能录入${label}第${occurrence + 1}边`, false, `inputs=[${await readInputs()}]`)
    break
  }
}
const gameCount = await evaluate(`document.querySelectorAll('.ms-game-inputs input').length`)
check('C 逐局小比分可录入', gameCount === 4, `gameInputs=${gameCount} inputs=[${await readInputs()}]`)
await click('.ms-submit')
let errorText = null
for (let i = 0; i < 30; i += 1) {
  await sleep(200)
  errorText = await evaluate(`document.querySelector('.ms-error')?.textContent ?? null`)
  if (errorText) break
}
check('C 页面显示服务端业务错误', typeof errorText === 'string' && errorText.includes('不一致'), `text=${errorText}`)

const afterC = (await api(`/api/tournaments/${tid}/matches`)).find((m) => m.id === matchC)
check('C 服务端状态未被改动', afterC.status !== 'FINISHED' && afterC.games.length === 0, `status=${afterC.status} games=${afterC.games.length}`)
check('C 输入未被清空', await evaluate(`[...document.querySelectorAll('.ms-score-input')].map((i) => i.value).join(',')`) === '2,1', 'inputs kept')

// ---------------------------------------------------------------- 2b：前端不再用 gamesToWin 阻断
lines.push('')
lines.push('### scenario B: 1:0 in a 2-game format must still reach the backend (no client-side rule)')
await openMatch(matchB)
await setInputByLabel('大比分', 0, '1')
await setInputByLabel('大比分', 1, '0')
const localHint = await evaluate(`document.querySelector('.ms-submit-hint')?.textContent ?? null`)
check(
  'B 前端不再提示“胜方大比分必须为 2”',
  typeof localHint !== 'string' || !localHint.includes('局制'),
  `hint=${localHint}`,
)
await click('.ms-submit')
let errorB = null
for (let i = 0; i < 30; i += 1) {
  await sleep(200)
  errorB = await evaluate(`document.querySelector('.ms-error')?.textContent ?? null`)
  if (errorB) break
}
check(
  'B 非法局制比分由后端裁决并展示服务端文案',
  typeof errorB === 'string' && errorB.includes('服务端未接受本次比分'),
  `text=${errorB}`,
)
const afterB = (await api(`/api/tournaments/${tid}/matches`)).find((m) => m.id === matchB)
check('B 服务端状态未被改动', afterB.status !== 'FINISHED', `status=${afterB.status}`)

// ---------------------------------------------------------------- 4：异常结果
lines.push('')
lines.push('### scenario D: abnormal result (side B forfeit)')
await openMatch(matchD)
await evaluate(`(() => { const tabs = [...document.querySelectorAll('.ms-mode-tab')]; tabs[1].click(); return true })()`)
await sleep(200)
await setSelect('.ms-field select', 'FORFEIT')
await evaluate(`(() => { const radios = [...document.querySelectorAll('input[name="ms-forfeit-side"]')]; radios[1].click(); return true })()`)
await sleep(200)
await click('.ms-submit')
await sleep(300)
const confirmShown = await evaluate(`document.querySelector('.ms-confirm') !== null`)
check('D 提交前必须二次确认', confirmShown === true, `confirm visible=${confirmShown}`)
await evaluate(`(() => { const btns = [...document.querySelectorAll('.ms-confirm button')]; btns[btns.length - 1].click(); return true })()`)

let doneText = null
for (let i = 0; i < 40; i += 1) {
  await sleep(200)
  doneText = await evaluate(`document.body.innerText`)
  if (doneText && doneText.includes('比分已保存')) break
}
const afterD = (await api(`/api/tournaments/${tid}/matches`)).find((m) => m.id === matchD)
check('D 服务端 result_type=FORFEIT', afterD.result_type === 'FORFEIT', `result_type=${afterD.result_type}`)
check('D 服务端 forfeit_entry_id 落库', afterD.forfeit_entry_id === (afterD.entry_b_id ?? afterD.player_b_id), `forfeit_entry_id=${afterD.forfeit_entry_id}`)
check('D 服务端不生成逐局小比分', afterD.games.length === 0, `games=${afterD.games.length}`)
check('D 页面显示异常结论而不是正常比分', typeof doneText === 'string' && doneText.includes('弃权'), 'done text contains 弃权')
check('D 页面明确区分行政比分', typeof doneText === 'string' && doneText.includes('排名用行政比分'), 'admin score labelled')

lines.push('')
lines.push(`=== summary: FAIL=${failures.length} ===`)
if (failures.length > 0) lines.push(`failed: ${failures.join(' | ')}`)
console.log(lines.join('\n'))
await send('Target.closeTarget', { targetId: target.result.targetId }).catch(() => {})
process.exit(failures.length > 0 ? 1 : 0)
