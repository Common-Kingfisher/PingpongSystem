/// <reference types="vitest/globals" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Match } from '../api'
import ScoreSheet from '../components/ScoreSheet'
import BigScreenPage from '../pages/BigScreenPage'

afterEach(cleanup)

describe('Day6 physical field defects', () => {
  it('DF-002: big screen headings use unrestricted overflow wrapping', () => {
    render(
      <MemoryRouter initialEntries={['/bigscreen?tid=12']}>
        <BigScreenPage tid={12} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { level: 1 })).toBeTruthy()
    const css = readFileSync(join(process.cwd(), 'src', 'index.css'), 'utf8')
    const headingRule = /\.bigscreen-header h1\s*\{[\s\S]*?\}/.exec(css)?.[0] ?? ''
    expect(headingRule).toContain('overflow-wrap: anywhere')
  })
})

// ------------------------------------------------------------------ 现场问题 B：弹窗必须属于 viewport

const CSS = readFileSync(join(process.cwd(), 'src', 'index.css'), 'utf8')

/** 取出某个选择器后面的第一条声明块（这些规则没有嵌套，直接找配对的 `}`）。 */
function declarationBlock(marker: string): string {
  const start = CSS.indexOf(marker)
  if (start < 0) return ''
  const open = CSS.indexOf('{', start)
  const close = CSS.indexOf('}', open)
  return open < 0 || close < 0 ? '' : CSS.slice(open + 1, close)
}

const backdrop = () => declarationBlock('.modal-backdrop, .score-sheet-backdrop')
const sheet = () => declarationBlock('\n.score-sheet {')

describe('现场问题 B：录分弹窗在手机 / 高缩放下必须完整可操作', () => {
  it('遮罩固定并自行可滚动，且阻止滚动链传到背景列表', () => {
    const rule = backdrop()
    expect(rule).toContain('position: fixed')
    expect(rule).toContain('inset: 0')
    expect(rule).toContain('overflow-y: auto')
    expect(rule).toContain('overscroll-behavior: contain')
    expect(rule).toContain('safe-area-inset-bottom')
  })

  it('不再使用会把超长内容顶部挤出可视区的 place-items: center 居中', () => {
    // 旧规则 `display: grid; place-items: center` 在内容高于 viewport 时上下同时溢出，
    // 而容器不可滚动 → 顶部与底部永久不可达。
    expect(backdrop()).not.toContain('place-items: center')
    // 安全居中：flex 顶部对齐 + 面板 auto 边距（有剩余空间时才吸收）
    expect(backdrop()).toContain('align-items: flex-start')
    expect(sheet()).toContain('margin: auto')
  })

  it('弹窗面板自身受 viewport 约束并可滚动（100dvh 优先，vh 兜底）', () => {
    const rule = sheet()
    expect(rule).toContain('box-sizing: border-box')
    expect(rule).toContain('max-height: calc(100vh - 40px)')
    expect(rule).toContain('max-height: calc(100dvh - 40px)')
    expect(rule).toContain('overflow-y: auto')
    expect(rule).toContain('overscroll-behavior: contain')
    // 宽度不再用 vw（高缩放 / 窄屏下会被 padding 撑出横向溢出）
    expect(rule).toContain('width: min(600px, 100%)')
    expect(rule).not.toContain('96vw')
  })

  it('同一套约束覆盖控制台的其它弹窗面板（避免只修一个弹窗）', () => {
    for (const marker of ['.console-assign-panel {', '.score-audit-panel {']) {
      const rule = declarationBlock(marker)
      expect(rule, marker).toContain('box-sizing: border-box')
      expect(rule, marker).toContain('margin: auto')
      expect(rule, marker).toContain('overflow: auto')
      expect(rule, marker).toContain('100dvh')
      expect(rule, marker).toContain('width: min(')
    }
  })

  it('标题、双方、全部字段与底部操作都在同一个弹窗 DOM 里且可操作', () => {
    const match: Match = {
      id: 88,
      tournament_id: 12,
      stage: 'GROUP',
      group_id: 3,
      round: 1,
      match_index: null,
      player_a_id: 10,
      player_b_id: 11,
      player_a_score: 2,
      player_b_score: 1,
      winner_id: 10,
      table_id: 2,
      status: 'FINISHED',
      prev_match_a_id: null,
      prev_match_b_id: null,
      entry_a_id: 10,
      entry_b_id: 11,
      entry_a_name: '甲方',
      entry_b_name: '乙方',
      result_type: 'NORMAL',
      result_note: null,
      bracket: 'MAIN',
      games: [],
    }

    const view = render(
      <MemoryRouter>
        <ScoreSheet
          match={match}
          sideA="甲方"
          sideB="乙方"
          gamesToWin={3}
          pointsToWin={11}
          busy={false}
          auditMode="revise"
          onClose={vi.fn()}
          onSave={vi.fn(async () => undefined)}
        />
      </MemoryRouter>,
    )

    // 弹窗是 viewport 层（fixed 遮罩 + 模态语义），不是页面文档流里的一块内容
    const dialog = screen.getByRole('dialog')
    expect(dialog.className).toContain('score-sheet-backdrop')
    expect(dialog.getAttribute('aria-modal')).toBe('true')

    const sheetEl = view.container.querySelector('.score-sheet') as HTMLElement
    // 弹窗面板必须包住全部字段与底部操作 —— 否则滚动可达性无从谈起
    for (const label of ['甲方大比分', '乙方大比分', '裁判备注', '操作人', '修改理由']) {
      expect(sheetEl.contains(screen.getByLabelText(label)), label).toBe(true)
    }
    expect(sheetEl.contains(screen.getByRole('button', { name: '取消' }))).toBe(true)
    expect(sheetEl.contains(screen.getByRole('button', { name: '检查并修改' }))).toBe(true)
    expect(sheetEl.contains(screen.getByRole('button', { name: '关闭' }))).toBe(true)
    // 底部操作容器也在面板内部（不能在面板滚动区之外）
    expect(sheetEl.contains(view.container.querySelector('.modal-actions') as HTMLElement)).toBe(true)

    // 取消 / 关闭必须始终可点（不能被 disabled 或覆盖层挡住而成为死路）
    expect((screen.getByRole('button', { name: '取消' }) as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole('button', { name: '关闭' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
