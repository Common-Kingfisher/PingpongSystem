/**
 * `publicFormat.ts` 纯函数单测（D 轨 Day4D 接线轮，PR #50 review）。
 *
 * 这是 Public 端「赛制 → 展示能力」的唯一映射，因此必须被精确钉住：
 * 一旦有人在这里偷偷加入排名 / BYE / 抽签 / 完赛状态之类的**业务计算**，
 * 或者把 legacy(null) 默认成 GROUP_KNOCKOUT，本文件就应该失败。
 *
 * ⚠️ 期望值全部来自 generated contract 的三个取值
 * （ROUND_ROBIN / SINGLE_ELIMINATION / GROUP_KNOCKOUT）+ null，不新建第二套 enum。
 */

/// <reference types="vitest/globals" />
import { describe, expect, it } from 'vitest'
import {
  getPublicCapabilities,
  getPublicStageLabel,
  getRankingsTitle,
  isRoundRobin,
  isSingleElimination,
} from '../publicFormat'

describe('getPublicCapabilities：赛制 → Public 模块可见性', () => {
  it('ROUND_ROBIN：有排名，没有签表、没有冠军', () => {
    expect(getPublicCapabilities('ROUND_ROBIN')).toEqual({
      showRankings: true,
      showBracket: false,
      showChampion: false,
    })
  })

  it('SINGLE_ELIMINATION：有签表与冠军，没有循环赛排名', () => {
    expect(getPublicCapabilities('SINGLE_ELIMINATION')).toEqual({
      showRankings: false,
      showBracket: true,
      showChampion: true,
    })
  })

  it('GROUP_KNOCKOUT：三者全开', () => {
    expect(getPublicCapabilities('GROUP_KNOCKOUT')).toEqual({
      showRankings: true,
      showBracket: true,
      showChampion: true,
    })
  })

  it('null / undefined（legacy 历史赛事）：全部可见，且不默认成 GROUP_KNOCKOUT', () => {
    for (const value of [null, undefined]) {
      expect(getPublicCapabilities(value)).toEqual({
        showRankings: true,
        showBracket: true,
        showChampion: true,
      })
    }
    // 反向断言：legacy 与 GROUP_KNOCKOUT 的能力相同，但这不代表“被识别成 GK”，
    // 而是“不做推断、保持既有可见性”。识别只允许来自 format_code 本身。
    expect(isRoundRobin(null)).toBe(false)
    expect(isSingleElimination(null)).toBe(false)
  })

  it('helper 只返回三个 UI 开关，不夹带任何业务结果', () => {
    for (const value of ['ROUND_ROBIN', 'SINGLE_ELIMINATION', 'GROUP_KNOCKOUT', null] as const) {
      expect(Object.keys(getPublicCapabilities(value)).sort()).toEqual([
        'showBracket',
        'showChampion',
        'showRankings',
      ])
    }
  })
})

describe('getRankingsTitle：排名页标题', () => {
  it('只有明确 GROUP_KNOCKOUT 才叫小组排名', () => {
    expect(getRankingsTitle('GROUP_KNOCKOUT')).toBe('小组排名')
  })

  it('循环赛与 legacy(null) 都用中性的「赛事排名」', () => {
    expect(getRankingsTitle('ROUND_ROBIN')).toBe('赛事排名')
    expect(getRankingsTitle(null)).toBe('赛事排名')
    expect(getRankingsTitle(undefined)).toBe('赛事排名')
  })
})

describe('getPublicStageLabel：阶段文案（纯展示，不做状态机）', () => {
  it('报名中 / 已结束 与赛制无关', () => {
    for (const format of ['ROUND_ROBIN', 'SINGLE_ELIMINATION', 'GROUP_KNOCKOUT', null] as const) {
      expect(getPublicStageLabel(format, 'REGISTRATION')).toBe('报名中')
      expect(getPublicStageLabel(format, 'FINISHED')).toBe('已结束')
    }
  })

  it('循环赛不会显示成「小组赛」', () => {
    expect(getPublicStageLabel('ROUND_ROBIN', 'GROUP_STAGE')).toBe('循环赛')
    expect(getPublicStageLabel('ROUND_ROBIN', 'KNOCKOUT')).toBe('循环赛')
  })

  it('单淘汰不会显示成「淘汰赛」以外的阶段名', () => {
    expect(getPublicStageLabel('SINGLE_ELIMINATION', 'KNOCKOUT')).toBe('单淘汰')
    expect(getPublicStageLabel('SINGLE_ELIMINATION', 'GROUP_STAGE')).toBe('单淘汰')
  })

  it('GROUP_KNOCKOUT 与 legacy(null) 保持既有文案', () => {
    for (const format of ['GROUP_KNOCKOUT', null] as const) {
      expect(getPublicStageLabel(format, 'GROUP_STAGE')).toBe('小组赛')
      expect(getPublicStageLabel(format, 'KNOCKOUT')).toBe('淘汰赛')
    }
  })

  it('没有 stage 时返回空串（不猜阶段）', () => {
    expect(getPublicStageLabel('ROUND_ROBIN', null)).toBe('')
    expect(getPublicStageLabel('ROUND_ROBIN', undefined)).toBe('')
  })
})
