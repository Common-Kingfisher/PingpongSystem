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
 * $env:PINGPONG_E2E_ADMIN_PASSWORD = "<至少 12 位>"
 * node .\v03_format_gen_fixture.py  # 先用 python 跑 fixture，得到 FIXTURE_JSON
 * node .\v03_format_gen_browser_check.mjs [base] [fixtureJsonPath]
 * ```
 *
 * 前置：后端已在 `base` 上运行，Chrome 以 `--remote-debugging-port=9333` 启动。
 *
 * ## fixture 隔离（PR #68 review Finding #4）
 *
 * 旧版本用 `findTournamentId(token, 'V0.3 验收 A ·')` **扫描赛事列表**找"第一个名字
 * 包含标记的赛事"，重复执行 fixture 后会命中上一轮的旧赛事；口令也硬编码成默认值。
 * 现在：tid / 账号名一律从 fixture 输出的 JSON 直接读取（不再扫描列表），
 * 口令只从 `PINGPONG_E2E_ADMIN_PASSWORD` 读取，缺失即 fail closed。
 */

import { readFileSync } from 'node:fs'
import { connectCdp, loginInBrowser, preparePage, sleep } from './day3_cdp_auth.mjs'

const BASE = (process.argv[2] ?? 'http://127.0.0.1:8099').replace(/\/$/, '')

/** 与 fixture 一致的 fail-closed 口令读取：没有任何默认值。 */
const PASSWORD_ENV = 'PINGPONG_E2E_ADMIN_PASSWORD'
const PASSWORD = process.env[PASSWORD_ENV] ?? ''
const MIN_PASSWORD_LENGTH = 12
if (PASSWORD.length < MIN_PASSWORD_LENGTH) {
  console.error(
    `RESULT=ERROR :: 必须设置环境变量 ${PASSWORD_ENV}（至少 ${MIN_PASSWORD_LENGTH} 位）；本脚本不再提供默认口令。`,
  )
  process.exit(2)
}

const FIXTURE_PATH = process.argv[3] ?? process.env.PINGPONG_E2E_FIXTURE ?? ''
if (!FIXTURE_PATH) {
  console.error(
    'RESULT=ERROR :: 必须提供 fixture JSON 路径（argv[3] 或 PINGPONG_E2E_FIXTURE）；'
      + '请先运行 v03_format_gen_fixture.py 并使用它输出的 FIXTURE_JSON。',
  )
  process.exit(2)
}

let fixture
try {
  fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'))
} catch (error) {
  console.error(`RESULT=ERROR :: 无法读取 fixture JSON (${FIXTURE_PATH}) :: ${error.message}`)
  process.exit(2)
}
if (fixture.base_url && fixture.base_url.replace(/\/$/, '') !== BASE) {
  console.error(
    `RESULT=ERROR :: fixture 属于 ${fixture.base_url}，与本次 base ${BASE} 不一致，拒绝复用。`,
  )
  process.exit(2)
}

const USERNAME = fixture.username
const TIDS = fixture.tids ?? {}
for (const key of ['ROUND_ROBIN', 'SINGLE_ELIMINATION', 'GROUP_KNOCKOUT']) {
  if (typeof TIDS[key] !== 'number') {
    console.error(`RESULT=ERROR :: fixture 缺少 tid：${key}`)
    process.exit(2)
  }
}

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

// `findTournamentId`（按赛事名扫描列表）已按 Finding #4 移除：
// 重复执行 fixture 会创建同名赛事，扫描"第一个名字匹配"可能命中上一轮的旧赛事。
// 现在 tid 一律来自 fixture 输出的 JSON。

/**
 * 浏览器 console / 未捕获异常收集器（PR #68 review 第 11 节：console error = 0）。
 *
 * 用 `Page.addScriptToEvaluateOnNewDocument` 在**每个新文档**上安装，因此
 * 反复导航也不会丢事件。`api.ts` 会为失败请求打印 `[api] ... -> 4xx` 诊断（既定行为），
 * 这类诊断与"页面真的报错"必须分开统计，不能混成一个数字。
 */
async function installErrorCollector(cdp) {
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
      window.__ppConsoleErrors = [];
      const record = (kind, text) => {
        try { window.__ppConsoleErrors.push(kind + '\\u0000' + String(text)); } catch (e) { /* noop */ }
      };
      const originalError = console.error.bind(console);
      console.error = (...args) => { record('console.error', args.map(String).join(' ')); originalError(...args); };
      window.addEventListener('error', (event) => record('uncaught', (event && event.message) || 'unknown error'));
      window.addEventListener('unhandledrejection', (event) => {
        const reason = event && event.reason;
        record('unhandledrejection', (reason && (reason.message || reason)) || 'unknown rejection');
      });
    })()`,
  })
}

/** 返回累计的 console / 未捕获异常，并按 `[api]` 诊断拆分。 */
async function readCollectedErrors(cdp) {
  const raw = await cdp.evaluate('JSON.stringify(window.__ppConsoleErrors || [])')
  const entries = JSON.parse(raw ?? '[]').map((line) => {
    const [kind, ...rest] = String(line).split('\u0000')
    return { kind, text: rest.join('\u0000') }
  })
  return {
    all: entries,
    pageErrors: entries.filter((entry) => entry.kind !== 'console.error'),
    apiDiagnostics: entries.filter(
      (entry) => entry.kind === 'console.error' && entry.text.startsWith('[api]'),
    ),
    // console.error 里除 api.ts 既定诊断之外的条目，才是真正的"页面报错"。
    unexpectedConsoleErrors: entries.filter(
      (entry) => entry.kind === 'console.error' && !entry.text.startsWith('[api]'),
    ),
  }
}

// ------------------------------------------------------------------ 主流程

async function main() {
  const token = await apiLogin()

  const cdp = await connectCdp()
  await preparePage(cdp, { width: 1440, height: 950 })
  await installErrorCollector(cdp)
  const login = await loginInBrowser(cdp, BASE, USERNAME, PASSWORD)
  check(
    '浏览器建立真实会话',
    login.status === 200 && login.sessionCookiePresent && login.sessionHttpOnly,
    `status=${login.status} cookie=${login.sessionCookiePresent} httpOnly=${login.sessionHttpOnly}`,
  )
  note('fixture run_id', String(fixture.run_id ?? '(未提供)'))

  // ---------------------------------------------------------------- A. ROUND_ROBIN
  const rr = TIDS.ROUND_ROBIN
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
  const se = TIDS.SINGLE_ELIMINATION
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
  const gk = TIDS.GROUP_KNOCKOUT
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

  // ---------------------------------------------------------------- 浏览器自身健康度
  const collected = await readCollectedErrors(cdp)
  check(
    'D1 浏览器无未捕获异常 / 未处理的 Promise 拒绝',
    collected.pageErrors.length === 0,
    collected.pageErrors.length
      ? JSON.stringify(collected.pageErrors.slice(0, 5))
      : '0 条',
  )
  check(
    'D2 除 api.ts 既定失败请求诊断外，console.error = 0',
    collected.unexpectedConsoleErrors.length === 0,
    collected.unexpectedConsoleErrors.length
      ? JSON.stringify(collected.unexpectedConsoleErrors.slice(0, 5))
      : `0 条（另有 ${collected.apiDiagnostics.length} 条 [api] 请求诊断，属既定行为）`,
  )

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
