/**
 * D 轨 Day5D · PR #58 reviewer P1 收口：**真实 App 路由级**验收（最小用例）。
 *
 * ## 这条测试要证明的唯一事情
 *
 * 原 reviewer P1 是「EVENT_ADMIN 无法从真实产品进入报名设置，只能手工调 API」。
 * 现在管理端报名开关由 master / C 轨提供（PR #61 的 `/settings` route，
 * TEAM 不变量由 PR #63 收口），因此这里用**真实 `App`** 走一遍：
 *
 * ```text
 * App
 *   → /settings?tid=12（AdminShell → AdminLayout → TournamentSettingsPage）
 *   → 「报名设置」
 *   → 勾选报名
 *   → 「保存报名设置」
 *   → api.updateTournamentRegistration(12, true)
 * ```
 *
 * ## 为什么只有这一条、且不放进 master 的测试文件
 *
 * `TournamentSettingsPage` 的组件级行为已由 master / C 轨的
 * `__tests__/TournamentSettingsPage.test.tsx` 覆盖，D 轨不复制也不改写它
 * （PR #58 的最终 diff 不得包含 C 轨文件）。本文件只补「路由可达」这一层。
 *
 * ## 与 D 轨 Public 的关系
 *
 * 本测试只驱动管理端入口；Public 侧仍由 `PublicRegistrationFlow.test.tsx` /
 * `PublicRegistrationPolicy.test.ts` 覆盖（同一 `TournamentOut.registration_enabled` 事实源）。
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { api } from '../api'
import type { Tournament } from '../api'
import { setActiveTournamentId } from '../activeTournament'

const TID = 12

const tournament: Tournament = {
  id: TID, name: '秋季乒乓赛', date: '2026-09-22', table_count: 8, group_count: 4,
  qualify_per_group: 2, stage: 'REGISTRATION', created_at: '2026-09-22T09:00:00Z',
  event_type: 'SINGLES', bronze_mode: 'BRONZE_MATCH', placement_mode: 'TIERED',
  games_to_win: 3, points_to_win: 11, roster_confirmed: false, operation_mode: 'LIVE',
  registration_enabled: false, format_code: 'GROUP_KNOCKOUT', rule_config: {}, rule_version: 1,
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  // AdminShell 与 TournamentSettingsPage 都会解析 tid：前者读 ?tid=，后者在无 prop 时
  // 读 window.location.search（jsdom 下由 MemoryRouter 改为读 localStorage 兜底）。
  // 两者指向同一个赛事，保证断言落在真实的 /settings 路由上。
  setActiveTournamentId(TID)
})

afterEach(cleanup)

describe('管理端 /settings 路由的报名开关入口', () => {
  it('真实 App 经 /settings?tid=12 进入报名设置，保存时调用正式 updateTournamentRegistration', async () => {
    const getTournament = vi.spyOn(api, 'getTournament').mockResolvedValue(tournament)
    vi.spyOn(api, 'getOrganization').mockResolvedValue({
      id: 1, tournament_id: TID, name: '组委会', contact_name: null, contact: null, note: null, created_at: '', updated_at: '',
    })
    vi.spyOn(api, 'getVenue').mockResolvedValue({
      id: 1, tournament_id: TID, name: '体育馆', address: null, contact_name: null, contact: null, note: null, created_at: '', updated_at: '',
    })
    const update = vi.spyOn(api, 'updateTournamentRegistration').mockResolvedValue({
      ...tournament, registration_enabled: true,
    })

    render(
      <MemoryRouter initialEntries={[`/settings?tid=${TID}`]}>
        <App />
      </MemoryRouter>,
    )

    // 路由确实渲染了赛事设置页（而不是空白 / 其它页面），且 AdminShell 用 ?tid= 解析了赛事
    expect(await screen.findByRole('heading', { name: '赛事设置' })).toBeTruthy()
    expect(getTournament).toHaveBeenCalledWith(TID)

    fireEvent.click(await screen.findByRole('tab', { name: '报名设置' }))
    const toggle = (await screen.findByRole('checkbox')) as HTMLInputElement
    expect(toggle.disabled).toBe(false)
    expect(toggle.checked).toBe(false)

    fireEvent.click(toggle)
    expect(update).not.toHaveBeenCalled()          // 只在显式保存后写入
    fireEvent.click(screen.getByRole('button', { name: '保存报名设置' }))

    await waitFor(() => expect(update).toHaveBeenCalledWith(TID, true))
    expect(update).toHaveBeenCalledTimes(1)
    // UI 刷新到服务端返回的有效状态
    await screen.findByText(/线上报名已开启/)
  })
})
