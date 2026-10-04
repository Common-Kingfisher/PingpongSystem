/**
 * 淘汰赛签表连线几何回归（现场问题 D）。
 *
 * ## 现场缺陷
 *
 * 移动端（360 / 390px）签表横向滚动后，SVG 分支线与卡片错位；viewport 变化 /
 * 横竖屏切换 / 容器 resize 之后同样错位。
 *
 * ## 根因（两条，缺一不可）
 *
 * 1. SVG 被放在横向滚动容器**外面**（`.ko-bracket-wrap` 的直接子元素）：`.ko-bracket`
 *    一滚动，卡片跟着动而 SVG 不动，于是连线与卡片分离；
 * 2. 测量 effect 只依赖 `[rounds, champion]`，容器 / 卡片几何变化后不会重算。
 *
 * ## 本文件能证明什么、不能证明什么
 *
 * jsdom **没有布局引擎**，`getBoundingClientRect()` 恒为 0。因此这里用**受控桩几何**
 * 验证"测量—重算—清理"这条逻辑链，以及"SVG 与卡片同处一个滚动画布"这一结构性不变量
 * （它才是滚动不错位的充分条件）。
 *
 * 真实像素级对齐（360 / 390 / 桌面）由 Chromium viewport 验收覆盖，不能只靠这里。
 */

/// <reference types="vitest/globals" />
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { KnockoutMatch, KnockoutRound } from '../api'
import KnockoutBracket from '../components/KnockoutBracket'

// ---------------------------------------------------------------- 固定签表拓扑
//
// 八强 4 场（1..4）→ 半决赛 2 场（5 = 1v2、6 = 3v4）→ 决赛 1 场（7 = 5v6）

function koMatch(overrides: Partial<KnockoutMatch> & { id: number; round: number }): KnockoutMatch {
  return {
    match_index: overrides.id,
    status: 'WAITING',
    player_a: null,
    player_b: null,
    player_a_score: null,
    player_b_score: null,
    winner_id: null,
    table_id: null,
    prev_match_a_id: null,
    prev_match_b_id: null,
    bracket: 'MAIN',
    ...overrides,
  }
}

const ROUNDS: KnockoutRound[] = [
  {
    round: 1,
    label: '八强',
    matches: [1, 2, 3, 4].map((id) => koMatch({ id, round: 1 })),
  },
  {
    round: 2,
    label: '半决赛',
    matches: [
      koMatch({ id: 5, round: 2, prev_match_a_id: 1, prev_match_b_id: 2 }),
      koMatch({ id: 6, round: 2, prev_match_a_id: 3, prev_match_b_id: 4 }),
    ],
  },
  {
    round: 3,
    label: '决赛',
    matches: [koMatch({ id: 7, round: 3, prev_match_a_id: 5, prev_match_b_id: 6 })],
  },
]

const CHAMPION = { id: 99, name: '冠军选手', seed_no: 1 }

// ---------------------------------------------------------------- 受控几何

interface Rect {
  top: number
  left: number
  width: number
  height: number
}

/**
 * 每个元素一个可控 rect。默认全部为 0（jsdom 的真实行为），
 * 由用例显式设置"布局结果"。
 */
let rects: Map<Element, Rect>
let rectReads: number

function setRect(el: Element, rect: Rect) {
  rects.set(el, rect)
}

function rectOf(el: Element): Rect {
  return rects.get(el) ?? { top: 0, left: 0, width: 0, height: 0 }
}

/** 画布原点固定在 (0,0)，卡片 rect 直接用画布坐标系表达。 */
function installGeometryStub() {
  rects = new Map()
  rectReads = 0
  Element.prototype.getBoundingClientRect = function getBoundingClientRect(this: Element) {
    rectReads += 1
    const { top, left, width, height } = rectOf(this)
    return {
      x: left,
      y: top,
      top,
      left,
      width,
      height,
      right: left + width,
      bottom: top + height,
      toJSON: () => ({}),
    } as DOMRect
  }
}

// ---------------------------------------------------------------- 受控 ResizeObserver / rAF

interface RoInstance {
  targets: Element[]
  callback: ResizeObserverCallback
  disconnected: boolean
  fire: () => void
}

let observers: RoInstance[] = []
let rafQueue: FrameRequestCallback[] = []

function installObserverStub() {
  observers = []
  class FakeResizeObserver {
    targets: Element[] = []
    disconnected = false
    constructor(public callback: ResizeObserverCallback) {
      observers.push(this as unknown as RoInstance)
    }
    observe(target: Element) {
      this.targets.push(target)
    }
    unobserve() {}
    disconnect() {
      this.disconnected = true
    }
  }
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
}

/** 收集 rAF 回调而不立即执行，便于断言"同一帧内多次触发只测一次"。 */
function installRafStub() {
  rafQueue = []
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    rafQueue.push(cb)
    return rafQueue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
}

function flushFrame() {
  const queued = rafQueue
  rafQueue = []
  for (const cb of queued) cb(0)
}

// ---------------------------------------------------------------- 渲染辅助

function renderBracket() {
  const view = render(
    <KnockoutBracket rounds={ROUNDS} champion={CHAMPION} runnerUp={null} />,
  )
  const canvas = view.container.querySelector('.ko-canvas') as HTMLElement
  const bracket = view.container.querySelector('.ko-bracket') as HTMLElement
  const wrap = view.container.querySelector('.ko-bracket-wrap') as HTMLElement
  const svg = view.container.querySelector('.ko-lines') as SVGSVGElement
  setRect(canvas, { top: 0, left: 0, width: 1200, height: 900 })
  const cards = new Map<number, HTMLElement>()
  view.container.querySelectorAll<HTMLElement>('[data-mid]').forEach((el) => {
    cards.set(Number(el.getAttribute('data-mid')), el)
  })
  const champ = view.container.querySelector('[data-champ]') as HTMLElement
  const paths = () => [...view.container.querySelectorAll('.ko-lines path')].map((p) => p.getAttribute('d'))
  return { ...view, canvas, bracket, wrap, svg, cards, champ, paths }
}

/**
 * 触发一次"容器尺寸变化 → rAF 合并 → 重算"。
 *
 * 首次渲染时 effect 会同步测一次，但那时候桩几何还没设置（jsdom 里元素本来就都是 0），
 * 因此每个用例设置完几何后都要走一遍真实的触发路径，而不是直接调内部函数 ——
 * 这样断言覆盖的才是**生产代码真正依赖的**重算通路。
 */
function remeasure() {
  act(() => {
    window.dispatchEvent(new Event('resize'))
    flushFrame()
  })
}

/**
 * 给 7 场 + 冠军卡设置一套"八强 → 半决赛 → 决赛"的几何：
 * 每轮卡片垂直居中于其两个上游之间（与真实 CSS 的居中立意一致）。
 */
function layoutBracket(b: ReturnType<typeof renderBracket>, opts: { cardLeft?: (id: number) => number } = {}) {
  const width = 210
  const height = 132
  const leftFor = opts.cardLeft ?? ((id: number) => (id <= 4 ? 0 : id <= 6 ? 320 : 640))
  // 八强 cy = 100 / 300 / 500 / 700；半决赛居中；决赛居中
  const centers: Record<number, number> = { 1: 100, 2: 300, 3: 500, 4: 700, 5: 200, 6: 600, 7: 400 }
  for (const [id, el] of b.cards) {
    const cy = centers[id] ?? 0
    setRect(el, { top: cy - height / 2, left: leftFor(id), width, height })
  }
  setRect(b.champ, { top: 400 - 60, left: 960, width, height: 120 })
}

beforeEach(() => {
  installGeometryStub()
  installObserverStub()
  installRafStub()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('现场问题 D：淘汰赛连线几何', () => {
  it('SVG 与全部卡片同处一个横向滚动画布（滚动不会让连线与卡片分离的结构性前提）', () => {
    const b = renderBracket()

    // SVG 必须在滚动画布**内部**：旧实现把它放在滚动容器外面，正是错位的根因。
    expect(b.canvas.contains(b.svg)).toBe(true)
    expect(b.cards.size).toBe(7)
    for (const card of b.cards.values()) expect(b.canvas.contains(card)).toBe(true)

    // 滚动容器同时包含画布与 SVG，三者共享同一坐标系
    expect(b.bracket.contains(b.canvas)).toBe(true)
    expect(b.bracket.contains(b.svg)).toBe(true)
    // 旧结构（SVG 是 wrap 的直接子元素、与滚动容器平级）必须已经不存在
    expect((b.svg.parentElement as HTMLElement).className).toBe('ko-canvas')
  })

  it('八强 → 半决赛 → 决赛的连线各自连到正确的上游，不串线', () => {
    const b = renderBracket()
    layoutBracket(b)
    remeasure()

    const paths = b.paths()
    // 6 条上游连线 + 1 条冠军线
    expect(paths).toHaveLength(7)

    // 半决赛 #5 的两条线必须从 #1 / #2 的右边缘出发，y 等于它们的中心
    expect(paths).toContain('M 210 100 H 290 V 200 H 320')
    expect(paths).toContain('M 210 300 H 290 V 200 H 320')
    // 半决赛 #6 来自 #3 / #4
    expect(paths).toContain('M 210 500 H 290 V 600 H 320')
    expect(paths).toContain('M 210 700 H 290 V 600 H 320')
    // 决赛 #7 来自 #5 / #6
    expect(paths).toContain('M 530 200 H 610 V 400 H 640')
    expect(paths).toContain('M 530 600 H 610 V 400 H 640')
    // 冠军线从决赛右边缘到冠军卡左侧（960 - 14）
    expect(paths).toContain('M 850 400 H 946')

    // 反向检查：绝不能出现"八强直接连到决赛"这类跨轮串线
    expect(paths.some((d) => d === 'M 210 100 H 610 V 400 H 640')).toBe(false)
    expect(paths.some((d) => d === 'M 210 500 H 610 V 400 H 640')).toBe(false)
  })

  it('容器 / 卡片几何变化后重算：连线跟随真实 DOM 几何重新归位', () => {
    const b = renderBracket()
    layoutBracket(b)
    remeasure()
    expect(b.paths()).toContain('M 210 100 H 290 V 200 H 320')

    // 模拟窄屏（360px）下卡片变窄、间距变小 → 所有坐标都应随之改变
    layoutBracket(b, { cardLeft: (id) => (id <= 4 ? 0 : id <= 6 ? 240 : 480) })
    // 桩几何已变，但还没触发测量：路径必须仍是旧的（证明下面看到的更新确实来自重算）
    expect(b.paths()).toContain('M 210 100 H 290 V 200 H 320')

    // ResizeObserver 通知尺寸变化 → rAF 合并后的重算
    act(() => {
      for (const observer of observers) observer.callback([], observer as unknown as ResizeObserver)
      flushFrame()
    })

    const paths = b.paths()
    expect(paths).not.toContain('M 210 100 H 290 V 200 H 320')
    expect(paths).toContain('M 210 100 H 210 V 200 H 240')
    expect(paths).toContain('M 210 300 H 210 V 200 H 240')
  })

  it('ResizeObserver 同时观察画布与外层容器，横竖屏类 resize 也会重算', () => {
    const b = renderBracket()
    layoutBracket(b)
    remeasure()

    const observed = observers.flatMap((observer) => observer.targets)
    expect(observed).toContain(b.canvas)
    expect(observed).toContain(b.wrap)

    // window resize（横竖屏切换不一定会改变被观察盒子的尺寸）
    layoutBracket(b, { cardLeft: (id) => (id <= 4 ? 0 : id <= 6 ? 260 : 520) })
    remeasure()
    expect(b.paths()).toContain('M 210 100 H 230 V 200 H 260')
  })

  it('同一帧内多次触发只测量一次（rAF 合并，避免移动端每帧重复读布局）', () => {
    const b = renderBracket()
    layoutBracket(b)
    remeasure()

    const before = rectReads
    act(() => {
      window.dispatchEvent(new Event('resize'))
      window.dispatchEvent(new Event('resize'))
      window.dispatchEvent(new Event('resize'))
      for (const observer of observers) observer.callback([], observer as unknown as ResizeObserver)
      // 触发 4 次，但这一帧只应排入 1 个回调
      expect(rafQueue).toHaveLength(1)
      flushFrame()
    })
    // 一次测量 = 画布 + 7 张卡片 + 冠军卡 = 9 次读取
    expect(rectReads - before).toBe(9)
  })

  it('卸载后彻底清理：断开 ResizeObserver、移除 resize / orientationchange、取消待执行帧', () => {
    const b = renderBracket()
    layoutBracket(b)
    remeasure()

    // 卸载前先排入一个待执行帧，验证它会被取消
    act(() => { window.dispatchEvent(new Event('resize')) })
    expect(rafQueue).toHaveLength(1)

    b.unmount()

    expect(observers.every((observer) => observer.disconnected)).toBe(true)

    const readsAfterUnmount = rectReads
    const rafCountAfterUnmount = rafQueue.length
    // 卸载后再触发 window resize：不得再测量、不得再排帧、不得抛错
    expect(() => {
      window.dispatchEvent(new Event('resize'))
      window.dispatchEvent(new Event('orientationchange'))
    }).not.toThrow()
    expect(rectReads).toBe(readsAfterUnmount)
    expect(rafQueue).toHaveLength(rafCountAfterUnmount)
  })

  it('签表数据变化会重算（新增一轮后连线随之更新）', () => {
    const view = render(<KnockoutBracket rounds={ROUNDS} champion={null} runnerUp={null} />)
    const canvas = view.container.querySelector('.ko-canvas') as HTMLElement
    setRect(canvas, { top: 0, left: 0, width: 1200, height: 900 })
    view.container.querySelectorAll<HTMLElement>('[data-mid]').forEach((el) => {
      setRect(el, { top: Number(el.getAttribute('data-mid')) * 100, left: 0, width: 210, height: 132 })
    })
    remeasure()
    expect(view.container.querySelectorAll('.ko-lines path').length).toBe(6)

    // 冠军产生后追加冠军连线
    view.rerender(<KnockoutBracket rounds={ROUNDS} champion={CHAMPION} runnerUp={null} />)
    const champ = view.container.querySelector('[data-champ]') as HTMLElement
    setRect(champ, { top: 340, left: 960, width: 210, height: 120 })
    remeasure()
    expect(view.container.querySelectorAll('.ko-lines path')).toHaveLength(7)
    // 最后一条正是冠军线：从决赛卡右边缘(0+210)连到冠军卡左侧(960-14)。
    // 这里每张卡片 top = id*100、height = 132，因此决赛(id=7)中心 y = 766。
    const paths = [...view.container.querySelectorAll('.ko-lines path')].map((p) => p.getAttribute('d'))
    expect(paths[paths.length - 1]).toBe('M 210 766 H 946')
  })
})
