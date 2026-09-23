import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, Tournament } from '../api'
import AdminLayout from '../layouts/AdminLayout'
import TournamentSettingsPage from '../pages/TournamentSettingsPage'

const tournament: Tournament = {
  id: 12, name: '秋季乒乓赛', date: '2026-09-22', table_count: 8, group_count: 4,
  qualify_per_group: 2, stage: 'REGISTRATION', created_at: '2026-09-22T09:00:00Z',
  event_type: 'SINGLES', bronze_mode: 'BRONZE_MATCH', placement_mode: 'TIERED',
  games_to_win: 3, points_to_win: 11, roster_confirmed: false, operation_mode: 'LIVE',
  registration_enabled: false, format_code: 'GROUP_KNOCKOUT', rule_config: {}, rule_version: 1,
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('赛事设置真实契约', () => {
  it('展示三张赛制卡，并按赛制隐藏不适用字段', () => {
    render(<TournamentSettingsPage tournament={tournament} />)
    expect(screen.getByRole('button', { name: /小组赛 \+ 淘汰赛/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /全体循环赛/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /单淘汰/ })).toBeTruthy()
    expect(screen.getByText('小组数量')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /全体循环赛/ }))
    expect(screen.queryByText('小组数量')).toBeNull()
    expect(screen.getByText('排名范围')).toBeTruthy()
  })

  it('format 实际变化时先二次确认，再调用真实接口', async () => {
    const update = vi.spyOn(api, 'updateTournamentFormat').mockResolvedValue({ ...tournament, format_code: 'ROUND_ROBIN' })
    render(<TournamentSettingsPage tournament={tournament} />)
    fireEvent.click(screen.getByRole('button', { name: /全体循环赛/ }))
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    expect(screen.getByRole('dialog', { name: '确认切换赛制' })).toBeTruthy()
    expect(within(screen.getByRole('dialog', { name: '确认切换赛制' })).getByText('小组赛 + 淘汰赛')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认并保存' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith(12, { format_code: 'ROUND_ROBIN', rule_config: {} }))
  })

  it('registration_enabled 只在显式保存后写入', async () => {
    const update = vi.spyOn(api, 'updateTournamentRegistration').mockResolvedValue({ ...tournament, registration_enabled: true })
    render(<TournamentSettingsPage tournament={tournament} />)
    fireEvent.click(screen.getByRole('tab', { name: '报名设置' }))
    fireEvent.click(screen.getByRole('checkbox'))
    expect(update).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '保存报名设置' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith(12, true))
  })

  it('TEAM 赛事不展示后端必然拒绝的个人赛 format 控件', () => {
    render(<TournamentSettingsPage tournament={{ ...tournament, event_type: 'TEAM', format_code: null }} />)
    expect(screen.getByRole('heading', { name: '团体赛使用独立赛制流程' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /小组赛 \+ 淘汰赛/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '保存设置' })).toBeNull()
  })

  it('organization 与 venue 分别调用 generated-contract wrapper 保存', async () => {
    const saveOrg = vi.spyOn(api, 'upsertOrganization').mockResolvedValue({ id: 1, tournament_id: 12, name: '组委会', contact_name: null, contact: null, note: null, created_at: '', updated_at: '' })
    const saveVenue = vi.spyOn(api, 'upsertVenue').mockResolvedValue({ id: 1, tournament_id: 12, name: '体育馆', address: null, contact_name: null, contact: null, note: null, created_at: '', updated_at: '' })
    render(<TournamentSettingsPage tournament={tournament} />)
    fireEvent.click(screen.getByRole('tab', { name: '基本信息' }))
    const org = screen.getByRole('heading', { name: '组织方' }).closest('section')!
    const venue = screen.getByRole('heading', { name: '比赛场馆' }).closest('section')!
    fireEvent.change(within(org).getByLabelText('组织方名称'), { target: { value: '组委会' } })
    fireEvent.click(within(org).getByRole('button', { name: '保存组织方' }))
    await waitFor(() => expect(saveOrg).toHaveBeenCalled())
    fireEvent.change(within(venue).getByLabelText('场馆名称'), { target: { value: '体育馆' } })
    await waitFor(() => expect((within(venue).getByRole('button', { name: '保存比赛场馆' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(within(venue).getByRole('button', { name: '保存比赛场馆' }))
    await waitFor(() => expect(saveVenue).toHaveBeenCalled())
  })

  it('高级操作使用真实 export，并要求 LIVE 完整名称才能删除', async () => {
    vi.spyOn(api, 'exportTournament').mockResolvedValue({} as Awaited<ReturnType<typeof api.exportTournament>>)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:test') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    render(<TournamentSettingsPage tournament={tournament} />)
    fireEvent.click(screen.getByRole('tab', { name: '高级操作' }))
    fireEvent.click(screen.getByRole('button', { name: '导出 JSON' }))
    await waitFor(() => expect(click).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: '删除赛事' }))
    const dialog = screen.getByRole('dialog', { name: '确认删除赛事' })
    const destructive = within(dialog).getByRole('button', { name: '永久删除' }) as HTMLButtonElement
    expect(destructive.disabled).toBe(true)
    fireEvent.change(within(dialog).getByLabelText('输入完整赛事名称'), { target: { value: tournament.name } })
    expect(destructive.disabled).toBe(false)
  })
})

describe('管理端 Public 入口', () => {
  it('选中赛事时打开对应 Public live 路由', () => {
    render(<MemoryRouter initialEntries={['/settings?tid=12']}><AdminLayout><div /></AdminLayout></MemoryRouter>)
    const link = screen.getByRole('link', { name: '打开 Public 页面' }) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/public/t/12/live')
  })
})
