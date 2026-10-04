/**
 * V0.3 三赛制生成链路：真实浏览器验收（Chrome DevTools Protocol）。
 *
 * 验收的是**产品入口**，不是 service 层：全部通过真实点击 `/draw` 上的按钮，
 * 再回到 `/console` 看现场是否真的出现了可排台的比赛。
 *
 * ```text
 * A. ROUND_ROBIN         /settings → /draw「生成循环赛」→ /console 15 场 WAITING
 * B. SINGLE_ELIMINATION  /settings → /draw 设 1 号种子 →「生成单淘汰签」
 *                        → /knockout 签表 → /console 5 场 WAITING（2 场 BYE 已自动晋级）
 * C. GROUP_KNOCKOUT      /settings → /draw「生成分组」→「生成小组比赛」
 *                        → /console 12 场 WAITING
 * ```
 *
 * 关键反向断言（§28/§29）：
 *
 * - ROUND_ROBIN 的 Console **不得**出现「生成淘汰赛 / 等待接口 / 小组出线」；
 * - SINGLE_ELIMINATION 的 Draw **不得**出现小组链入口，也**不得**触发
 *   `auto-group` / `generate-group-matches` / `generate-knockout`；
 * - `/draw` 上必须已经不存在"等待单循环生成接口""首轮淘汰签仍等待"这两句旧文案。
 *
 * 用法（先跑 fixture，再跑本脚本）：
 *
 * ```powershell
 * cd backend
 * node .\v03_format_gen_browser_check.mjs [base] [username] [password]
 * ```
 *
 * 前置：后端已在 `base` 上运行，Chrome 以 `--remote-debugging-port=9333` 启动。
 */

import { connectCdp, loginInBrowser, preparePage, sleep } from './day3_cdp_auth.mjs'

const BASE = (process.argv[2] ?? 'http://127.0.0.1:8099').replace(/\/$/, '')
const USERNAME = process.argv[3] ?? 'v03-format-admin'
const PASSWORD = process.argv[4] ?? 'v03-format-pass1'

const failures = []
const notes = []

function check(name, ok, detail) {
  const line = `[${ok ? 'PASS' : 'FAIL'}] ${name} :: ${detail}`
  console.log(line)
  if (!ok) failures.push(name)
}

function note(name, detail) {
  const line = `[NOTE] ${name} :: ${detail}`
  console.log(line)
  notes.push(line)
}

// ------------------------------------------------------------------ HTTP 侧（只读核对）

async function apiLogin() {
  const resp = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USERNAME, password: PASSWORD, mode: 'bearer' }),
  })
  if (!resp.ok) throw new Error(`HTTP 登录失败: ${resp.status} ${await resp.text()}`)
  return (await resp.json()).access_token
}

async function apiGet(token, path) {
  const resp = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } })
  const body = await resp.json().catch(() => null)
  return { status: resp.status, body }
}

// ------------------------------------------------------------------ CDP 侧

async function waitForText(cdp, needle, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  let text = ''
  while (Date.now() < deadline) {
    text = await cdp.evaluate('document.body.innerText')
    if (typeof text === 'string' && text.includes(needle)) return true
    await sleep(200)
  }
  return false
}

async function goto(cdp, path, marker) {
  await cdp.send('Page.navigate', { url: `${BASE}${path}` })
  const ok = await waitForText(cdp, marker)
  if (!ok) {
    const text = await cdp.evaluate('document.body.innerText')
    throw new Error(`页面 ${path} 未出现「${marker}」\n----- 实际页面文本 -----\n${text}`)
  }
  return cdp.evaluate('document.body.innerText')
}

async function clickButton(cdp, label) {
  const result = await cdp.evaluate(`(() => {
    const buttons = [...document.querySelectorAll('button')]
    const found = buttons.find((b) => (b.textContent || '').trim() === ${JSON.stringify(label)})
    if (!found) return { ok: false, reason: 'not-found', buttons: buttons.map((b) => (b.textContent || '').trim()).slice(0, 80) }
    if (found.disabled) return { ok: false, reason: 'disabled' }
    found.click()
    return { ok: true }
  })()`)
  if (!result.ok) throw new Error(`点击「${label}」失败: ${JSON.stringify(result)}`)
}

async function clickFirstSeedCandidate(cdp) {
  const result = await cdp.evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').includes('＋'))
    if (!button) return { ok: false }
    button.click()
    return { ok: true }
  })()`)
  if (!result.ok) throw new Error('未找到种子候选按钮（＋）')
}

async function findTournamentId(token, marker) {
  const listed = await apiGet(token, '/api/tournaments')
  if (listed.status !== 200) throw new Error(`读取赛事列表失败: ${listed.status}`)
  const match = listed.body.find((t) => typeof t.name === 'string' && t.name.includes(marker))
  if (!match) throw new Error(`未找到名称包含「${marker}」的赛事，请先运行 v03_format_gen_fixture.py`)
  return match.id
}

// ------------------------------------------------------------------ 主流程

async function main() {
  const token = await apiLogin()

  const cdp = await connectCdp()
  await preparePage(cdp, { width: 1440, height: 950 })
  const login = await loginInBrowser(cdp, BASE, USERNAME, PASSWORD)
  check(
    '浏览器建立真实会话',
    login.status === 200 && login.sessionCookiePresent && login.sessionHttpOnly,
    `status=${login.status} cookie=${login.sessionCookiePresent} httpOnly=${login.sessionHttpOnly}`,
  )

  // ---------------------------------------------------------------- A. ROUND_ROBIN
  const rr = await findTournamentId(token, 'V0.3 验收 A ·')
  note('ROUND_ROBIN tid', String(rr))

  const rrSettings = await goto(cdp, `/settings?tid=${rr}`, '当前适用规则')
  check('A1 /settings 按赛事真实赛制展示', rrSettings.includes('全体循环赛'), 'settings 显示「全体循环赛」')

  const rrDraw = await goto(cdp, `/draw?tid=${rr}`, '单循环编排')
  check('A2 /draw 不再显示"等待单循环生成接口"', !rrDraw.includes('等待单循环生成接口'), '旧等待文案已消失')
  check('A3 /draw 没有淘汰赛/小组入口', !/生成淘汰|生成分组|生成小组比赛/.test(rrDraw), '无淘汰赛与小组链入口')
  check('A4 /draw 生成按钮可用', rrDraw.includes('生成循环赛'), '存在「生成循环赛」')

  await clickButton(cdp, '生成循环赛')
  const rrNotice = await waitForText(cdp, '已生成 15 场循环赛。')
  check('A5 点击后真实生成 15 场循环赛', rrNotice, '页面回执：已生成 15 场循环赛。')

  const rrMatches = await apiGet(token, `/api/tournaments/${rr}/matches`)
  const rrTournament = await apiGet(token, `/api/tournaments/${rr}`)
  check(
    'A6 后端事实：15 场 GROUP / WAITING，stage=GROUP_STAGE',
    rrMatches.body.length === 15
      && rrMatches.body.every((m) => m.stage === 'GROUP' && m.status === 'WAITING')
      && rrTournament.body.stage === 'GROUP_STAGE'
      && rrTournament.body.format_code === 'ROUND_ROBIN',
    `matches=${rrMatches.body.length} stage=${rrTournament.body.stage}`,
  )

  const rrConsole = await goto(cdp, `/console?tid=${rr}`, '待进行比赛')
  check('A7 Console 存在 WAITING 比赛', rrConsole.includes('待进行比赛（15）'), '待进行比赛（15）')
  const rrForbidden = ['生成淘汰赛', '等待接口', '小组出线'].filter((needle) => rrConsole.includes(needle))
  check('A8 Console 无淘汰赛/等待接口/小组出线文案', rrForbidden.length === 0, `命中=${JSON.stringify(rrForbidden)}`)

  // ---------------------------------------------------------------- B. SINGLE_ELIMINATION
  const se = await findTournamentId(token, 'V0.3 验收 B ·')
  note('SINGLE_ELIMINATION tid', String(se))

  const seSettings = await goto(cdp, `/settings?tid=${se}`, '当前适用规则')
  check('B1 /settings 按赛事真实赛制展示', seSettings.includes('单淘汰'), 'settings 显示「单淘汰」')

  const seDraw = await goto(cdp, `/draw?tid=${se}`, '单败淘汰签')
  check('B2 /draw 不再显示"首轮淘汰签仍等待"', !seDraw.includes('首轮淘汰签仍等待'), '旧等待文案已消失')
  check('B3 /draw 没有小组链入口', !/生成分组|生成小组比赛|生成淘汰赛/.test(seDraw), '无小组链入口')

  await clickFirstSeedCandidate(cdp)
  const seedSaved = await waitForText(cdp, '种子顺序已保存。')
  check('B4 单打种子可用真实接口保存', seedSaved, '页面回执：种子顺序已保存。')

  await clickButton(cdp, '生成单淘汰签')
  const seNotice = await waitForText(cdp, '已生成 7 场淘汰赛。')
  check('B5 点击后真实生成主签 7 场', seNotice, '页面回执：已生成 7 场淘汰赛。')

  const seMatches = await apiGet(token, `/api/tournaments/${se}/matches`)
  const seTournament = await apiGet(token, `/api/tournaments/${se}`)
  const seKnockout = seMatches.body.filter((m) => m.stage === 'KNOCKOUT')
  const seGroup = seMatches.body.filter((m) => m.stage === 'GROUP')
  const byeCount = seKnockout.filter((m) => m.result_type === 'WALKOVER').length
  check(
    'B6 后端事实：主签 7 场 / 无小组赛 / stage=KNOCKOUT',
    seKnockout.length === 7
      && seGroup.length === 0
      && seTournament.body.stage === 'KNOCKOUT'
      && seTournament.body.format_code === 'SINGLE_ELIMINATION',
    `knockout=${seKnockout.length} group=${seGroup.length} stage=${seTournament.body.stage}`,
  )
  check('B7 6 人非 2 幂：BYE 由既有 Handler 记为 WALKOVER', byeCount === 2, `walkover=${byeCount}`)

  const seBracket = await goto(cdp, `/knockout?tid=${se}`, '决赛')
  check('B8 /knockout 渲染真实签表', seBracket.includes('8强赛') && seBracket.includes('决赛'), '含 8强赛 与 决赛')
  check('B9 签表不出现小组语义', !seBracket.includes('小组出线'), '无小组出线')

  const seConsole = await goto(cdp, `/console?tid=${se}`, '待进行比赛')
  check('B10 Console 存在 WAITING 比赛', seConsole.includes('待进行比赛（5）'), '待进行比赛（5）')
  check('B11 Console 不伪造小组阶段', !/小组赛尚未|小组出线/.test(seConsole), '无小组赛语义')

  // ---------------------------------------------------------------- C. GROUP_KNOCKOUT
  const gk = await findTournamentId(token, 'V0.3 验收 C ·')
  note('GROUP_KNOCKOUT tid', String(gk))

  const gkSettings = await goto(cdp, `/settings?tid=${gk}`, '当前适用规则')
  check('C1 /settings 按赛事真实赛制展示', gkSettings.includes('小组赛 + 淘汰赛'), 'settings 显示「小组赛 + 淘汰赛」')

  await goto(cdp, `/draw?tid=${gk}`, '小组抽签结果')
  await clickButton(cdp, '生成分组')
  const grouped = await waitForText(cdp, '分组已由后端生成并保存。')
  check('C2 生成分组主链可用', grouped, '页面回执：分组已由后端生成并保存。')

  await clickButton(cdp, '生成小组比赛')
  const gkNotice = await waitForText(cdp, '已生成 12 场小组比赛。')
  check('C3 生成小组比赛主链可用（legacy 入口未退化）', gkNotice, '页面回执：已生成 12 场小组比赛。')

  const gkMatches = await apiGet(token, `/api/tournaments/${gk}/matches`)
  const gkTournament = await apiGet(token, `/api/tournaments/${gk}`)
  check(
    'C4 后端事实：12 场小组赛，stage=GROUP_STAGE',
    gkMatches.body.length === 12
      && gkMatches.body.every((m) => m.stage === 'GROUP' && m.status === 'WAITING')
      && gkTournament.body.stage === 'GROUP_STAGE'
      && gkTournament.body.format_code === 'GROUP_KNOCKOUT',
    `matches=${gkMatches.body.length} stage=${gkTournament.body.stage}`,
  )

  const gkConsole = await goto(cdp, `/console?tid=${gk}`, '待进行比赛')
  check('C5 Console 存在 WAITING 比赛', gkConsole.includes('待进行比赛（12）'), '待进行比赛（12）')

  await cdp.close()

  console.log('')
  if (failures.length) {
    console.log(`RESULT=FAIL (${failures.length}) :: ${failures.join(' | ')}`)
    return 1
  }
  console.log(`RESULT=PASS (${notes.length} notes)`)
  return 0
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(`RESULT=ERROR :: ${error && error.stack ? error.stack : error}`)
    process.exit(2)
  },
)
