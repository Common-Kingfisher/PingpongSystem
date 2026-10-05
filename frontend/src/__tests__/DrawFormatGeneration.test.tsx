/**
 * V0.3 三赛制生成链路（C 轨接线）回归。
 *
 * 本文件锁定的是**产品入口**，不是比赛算法：
 *
 * - `ROUND_ROBIN` / `SINGLE_ELIMINATION` 不再显示"等待接口"，而是调用真实
 *   `api.generateMatches(tid)`（`POST /api/tournaments/{tid}/generate-matches`）；
 * - 两个赛制都**不得**改调 `generateGroupMatches` / `generateKnockout`
 *   （单淘汰不是小组淘汰的第二阶段，循环赛没有淘汰阶段）；
 * - `GROUP_KNOCKOUT` 的"生成分组 / 生成小组比赛"主链不因本轮接线而退化；
 * - 前端只做明显的 UX guard（busy / stage / roster_confirmed），
 *   参赛位数量、重复生成与合法性仍以服务端为准。
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, GroupingResult, Player, Tournament } from '../api'
import DrawPage from '../pages/DrawPage'

function tournament(overrides: Partial<Tournament> = {}): Tournament {
  return {
    id: 7, name: '校际乒乓赛', date: '2026-09-23', table_count: 4, group_count: 2,
    qualify_per_group: 2, stage: 'REGISTRATION', created_at: '', event_type: 'SINGLES',
    bronze_mode: 'JOINT_BRONZE', placement_mode: 'OFF', games_to_win: 2, points_to_win: 11,
    roster_confirmed: true, operation_mode: 'LIVE', registration_enabled: false,
    format_code: 'ROUND_ROBIN', rule_config: {}, rule_version: 1,
    ...overrides,
  }
}

function generationResult(current: Tournament, matches: number, perGroup: Record<string, number> = {}) {
  return { matches_generated: matches, per_group: perGroup, tournament: current }
}

const player: Player = {
  id: 1, tournament_id: 7, name: '张敏', college: null,
  rating_points: 1000, seed_no: null, group_id: null,
}

const oneGroup: GroupingResult = {
  groups: [{ id: 31, name: 'A组', sort_order: 0, qualify_count: 2, players: [], entries: [] }],
}

function prepare(current: Tournament, groups: GroupingResult = { groups: [] }) {
  vi.spyOn(api, 'getTournament').mockResolvedValue(current)
  vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
  vi.spyOn(api, 'getGroups').mockResolvedValue(groups)
  return render(<MemoryRouter initialEntries={['/draw?tid=7']}><DrawPage /></MemoryRouter>)
}

/** 把"绝不应该被本赛制调用"的两个旧入口变成显式失败，而不是静默 undefined。 */
function forbidLegacyEndpoints() {
  return {
    groupMatches: vi
      .spyOn(api, 'generateGroupMatches')
      .mockRejectedValue(new ApiError(500, 'legacy 小组入口不应被本赛制调用')),
    knockout: vi
      .spyOn(api, 'generateKnockout')
      .mockRejectedValue(new ApiError(500, 'generate-knockout 不应被本赛制调用')),
  }
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('DrawPage — ROUND_ROBIN 使用真实的赛制生成入口', () => {
  it('不再显示"等待单循环生成接口"，改为真实生成入口', async () => {
    prepare(tournament({ format_code: 'ROUND_ROBIN' }))

    expect(await screen.findByRole('heading', { name: '生成循环赛' })).toBeTruthy()
    expect(screen.queryByText(/等待单循环生成接口/)).toBeNull()
    expect(screen.queryByText(/等待 · /)).toBeNull()
    // 循环赛没有淘汰与小组出线语义
    expect(screen.queryByRole('button', { name: /生成淘汰/ })).toBeNull()
    expect(screen.queryByText(/小组出线|小组晋级|小组赛/)).toBeNull()
  })

  it('点击后只调用一次 api.generateMatches(tid)，并展示真实生成场数', async () => {
    const current = tournament({ format_code: 'ROUND_ROBIN' })
    prepare(current)
    const legacy = forbidLegacyEndpoints()
    const generate = vi
      .spyOn(api, 'generateMatches')
      .mockResolvedValue(generationResult({ ...current, stage: 'GROUP_STAGE' }, 15))

    fireEvent.click(await screen.findByRole('button', { name: '生成循环赛' }))

    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1))
    expect(generate).toHaveBeenCalledWith(7)
    expect(legacy.groupMatches).not.toHaveBeenCalled()
    expect(legacy.knockout).not.toHaveBeenCalled()
    expect(await screen.findByText('已生成 15 场循环赛。')).toBeTruthy()
  })

  it('后端拒绝时展示服务端 detail，不伪造成功', async () => {
    prepare(tournament({ format_code: 'ROUND_ROBIN' }))
    vi.spyOn(api, 'generateMatches').mockRejectedValue(
      new ApiError(409, '循环赛已生成，不能重复生成'),
    )

    fireEvent.click(await screen.findByRole('button', { name: '生成循环赛' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('循环赛已生成，不能重复生成')
    expect(screen.queryByText(/已生成 \d+ 场循环赛。/)).toBeNull()
  })
})

describe('DrawPage — SINGLE_ELIMINATION 使用真实的赛制生成入口', () => {
  it('不再显示"首轮淘汰签仍等待"，改为真实生成入口', async () => {
    prepare(tournament({ format_code: 'SINGLE_ELIMINATION' }))

    expect(await screen.findByRole('heading', { name: '单败淘汰签' })).toBeTruthy()
    expect(screen.queryByText(/首轮淘汰签仍等待/)).toBeNull()
    expect(screen.getByRole('button', { name: '生成单淘汰签' })).toBeTruthy()
    // 单淘汰不是小组淘汰的第二阶段
    expect(screen.queryByRole('button', { name: /生成淘汰赛/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /生成分组|生成小组比赛/ })).toBeNull()
  })

  it('保留单打种子编辑，并只调用一次 api.generateMatches(tid)', async () => {
    const current = tournament({ format_code: 'SINGLE_ELIMINATION' })
    prepare(current)
    expect(await screen.findByRole('heading', { name: '种子设置' })).toBeTruthy()

    const legacy = forbidLegacyEndpoints()
    const generate = vi
      .spyOn(api, 'generateMatches')
      .mockResolvedValue(generationResult({ ...current, stage: 'KNOCKOUT' }, 7))

    fireEvent.click(screen.getByRole('button', { name: '生成单淘汰签' }))

    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1))
    expect(generate).toHaveBeenCalledWith(7)
    expect(legacy.knockout).not.toHaveBeenCalled()
    expect(legacy.groupMatches).not.toHaveBeenCalled()
    expect(await screen.findByText('已生成 7 场淘汰赛。')).toBeTruthy()
  })
})

describe('DrawPage — 生成前的 UX guard（最终合法性仍以后端为准）', () => {
  it('ROUND_ROBIN：名单未确认时禁用生成并提示', async () => {
    prepare(tournament({ format_code: 'ROUND_ROBIN', roster_confirmed: false }))

    const button = (await screen.findByRole('button', { name: '生成循环赛' })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByText('请先确认正式名单。')).toBeTruthy()
    expect(screen.getByText('等待名单确认')).toBeTruthy()
  })

  it('SINGLE_ELIMINATION：名单未确认时禁用生成并提示', async () => {
    prepare(tournament({ format_code: 'SINGLE_ELIMINATION', roster_confirmed: false }))

    const button = (await screen.findByRole('button', { name: '生成单淘汰签' })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByText('请先确认正式名单。')).toBeTruthy()
  })

  it('ROUND_ROBIN：已生成（stage != REGISTRATION）后不提供可重复生成入口', async () => {
    prepare(tournament({ format_code: 'ROUND_ROBIN', stage: 'GROUP_STAGE' }))

    const button = (await screen.findByRole('button', { name: '生成循环赛' })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByText('当前阶段不允许再次生成比赛。')).toBeTruthy()
    expect(screen.getByText('当前阶段不可生成')).toBeTruthy()
  })

  it('SINGLE_ELIMINATION：进入 KNOCKOUT 后不提供可重复生成入口', async () => {
    prepare(tournament({ format_code: 'SINGLE_ELIMINATION', stage: 'KNOCKOUT' }))

    const button = (await screen.findByRole('button', { name: '生成单淘汰签' })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByText('当前阶段不允许再次生成比赛。')).toBeTruthy()
  })
})

describe('DrawPage — GROUP_KNOCKOUT 主链不退化', () => {
  it('仍提供"生成分组 / 生成小组比赛"，且小组比赛走 legacy 端点', async () => {
    const current = tournament({ format_code: 'GROUP_KNOCKOUT' })
    prepare(current, oneGroup)
    const generate = vi
      .spyOn(api, 'generateMatches')
      .mockResolvedValue(generationResult(current, 6, { A组: 6 }))
    const groupMatches = vi
      .spyOn(api, 'generateGroupMatches')
      .mockResolvedValue(generationResult({ ...current, stage: 'GROUP_STAGE' }, 6, { A组: 6 }))

    expect(await screen.findByRole('button', { name: '重新生成分组' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '生成小组比赛' }))

    await waitFor(() => expect(groupMatches).toHaveBeenCalledWith(7))
    expect(generate).not.toHaveBeenCalled()
    expect(await screen.findByText('已生成 6 场小组比赛。')).toBeTruthy()
  })

  it('未确认名单时仍保留既有的分组禁用与提示', async () => {
    prepare(tournament({ format_code: 'GROUP_KNOCKOUT', roster_confirmed: false }), oneGroup)

    const autoGroup = (await screen.findByRole('button', { name: '重新生成分组' })) as HTMLButtonElement
    expect(autoGroup.disabled).toBe(true)
    expect(screen.getByText('请先在“参赛名单”确认正式名单。')).toBeTruthy()
    // 未分组时小组比赛入口仍被禁用
    expect((screen.getByRole('button', { name: '生成小组比赛' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
