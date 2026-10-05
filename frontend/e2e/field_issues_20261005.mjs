/**
 * 现场问题清单（2026-10-05）真实浏览器验收。
 *
 * 环境：真实 FastAPI + 真实 SQLite + 真实 Chromium（channel: chrome）。
 * 目的：覆盖 jsdom 无法证明的部分 —— viewport 可达性、CSS 布局、SVG 与卡片
 * 在横向滚动 / resize 后的**视口坐标**对齐、以及双裁判并发冲突的真实 HTTP 行为。
 *
 * 用法（先启动带独立库的后端，并在 frontend 执行 pnpm build）：
 *   PINGPONG_DB_PATH=<tmp>/field_e2e.db python -m uvicorn app.main:app --port 8011
 *   node field_issues.mjs
 */

import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8011'
const OUT = process.env.OUT_DIR ?? 'D:/PingPong_Platform_Project/field-evidence'

mkdirSync(OUT, { recursive: true })

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok: Boolean(ok), detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  ::  ${detail}` : ''}`)
}
function section(title) {
  console.log(`\n=============== ${title} ===============`)
}

async function api(ctx, method, url, body) {
  const res = await ctx.request.fetch(`${BASE}${url}`, {
    method,
    data: body === undefined ? undefined : body,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
  })
  const text = await res.text()
  let json = null
  try { json = text ? JSON.parse(text) : null } catch { /* 非 JSON */ }
  return { status: res.status(), json, text }
}

// ---------------------------------------------------------------- 视口可达性工具

/**
 * 某个控件是否"用户真的够得到"：
 * 1. 滚动到它（模拟用户滚动弹窗内部）；
 * 2. 它的盒模型必须完整落在 viewport 内；
 * 3. 它中心点上的最上层元素必须仍属于录分弹窗（没有被别的层盖住）。
 */
async function reachable(page, selector) {
  const loc = page.locator(selector).first()
  const count = await loc.count()
  if (count === 0) return { ok: false, why: '元素不存在' }
  await loc.scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(30)
  const box = await loc.boundingBox()
  if (!box) return { ok: false, why: 'boundingBox 为空（不可见？）' }
  const vp = page.viewportSize()
  const inViewport = box.x >= -1 && box.y >= -1
    && box.x + box.width <= vp.width + 1 && box.y + box.height <= vp.height + 1
  const topmost = await page.evaluate(({ x, y }) => {
    const el = document.elementFromPoint(x, y)
    if (!el) return 'null'
    if (el.closest('.score-sheet')) return null
    return `${el.tagName}.${typeof el.className === 'string' ? el.className : ''}`
  }, { x: box.x + box.width / 2, y: box.y + box.height / 2 })
  if (!inViewport) return { ok: false, why: `超出 viewport: box=${JSON.stringify(box)} vp=${JSON.stringify(vp)}` }
  if (topmost) return { ok: false, why: `被遮挡: ${topmost}` }
  return { ok: true, why: '' }
}

async function bracketShot(page, name) {
  // 窄屏下管理端侧边栏会占满首屏；先把签表滚进视口。
  // 再分别截"横向滚动到最左 / 中间 / 最右"三张：这正是本轮修复要证明的性质
  // （滚动时连线必须跟着卡片一起走），单张静止截图说明不了问题。
  const wrap = page.locator('.ko-bracket-wrap').first()
  await wrap.scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(200)
  const positions = [['left', 0], ['mid', 0.5], ['right', 1]]
  for (const [label, ratio] of positions) {
    await page.evaluate((r) => {
      const el = document.querySelector('.ko-bracket')
      el.scrollLeft = r === 0 ? 0 : Math.floor((el.scrollWidth - el.clientWidth) * r) + (r === 1 ? 1 : 0)
    }, ratio)
    await page.waitForTimeout(200)
    await wrap.screenshot({ path: path.join(OUT, `${name}-${label}.png`) }).catch(() => {})
  }
}

async function horizontalOverflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }))
}

// ---------------------------------------------------------------- 签表几何工具

/**
 * 用**视口坐标**逐条校验 SVG path 与卡片几何是否对齐。
 *
 * 这是本轮最关键的证据：旧结构把 SVG 放在横向滚动容器外面，
 * 一旦 `.ko-bracket` 滚动，卡片的视口坐标变了而 SVG 没变，这里的 delta 就会 > 0。
 */
async function checkBracketAlignment(page) {
  return page.evaluate(() => {
    const parsePath = (d) => {
      const nums = (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number)
      return nums
    }
    const canvas = document.querySelector('.ko-canvas')
    if (!canvas) return { error: 'no .ko-canvas' }
    const svg = document.querySelector('svg.ko-lines')
    if (!svg) return { error: 'no svg.ko-lines' }
    const svgRect = svg.getBoundingClientRect()
    const cards = [...document.querySelectorAll('[data-mid]')].map((el) => {
      const r = el.getBoundingClientRect()
      return {
        id: Number(el.getAttribute('data-mid')),
        left: r.left, right: r.right, cy: r.top + r.height / 2, width: r.width,
      }
    })
    const champs = [...document.querySelectorAll('[data-champ]')].map((el) => {
      const r = el.getBoundingClientRect()
      return { left: r.left, right: r.right, cy: r.top + r.height / 2 }
    })
    const paths = [...document.querySelectorAll('svg.ko-lines path')].map((p) => p.getAttribute('d'))
    const TOL = 0.75
    const mismatches = []
    let matched = 0
    let championLines = 0

    for (const d of paths) {
      const n = parsePath(d)
      if (n.length === 5) {
        // "M x0 y0 H x1 V y1 H x2" —— 上游分支线
        const [x0, y0, y1, x2] = [n[0], n[1], n[3], n[4]]
        // path 坐标是 SVG 用户坐标（= canvas 内的 CSS px）；换算回视口坐标
        const vx0 = svgRect.left + x0
        const vy0 = svgRect.top + y0
        const vy1 = svgRect.top + y1
        const vx2 = svgRect.left + x2
        const feeder = cards.find((c) => Math.abs(c.right - vx0) < TOL && Math.abs(c.cy - vy0) < TOL)
        const target = cards.find((c) => Math.abs(c.left - vx2) < TOL && Math.abs(c.cy - vy1) < TOL)
        if (feeder && target) matched += 1
        else {
          mismatches.push({
            d, feeder: feeder ? feeder.id : null, target: target ? target.id : null,
            nearestFeeder: cards.map((c) => ({ id: c.id, dx: +(c.right - vx0).toFixed(2), dy: +(c.cy - vy0).toFixed(2) }))
              .sort((a, b) => Math.abs(a.dx) + Math.abs(a.dy) - Math.abs(b.dx) - Math.abs(b.dy))[0],
          })
        }
      } else if (n.length === 3) {
        // "M x0 y0 H x1" —— 冠军线
        const [x0, y0, x1] = [n[0], n[1], n[2]]
        const vx0 = svgRect.left + x0
        const vy0 = svgRect.top + y0
        const vx1 = svgRect.left + x1
        const feeder = cards.find((c) => Math.abs(c.right - vx0) < TOL && Math.abs(c.cy - vy0) < TOL)
        const champ = champs.find((c) => Math.abs(c.left - 14 - vx1) < TOL)
        if (feeder && champ) championLines += 1
        else mismatches.push({ d, championLine: true, feeder: feeder ? feeder.id : null, champ: Boolean(champ) })
      } else {
        mismatches.push({ d, unparsed: n })
      }
    }

    return {
      totalPaths: paths.length,
      matched,
      championLines,
      mismatches,
      bracketScrollLeft: document.querySelector('.ko-bracket')?.scrollLeft ?? null,
      bracketScrollWidth: document.querySelector('.ko-bracket')?.scrollWidth ?? null,
      bracketClientWidth: document.querySelector('.ko-bracket')?.clientWidth ?? null,
      pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
    }
  })
}

// ---------------------------------------------------------------- 环境准备

const ADMIN = { username: 'field-e2e-admin', display_name: '现场验收管理员', password: 'FieldE2E!2026#Pass' }
const EVENT_ADMIN = { username: 'field-e2e-operator', display_name: '现场验收主裁', password: 'FieldE2E!2026#Oper' }
let TID = null
let KO_TREE = null

async function bootstrapAndLogin(ctx) {
  const status = await api(ctx, 'GET', '/api/v1/system/bootstrap/status')
  if (status.json?.status === 'NEEDS_INITIALIZATION') {
    const boot = await api(ctx, 'POST', '/api/v1/system/bootstrap', ADMIN)
    if (boot.status >= 300) throw new Error(`bootstrap failed: ${boot.status} ${boot.text}`)
  }
  let login = await api(ctx, 'POST', '/api/v1/auth/login', {
    username: ADMIN.username, password: ADMIN.password,
  })
  if (login.status >= 300) throw new Error(`login(system admin) failed: ${login.status} ${login.text}`)

  // 建赛事需要 EVENT_ADMIN（require_event_admin）；SYSTEM_ADMIN 只能建账号。
  const created = await api(ctx, 'POST', '/api/v1/system/users', EVENT_ADMIN)
  if (created.status >= 300 && created.status !== 409) {
    throw new Error(`create event admin failed: ${created.status} ${created.text}`)
  }
  login = await api(ctx, 'POST', '/api/v1/auth/login', {
    username: EVENT_ADMIN.username, password: EVENT_ADMIN.password,
  })
  if (login.status >= 300) throw new Error(`login(event admin) failed: ${login.status} ${login.text}`)
  const me = await api(ctx, 'GET', '/api/v1/auth/me')
  check('真实后端：bootstrap + 建 EVENT_ADMIN + 登录成功',
    me.status === 200 && me.json?.user?.username === EVENT_ADMIN.username
      && me.json?.user?.system_role === 'EVENT_ADMIN',
    `status=${me.status} user=${me.json?.user?.username} role=${me.json?.user?.system_role}`)
}

async function setupTournament(ctx) {
  const players = 16
  const create = await api(ctx, 'POST', '/api/tournaments', {
    name: '现场问题验收赛 20261005',
    date: '2026-10-05',
    table_count: 4,
    group_count: 4,
    qualify_per_group: 2,
    games_to_win: 2,
    points_to_win: 11,
    format_code: 'GROUP_KNOCKOUT',
  })
  if (create.status >= 300) throw new Error(`create tournament: ${create.status} ${create.text}`)
  TID = create.json.id

  for (let i = 1; i <= players; i += 1) {
    const r = await api(ctx, 'POST', `/api/tournaments/${TID}/players`, { name: `选手${String(i).padStart(2, '0')}` })
    if (r.status >= 300) throw new Error(`add player ${i}: ${r.status} ${r.text}`)
  }
  await api(ctx, 'POST', `/api/tournaments/${TID}/confirm-roster`)
  const grouped = await api(ctx, 'POST', `/api/tournaments/${TID}/auto-group`)
  if (grouped.status >= 300) throw new Error(`auto-group: ${grouped.status} ${grouped.text}`)
  const gen = await api(ctx, 'POST', `/api/tournaments/${TID}/generate-group-matches`)
  if (gen.status >= 300) throw new Error(`generate-group-matches: ${gen.status} ${gen.text}`)

  const groupMatches = (await api(ctx, 'GET', `/api/tournaments/${TID}/matches?stage=GROUP`)).json ?? []
  for (const m of groupMatches) {
    // 让"选手 id 小的一方"全胜，形成组内严格全序 → 不会出现需要人工裁定的并列。
    // 同时补上逐局小分（排名 tie-break 需要真实小分数据）。
    const aId = m.player_a_id ?? m.entry_a_id
    const bId = m.player_b_id ?? m.entry_b_id
    const aWins = aId < bId
    const r = await api(ctx, 'POST', `/api/matches/${m.id}/score`, {
      player_a_score: aWins ? 2 : 0,
      player_b_score: aWins ? 0 : 2,
      games: aWins
        ? [{ side_a_score: 11, side_b_score: 5 }, { side_a_score: 11, side_b_score: 7 }]
        : [{ side_a_score: 5, side_b_score: 11 }, { side_a_score: 7, side_b_score: 11 }],
      result_type: 'NORMAL',
      request_id: crypto.randomUUID(), operator_name: '验收脚本',
    })
    if (r.status >= 300) throw new Error(`score group match ${m.id}: ${r.status} ${r.text}`)
  }
  const ko = await api(ctx, 'POST', `/api/tournaments/${TID}/generate-knockout`)
  if (ko.status >= 300) throw new Error(`generate-knockout: ${ko.status} ${ko.text}`)
  KO_TREE = ko.json

  const tables = (await api(ctx, 'GET', `/api/tournaments/${TID}/dashboard`)).json?.tables ?? []
  const waiting = (await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=WAITING`)).json ?? []
  check(
    '环境准备：八强签表 + 多场 WAITING + 多张 FREE 球台',
    (KO_TREE?.rounds?.length ?? 0) === 3 && waiting.length >= 2 && tables.filter((t) => t.status === 'FREE').length >= 2,
    `rounds=${KO_TREE?.rounds?.length} waiting=${waiting.length} freeTables=${tables.filter((t) => t.status === 'FREE').length}`,
  )
}

// ---------------------------------------------------------------- CASE A / B

async function caseA(page, ctx) {
  section('CASE A — 待进行比赛 → 指定球台（Match → Table）')
  const dash0 = (await api(ctx, 'GET', `/api/tournaments/${TID}/dashboard`)).json
  const waiting = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=WAITING`)).json ?? [])
    .filter((m) => (dash0.next_playable ?? []).some((p) => p.id === m.id))
  const freeTables = (dash0.tables ?? []).filter((t) => t.status === 'FREE')
  check('CASE A 前置：至少 2 场后端可安排比赛 + 2 张 FREE 球台',
    waiting.length >= 2 && freeTables.length >= 2,
    `playable=${waiting.length} free=${freeTables.length}`)

  const targetMatch = waiting[0]
  const otherMatch = waiting[1]
  // 明确挑"第 2 张空闲球台"，验证不是只能自动分配
  const targetTable = freeTables[1]

  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(`${BASE}/console?tid=${TID}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.waiting-match-card', { timeout: 15000 })

  const card = page.locator('.waiting-match-card', { hasText: `#${targetMatch.id}` }).first()
  check('CASE A：待进行比赛卡片出现「指定球台」入口', await card.getByRole('button', { name: '指定球台' }).count() === 1)

  await card.getByRole('button', { name: '指定球台' }).click()
  const dialog = page.getByRole('dialog', { name: `为比赛 #${targetMatch.id} 指定球台` })
  await dialog.waitFor({ timeout: 5000 })
  const choices = dialog.locator('.console-table-item')
  const choiceNames = await choices.allInnerTexts()
  const occupiedNames = (dash0.tables ?? []).filter((t) => t.status !== 'FREE').map((t) => t.name)
  check('CASE A：候选只列出后端 FREE 球台，不含占用球台',
    choiceNames.length === freeTables.length && !choiceNames.some((n) => occupiedNames.some((o) => n.includes(o))),
    `候选=${JSON.stringify(choiceNames)} 占用=${JSON.stringify(occupiedNames)}`)

  const chosenIndex = choiceNames.findIndex((n) => n.includes(targetTable.name))
  await choices.nth(chosenIndex).click()
  await page.waitForTimeout(1200)

  const mAfter = (await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? []
  const dashAfter = (await api(ctx, 'GET', `/api/tournaments/${TID}/dashboard`)).json
  const moved = mAfter.find((m) => m.id === targetMatch.id)
  const tableAfter = dashAfter.tables.find((t) => t.id === targetTable.id)
  check('CASE A：Match.status = PLAYING 且 table_id 正确',
    moved?.status === 'PLAYING' && moved?.table_id === targetTable.id,
    `match#${targetMatch.id} status=${moved?.status} table_id=${moved?.table_id} 期望台=${targetTable.id}`)
  check('CASE A：对应球台变为 OCCUPIED', tableAfter?.status === 'OCCUPIED', `table=${targetTable.name} status=${tableAfter?.status}`)

  const otherAfter = (await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=WAITING`)).json ?? []
  check('CASE A2：其他 WAITING Match 不受影响',
    otherAfter.some((m) => m.id === otherMatch.id) && otherAfter.every((m) => m.table_id === null),
    `仍有 #${otherMatch.id}=${otherAfter.some((m) => m.id === otherMatch.id)}`)

  // 排序/渲染层面：球台卡片必须显示该场对阵
  await page.waitForTimeout(800)
  const liveCard = page.locator('.live-table-card', { hasText: targetTable.name }).first()
  check('CASE A：现场球台卡片显示该场比赛（页面已 refresh）',
    (await liveCard.innerText()).includes('进行中'), (await liveCard.innerText()).replace(/\s+/g, ' ').slice(0, 90))

  // 现在确实有了一张 OCCUPIED 球台：再开一次面板，确认它已被排除在候选之外。
  await page.waitForTimeout(1200) // 等一次 5 秒轮询内的刷新落地
  const card2 = page.locator('.waiting-match-card', { hasText: `#${otherMatch.id}` }).first()
  if (await card2.getByRole('button', { name: '指定球台' }).count() === 1) {
    await card2.getByRole('button', { name: '指定球台' }).click()
    const dialog2 = page.getByRole('dialog', { name: `为比赛 #${otherMatch.id} 指定球台` })
    await dialog2.waitFor({ timeout: 5000 })
    const names2 = await dialog2.locator('.console-table-item').allInnerTexts()
    check('CASE A：已占用球台从候选中消失（候选只来自后端 FREE 状态）',
      !names2.some((n) => n.includes(targetTable.name)) && names2.length === freeTables.length - 1,
      `候选=${JSON.stringify(names2.map((n) => n.replace(/\s+/g, ' ')))} 期望排除 ${targetTable.name}`)
    await page.keyboard.press('Escape').catch(() => {})
    await dialog2.locator('.modal-close').click()
    await page.waitForTimeout(200)
  } else {
    check('CASE A：已占用球台从候选中消失（候选只来自后端 FREE 状态）', false, '第二场比赛的入口未出现')
  }

  section('CASE B — 自动安排下一批比赛仍可用')
  const beforePlaying = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? []).length
  await page.getByRole('button', { name: '自动安排下一批比赛' }).click()
  await page.waitForTimeout(1500)
  const afterPlaying = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? []).length
  check('CASE B：自动排台仍然给空闲球台安排比赛', afterPlaying > beforePlaying,
    `playing ${beforePlaying} -> ${afterPlaying}`)
}

// ---------------------------------------------------------------- CASE F

async function caseF(page) {
  section('CASE F — 淘汰赛移动端连线几何（初始 / 滚动 / resize）')
  const topology = []
  for (const round of KO_TREE.rounds) {
    for (const m of round.matches) {
      for (const feeder of [m.prev_match_a_id, m.prev_match_b_id]) {
        if (feeder != null) topology.push([feeder, m.id])
      }
    }
  }
  const expectedLines = topology.length
  const hasChampion = Boolean(KO_TREE.champion)

  for (const vp of [{ width: 360, height: 640 }, { width: 390, height: 844 }, { width: 1280, height: 900 }]) {
    await page.setViewportSize(vp)
    await page.goto(`${BASE}/knockout?tid=${TID}`, { waitUntil: 'networkidle' })
    await page.waitForSelector('.ko-canvas [data-mid]', { timeout: 15000 })
    await page.waitForTimeout(400)

    const tag = `${vp.width}x${vp.height}`

    const initial = await checkBracketAlignment(page)
    check(`CASE F[${tag}] 初始位置：全部 ${expectedLines} 条分支线均对齐对应比赛`,
      initial.mismatches.length === 0 && initial.matched === expectedLines,
      `matched=${initial.matched}/${expectedLines} mismatches=${initial.mismatches.length} ${initial.mismatches.length ? JSON.stringify(initial.mismatches.slice(0, 2)) : ''}`)
    check(`CASE F[${tag}] 冠军线对齐（champion=${hasChampion}）`,
      hasChampion ? initial.championLines === 1 : initial.championLines === 0,
      `championLines=${initial.championLines}`)
    check(`CASE F[${tag}] 页面无横向溢出`, initial.pageOverflow <= 1, `overflow=${initial.pageOverflow}px`)

    // 横向滚动到最右 —— 旧实现（SVG 在滚动容器外）正是在这里开始错位
    await page.evaluate(() => {
      const el = document.querySelector('.ko-bracket')
      el.scrollLeft = el.scrollWidth
    })
    await page.waitForTimeout(300)
    const scrolled = await checkBracketAlignment(page)
    check(`CASE F[${tag}] 横向滚动到最右后：分支线仍连接对应 Match`,
      scrolled.mismatches.length === 0 && scrolled.matched === expectedLines,
      `scrollLeft=${scrolled.bracketScrollLeft} scrollWidth=${scrolled.bracketScrollWidth} clientWidth=${scrolled.bracketClientWidth} matched=${scrolled.matched}`)

    // 再滚回中间
    await page.evaluate(() => {
      const el = document.querySelector('.ko-bracket')
      el.scrollLeft = Math.floor(el.scrollWidth / 2)
    })
    await page.waitForTimeout(300)
    const mid = await checkBracketAlignment(page)
    check(`CASE F[${tag}] 滚动到中间后：分支线仍连接对应 Match`, mid.mismatches.length === 0,
      `scrollLeft=${mid.bracketScrollLeft} mismatches=${mid.mismatches.length}`)

    await bracketShot(page, `bracket-${tag}`)
  }

  // resize：宽 → 窄 → 宽
  section('CASE F — resize 宽 → 窄 → 宽')
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(`${BASE}/knockout?tid=${TID}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.ko-canvas [data-mid]')
  await page.waitForTimeout(300)
  const wide1 = await checkBracketAlignment(page)
  await page.setViewportSize({ width: 360, height: 640 })
  await page.waitForTimeout(500)
  const narrow = await checkBracketAlignment(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.waitForTimeout(500)
  const wide2 = await checkBracketAlignment(page)
  check('CASE F：resize 宽→窄→宽以后连线重新归位',
    wide1.mismatches.length === 0 && narrow.mismatches.length === 0 && wide2.mismatches.length === 0,
    `wide1=${wide1.matched}/${expectedLines} narrow=${narrow.matched}/${expectedLines} wide2=${wide2.matched}/${expectedLines}`)

  // 横竖屏（portrait <-> landscape）
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(400)
  const portrait = await checkBracketAlignment(page)
  await page.setViewportSize({ width: 844, height: 390 })
  await page.waitForTimeout(400)
  const landscape = await checkBracketAlignment(page)
  check('CASE F：竖屏 ↔ 横屏切换后连线仍对齐',
    portrait.mismatches.length === 0 && landscape.mismatches.length === 0,
    `portrait=${portrait.matched}/${expectedLines} landscape=${landscape.matched}/${expectedLines}`)
}

// ---------------------------------------------------------------- CASE C / D / E（录分弹窗）

/** 打开「修改大比分」录分弹窗（revise 流程，含修改理由字段）。 */
async function openReviseSheet(page) {
  await page.goto(`${BASE}/console?tid=${TID}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.data-table', { timeout: 15000 })
  await page.getByRole('button', { name: '修改大比分' }).first().click()
  await page.waitForSelector('.score-sheet', { timeout: 5000 })
  await page.waitForTimeout(200)
}

async function caseCDE(page) {
  section('CASE C / D — 录分弹窗 viewport 可达性矩阵')
  const viewports = [
    { width: 360, height: 640, label: '360x640' },
    { width: 390, height: 844, label: '390x844' },
    { width: 768, height: 1024, label: '768x1024' },
    { width: 1280, height: 720, label: '1280x720（普通电脑 100%）' },
    { width: 360, height: 420, label: '360x420（等效短 viewport）' },
  ]

  const controls = [
    ['标题', '.score-sheet h2'],
    ['A 方选手', '.score-sheet .touch-score-a span'],
    ['B 方选手', '.score-sheet .touch-score-b span'],
    ['A 方大比分输入', '.score-sheet .touch-score-a input'],
    ['B 方大比分输入', '.score-sheet .touch-score-b input'],
    ['裁判备注', '.score-sheet .score-note input'],
    ['操作人', '.score-sheet .score-audit-fields input'],
    ['修改理由', '.score-sheet .score-audit-fields textarea'],
    ['取消按钮', '.score-sheet .modal-actions .btn:not(.primary)'],
    ['检查并修改按钮', '.score-sheet .modal-actions .btn.primary'],
    ['关闭按钮', '.score-sheet .modal-close'],
  ]

  for (const vp of viewports) {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await openReviseSheet(page)

    const bad = []
    for (const [name, sel] of controls) {
      const r = await reachable(page, sel)
      if (!r.ok) bad.push(`${name}: ${r.why}`)
    }
    check(`CASE C[${vp.label}] 标题/双方/大比分/备注/操作人/修改理由/取消/确认 全部可达`,
      bad.length === 0, bad.length ? bad.join(' | ') : '11/11 可达')

    // 吸底效果：还没滚动时，底部主操作就应该已经在视口内且没有被遮挡。
    const preScroll = await page.evaluate(() => {
      const btn = document.querySelector('.score-sheet .modal-actions .btn.primary')
      if (!btn) return { visible: false, why: '按钮不存在' }
      const r = btn.getBoundingClientRect()
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
      return {
        visible: r.top >= -1 && r.bottom <= window.innerHeight + 1
          && Boolean(el && el.closest('.score-sheet')),
        top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight,
      }
    })
    check(`CASE C[${vp.label}] 未滚动时底部主操作已在屏内（弹窗内吸底）`,
      preScroll.visible, `buttonTop=${preScroll.top} buttonBottom=${preScroll.bottom} viewportH=${preScroll.vh}`)

    const ov = await horizontalOverflow(page)
    check(`CASE C[${vp.label}] 无横向页面溢出`, ov.scrollWidth <= ov.innerWidth + 1,
      `scrollWidth=${ov.scrollWidth} innerWidth=${ov.innerWidth}`)

    // 弹窗必须在背景列表之上：fixed overlay + 中心点最上层元素属于弹窗
    const cover = await page.evaluate(() => {
      const backdrop = document.querySelector('.score-sheet-backdrop')
      const cs = getComputedStyle(backdrop)
      const sheet = document.querySelector('.score-sheet')
      const r = sheet.getBoundingClientRect()
      const el = document.elementFromPoint(r.left + r.width / 2, Math.min(r.top + 20, window.innerHeight - 2))
      return {
        position: cs.position, inset: `${cs.top},${cs.right},${cs.bottom},${cs.left}`,
        zIndex: cs.zIndex, overflowY: cs.overflowY,
        topmostInSheet: Boolean(el && el.closest('.score-sheet')),
        sheetHeight: Math.round(r.height), viewportHeight: window.innerHeight,
        sheetWidth: Math.round(r.width), viewportWidth: window.innerWidth,
      }
    })
    check(`CASE C[${vp.label}] 弹窗是 viewport overlay 而非文档流内容`,
      cover.position === 'fixed' && cover.topmostInSheet && cover.sheetHeight <= cover.viewportHeight + 1 && cover.sheetWidth <= cover.viewportWidth + 1,
      `position=${cover.position} z=${cover.zIndex} sheet=${cover.sheetWidth}x${cover.sheetHeight} vp=${cover.viewportWidth}x${cover.viewportHeight} 顶层属于弹窗=${cover.topmostInSheet}`)

    // 背景列表滚动：弹窗几何不得改变，且仍在最上层
    const before = await page.evaluate(() => {
      const r = document.querySelector('.score-sheet').getBoundingClientRect()
      return { top: Math.round(r.top), left: Math.round(r.left) }
    })
    await page.evaluate(() => window.scrollBy(0, 600))
    await page.waitForTimeout(200)
    const after = await page.evaluate(() => {
      const r = document.querySelector('.score-sheet').getBoundingClientRect()
      const el = document.elementFromPoint(r.left + r.width / 2, Math.min(r.top + 20, window.innerHeight - 2))
      return { top: Math.round(r.top), left: Math.round(r.left), topmostInSheet: Boolean(el && el.closest('.score-sheet')) }
    })
    check(`CASE C[${vp.label}] 背景滚动后弹窗仍停在当前屏幕上层`,
      after.top === before.top && after.left === before.left && after.topmostInSheet,
      `before=${JSON.stringify(before)} after=${JSON.stringify(after)}`)

    await page.screenshot({ path: path.join(OUT, `scoresheet-${vp.width}x${vp.height}.png`) })
    await page.getByRole('button', { name: '取消' }).click()
    await page.waitForTimeout(150)
  }

  // 高页面缩放（等效短 viewport）：CSS zoom 会让布局视口按比例缩小
  section('CASE D — 高页面缩放等效短 viewport（1280x720 @ zoom 2 = 640x360 布局）')
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto(`${BASE}/console?tid=${TID}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.data-table')
  await page.evaluate(() => { document.documentElement.style.zoom = '2' })
  await page.waitForTimeout(300)
  // 先量"没有弹窗时"背景页面自身的横向溢出，再量"打开弹窗后"的溢出：
  // 两者之差才是弹窗引入的溢出（背景控制台表格在高缩放下的溢出是既有情况）。
  const overflowClosed = (await horizontalOverflow(page)).scrollWidth
  await openReviseSheet(page)
  await page.evaluate(() => { document.documentElement.style.zoom = '2' })
  await page.waitForTimeout(400)
  const zoomed = []
  for (const [name, sel] of [['标题', '.score-sheet h2'], ['A 方大比分', '.score-sheet .touch-score-a input'],
    ['B 方大比分', '.score-sheet .touch-score-b input'], ['操作人', '.score-sheet .score-audit-fields input'],
    ['修改理由', '.score-sheet .score-audit-fields textarea'],
    ['取消按钮', '.score-sheet .modal-actions .btn:not(.primary)'],
    ['检查并修改按钮', '.score-sheet .modal-actions .btn.primary'],
    ['关闭按钮', '.score-sheet .modal-close']]) {
    const r = await reachable(page, sel)
    if (!r.ok) zoomed.push(`${name}: ${r.why}`)
  }
  const overflowOpen = await horizontalOverflow(page)
  const modalOwnOverflow = await page.evaluate(() => {
    const sheet = document.querySelector('.score-sheet').getBoundingClientRect()
    return { sheetRight: Math.round(sheet.right), innerWidth: window.innerWidth }
  })
  check('CASE D[zoom 2] 标题/大比分/操作人/修改理由/底部操作仍全部可达',
    zoomed.length === 0, zoomed.join(' | ') || '8/8 可达')
  check('CASE D[zoom 2] 弹窗自身不超出视口宽度',
    modalOwnOverflow.sheetRight <= modalOwnOverflow.innerWidth + 1,
    `sheetRight=${modalOwnOverflow.sheetRight} innerWidth=${modalOwnOverflow.innerWidth}`)
  check('CASE D[zoom 2] 弹窗不引入任何横向页面溢出',
    overflowOpen.scrollWidth <= overflowClosed + 1,
    `有弹窗=${overflowOpen.scrollWidth} 无弹窗=${overflowClosed}（背景控制台表格在 200% 缩放下的既有溢出，与弹窗无关）`)
  await page.screenshot({ path: path.join(OUT, 'scoresheet-zoom2.png') })
  await page.evaluate(() => { document.documentElement.style.zoom = '1' })
  await page.getByRole('button', { name: '取消' }).click().catch(() => {})
  await page.waitForTimeout(200)
}

async function caseE(page) {
  section('CASE E — 修改理由不足 2 个字时必须让用户看懂规则')
  await page.setViewportSize({ width: 1280, height: 900 })
  await openReviseSheet(page)

  const hint = await page.locator('.score-sheet .score-field-hint').innerText()
  check('CASE E：未输入时规则就可见（必填 + 至少 2 个字）', /至少\s*2\s*个字/.test(hint), hint.replace(/\s+/g, ' '))

  const textarea = page.locator('.score-sheet .score-audit-fields textarea')
  check('CASE E：textarea 带 minLength=2', await textarea.getAttribute('minlength') === '2')

  // 先满足其他必填项，才能确认"按钮不可点是修改理由造成的"
  await page.locator('.score-sheet .score-audit-fields input').fill('现场主裁')
  await page.locator('.score-sheet .touch-score-a input').fill('2')
  await page.locator('.score-sheet .touch-score-b input').fill('0')

  await textarea.fill('错')
  await page.waitForTimeout(150)
  const errVisible = await page.locator('.score-sheet .score-field-error').count()
  const errText = errVisible ? (await page.locator('.score-sheet .score-field-error').first().innerText()).replace(/\s+/g, ' ') : ''
  const btn = page.locator('.score-sheet .modal-actions .btn.primary')
  const disabled1 = await btn.isDisabled()
  const hint1 = (await page.locator('.score-sheet .score-field-hint').innerText()).replace(/\s+/g, ' ')
  check('CASE E：只填 1 个字时给出字段级错误 + 字数提示，且按钮不可点',
    errVisible === 1 && disabled1 && /至少\s*2\s*个字|不足\s*2\s*个字/.test(errText) && /已填\s*1\s*个字/.test(hint1),
    `error="${errText}" hint="${hint1}" disabled=${disabled1}`)

  await textarea.fill('记错')
  await page.waitForTimeout(150)
  const stillErr = await page.locator('.score-sheet .score-field-error').count()
  const disabled2 = await btn.isDisabled()
  check('CASE E：补足 2 个字后错误消失且按钮可点', stillErr === 0 && !disabled2,
    `errorCount=${stillErr} disabled=${disabled2}`)

  // 只填空格 → 视为 0 个字
  await textarea.fill('   ')
  await page.waitForTimeout(150)
  const spaceOk = await page.locator('.score-sheet .score-field-error').count() === 1
    && /0\s*个字/.test((await page.locator('.score-sheet .score-field-hint').innerText()).replace(/\s+/g, ' '))
  check('CASE E：只填空格按 0 个字处理，不会静默卡住', spaceOk)
  await page.locator('.score-sheet .modal-close').click()

  // 补录逐局小分（detailMode）同一规则
  await page.goto(`${BASE}/console?tid=${TID}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.data-table')
  const row = page.locator('.data-table tbody tr').first()
  await row.getByText('更多', { exact: true }).click()
  const entry = row.getByRole('button', { name: /补录小比分|修改小比分/ }).first()
  await entry.click()
  await page.waitForSelector('.score-sheet')
  await page.waitForTimeout(200)
  const detailHint = (await page.locator('.score-sheet .score-field-hint').innerText()).replace(/\s+/g, ' ')
  const detailTitle = await page.locator('.score-sheet h2').innerText()
  check('CASE E：补录/修改逐局小分（detailMode）同样展示“至少 2 个字”',
    /至少\s*2\s*个字/.test(detailHint), `title=${detailTitle} hint=${detailHint}`)
  await page.locator('.score-sheet .modal-close').click()
}

// ---------------------------------------------------------------- CASE F2：签表打满（含冠军线）

async function playOutKnockout(ctx) {
  for (let guard = 0; guard < 12; guard += 1) {
    const ko = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?stage=KNOCKOUT`)).json ?? [])
      .filter((m) => m.status !== 'FINISHED' && m.player_a_id != null && m.player_b_id != null)
    if (ko.length === 0) return
    for (const m of ko) {
      const aWins = m.player_a_id < m.player_b_id
      const r = await api(ctx, 'POST', `/api/matches/${m.id}/score`, {
        player_a_score: aWins ? 2 : 0, player_b_score: aWins ? 0 : 2,
        result_type: 'NORMAL', request_id: crypto.randomUUID(), operator_name: '验收脚本',
      })
      if (r.status >= 300) throw new Error(`play out match ${m.id}: ${r.status} ${r.text}`)
    }
  }
}

async function caseF2Champion(page, ctx) {
  section('CASE F2 — 签表打满（八强→半决赛→决赛→冠军）：连线仍不串线')
  await playOutKnockout(ctx)
  const tree = (await api(ctx, 'GET', `/api/tournaments/${TID}/knockout`)).json
  const topology = []
  for (const round of tree.rounds) {
    for (const m of round.matches) {
      for (const feeder of [m.prev_match_a_id, m.prev_match_b_id]) {
        if (feeder != null) topology.push([feeder, m.id])
      }
    }
  }
  check('CASE F2：签表已打满且产生冠军', Boolean(tree.champion) && topology.length > 0,
    `champion=${tree.champion?.name ?? 'null'} rounds=${tree.rounds.length} 分支线=${topology.length}`)

  for (const vp of [{ width: 360, height: 640 }, { width: 390, height: 844 }, { width: 1280, height: 900 }]) {
    await page.setViewportSize(vp)
    await page.goto(`${BASE}/knockout?tid=${TID}`, { waitUntil: 'networkidle' })
    await page.waitForSelector('.ko-canvas [data-mid]', { timeout: 15000 })
    await page.waitForTimeout(400)
    const tag = `${vp.width}x${vp.height}`

    const initial = await checkBracketAlignment(page)
    check(`CASE F2[${tag}] 满签表：${topology.length} 条分支线全部对齐（含冠军线）`,
      initial.mismatches.length === 0 && initial.matched === topology.length && initial.championLines === 1,
      `matched=${initial.matched}/${topology.length} championLines=${initial.championLines} mismatches=${initial.mismatches.length}`)

    await page.evaluate(() => { const el = document.querySelector('.ko-bracket'); el.scrollLeft = el.scrollWidth })
    await page.waitForTimeout(300)
    const scrolled = await checkBracketAlignment(page)
    check(`CASE F2[${tag}] 满签表横向滚动到最右：仍全部对齐`,
      scrolled.mismatches.length === 0 && scrolled.matched === topology.length && scrolled.championLines === 1,
      `scrollLeft=${scrolled.bracketScrollLeft} matched=${scrolled.matched} championLines=${scrolled.championLines}`)

    await bracketShot(page, `bracket-full-${tag}`)
  }
}

// ---------------------------------------------------------------- CASE G / H

async function caseG(page, ctx) {
  section('CASE G — 双裁判同场：一个成功、一个 409、数据库结果唯一、失败端自动 reload')

  // 准备一场 PLAYING 比赛（先下台再重排，避免用掉已经打过的）
  const dash = (await api(ctx, 'GET', `/api/tournaments/${TID}/dashboard`)).json
  let playing = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? [])
  if (playing.length === 0) {
    const free = dash.tables.find((t) => t.status === 'FREE')
    const cand = dash.next_playable[0]
    await api(ctx, 'POST', `/api/matches/${cand.id}/assign-table`, { table_id: free.id })
    playing = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? [])
  }
  const match = playing[0]
  check('CASE G 前置：存在一场 PLAYING 比赛', Boolean(match), `match=#${match?.id} status=${match?.status}`)

  // 失败端（裁判 B）先打开录分页，表单基于"比赛仍在进行中"的旧状态
  await page.setViewportSize({ width: 390, height: 844 })
  const browserPosts = []
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/matches\/\d+\/score/.test(req.url())) browserPosts.push(req.url())
  })
  await page.goto(`${BASE}/admin/t/${TID}/matches/${match.id}/score`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.ms-submit', { timeout: 15000 })
  await page.locator('.ms-score-side').first().locator('input').fill('2')
  await page.locator('.ms-score-side--b').locator('input').fill('0')
  await page.locator('.ms-card--notes input').fill('裁判B')

  // 裁判 A 用另一个终端（独立 request_id）先提交成功
  const aScore = { player_a_score: 2, player_b_score: 1 }
  const aRes = await api(ctx, 'POST', `/api/matches/${match.id}/score`, {
    ...aScore, result_type: 'NORMAL', request_id: crypto.randomUUID(), operator_name: '裁判A',
  })
  check('CASE G：裁判 A 提交成功（200）', aRes.status === 200, `status=${aRes.status} ${aRes.text.slice(0, 120)}`)

  // 裁判 B 提交 → 必须 409，且页面必须自动 reload 到最新完成态
  await page.locator('.ms-submit').click()
  await page.waitForTimeout(2500)

  const bodyText = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
  const bannerCount = await page.locator('.ms-refresh-warning').count()
  const stillHasForm = await page.getByRole('button', { name: '确认提交大比分' }).count()
  const stillSubmitting = await page.getByRole('button', { name: '提交中…' }).count()

  check('CASE G：失败端只发出一次比分 POST（409 未被自动重试）', browserPosts.length === 1,
    `POST 次数=${browserPosts.length}`)
  check('CASE G：失败端自动 reload 并进入最新完成态（不再停在旧可提交表单）',
    bodyText.includes('比赛已结束') && stillHasForm === 0,
    `完成态=${bodyText.includes('比赛已结束')} 旧表单按钮数=${stillHasForm}`)
  check('CASE G：失败端显示服务端真实比分（2:1），不是本地待提交的 2:0',
    bodyText.includes('2 : 1') && !bodyText.includes('2 : 0'),
    `含 2:1=${bodyText.includes('2 : 1')}`)
  check('CASE G：告知裁判冲突并说明已加载最新结果',
    bannerCount > 0 && /该场比赛已由其他终端更新，已加载最新结果/.test(bodyText),
    `banner=${bannerCount}`)
  check('CASE G：无无限 loading（提交中状态已释放）', stillSubmitting === 0)

  const audits = (await api(ctx, 'GET', `/api/matches/${match.id}/score-audits`)).json ?? []
  const finalMatch = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches`)).json ?? []).find((m) => m.id === match.id)
  check('CASE G：数据库结果唯一（一条审计、一份比分、状态 FINISHED）',
    audits.length === 1 && finalMatch?.status === 'FINISHED'
    && finalMatch?.player_a_score === 2 && finalMatch?.player_b_score === 1,
    `audits=${audits.length} status=${finalMatch?.status} score=${finalMatch?.player_a_score}:${finalMatch?.player_b_score}`)

  await page.screenshot({ path: path.join(OUT, 'conflict-finished-390x844.png') })
  page.removeAllListeners('request')
}

async function caseH(ctx) {
  section('CASE H — 不同 Match 并发：两个裁判都应正常成功')
  const dash = (await api(ctx, 'GET', `/api/tournaments/${TID}/dashboard`)).json
  let playing = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? [])
  // 需要两场同时 PLAYING
  while (playing.length < 2) {
    const d = (await api(ctx, 'GET', `/api/tournaments/${TID}/dashboard`)).json
    const free = d.tables.find((t) => t.status === 'FREE')
    const cand = d.next_playable[0]
    if (!free || !cand) break
    await api(ctx, 'POST', `/api/matches/${cand.id}/assign-table`, { table_id: free.id })
    playing = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches?status=PLAYING`)).json ?? [])
  }

  if (playing.length < 2) {
    check('CASE H 前置：两场 PLAYING 比赛', false, `只拿到 ${playing.length} 场`)
    return
  }
  const [m1, m2] = playing
  const [r1, r2] = await Promise.all([
    api(ctx, 'POST', `/api/matches/${m1.id}/score`, {
      player_a_score: 2, player_b_score: 0, result_type: 'NORMAL', request_id: crypto.randomUUID(), operator_name: '裁判甲',
    }),
    api(ctx, 'POST', `/api/matches/${m2.id}/score`, {
      player_a_score: 0, player_b_score: 2, result_type: 'NORMAL', request_id: crypto.randomUUID(), operator_name: '裁判乙',
    }),
  ])
  check('CASE H：不同比赛的并发提交都成功，未被冲突收口误伤',
    r1.status === 200 && r2.status === 200, `r1=${r1.status} r2=${r2.status}`)
  const m1After = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches`)).json ?? []).find((m) => m.id === m1.id)
  const m2After = ((await api(ctx, 'GET', `/api/tournaments/${TID}/matches`)).json ?? []).find((m) => m.id === m2.id)
  check('CASE H：两场都各自写入自己的结果',
    m1After?.status === 'FINISHED' && m2After?.status === 'FINISHED',
    `m1=${m1After?.status} ${m1After?.player_a_score}:${m1After?.player_b_score} / m2=${m2After?.status} ${m2After?.player_a_score}:${m2After?.player_b_score}`)
}

// ---------------------------------------------------------------- 主流程

const browser = await chromium.launch({ channel: 'chrome' })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))

try {
  section('环境')
  await bootstrapAndLogin(context)
  await setupTournament(context)

  await caseA(page, context)
  await caseF(page)
  await caseCDE(page)
  await caseE(page)
  await caseG(page, context)
  await caseH(context)
  await caseF2Champion(page, context)

  section('页面运行时错误')
  check('浏览器无未捕获页面异常', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | ') || 'none')
} catch (error) {
  check('验收脚本本身未抛错', false, String(error && error.stack ? error.stack.split('\n').slice(0, 4).join(' / ') : error))
} finally {
  const failed = results.filter((r) => !r.ok)
  console.log(`\n================= 汇总 =================`)
  console.log(`总计 ${results.length} 项，通过 ${results.length - failed.length}，失败 ${failed.length}`)
  if (failed.length) {
    console.log('\n失败项：')
    for (const f of failed) console.log(` - ${f.name}  ::  ${f.detail}`)
  }
  writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ base: BASE, tid: TID, results }, null, 2), 'utf8')
  await browser.close()
  process.exit(failed.length ? 1 : 0)
}
