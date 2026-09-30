import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, Player, Registration, Tournament } from '../api'
import DrawPage from '../pages/DrawPage'
import PlayersPage, { RECOMMENDED_ROSTER_CSV } from '../pages/PlayersPage'

const baseTournament: Tournament = {
  id: 7, name: '校际乒乓赛', date: '2026-09-23', table_count: 4, group_count: 2,
  qualify_per_group: 2, stage: 'REGISTRATION', created_at: '', event_type: 'SINGLES',
  bronze_mode: 'JOINT_BRONZE', placement_mode: 'OFF', games_to_win: 2, points_to_win: 11,
  roster_confirmed: true, operation_mode: 'LIVE', registration_enabled: true,
  format_code: 'GROUP_KNOCKOUT', rule_config: {}, rule_version: 1,
}
const player: Player = { id: 1, tournament_id: 7, name: '张敏', college: null, rating_points: 1000, seed_no: null, group_id: null }

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks() })
afterEach(cleanup)

function prepareDraw(format: Tournament['format_code']) {
  vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, format_code: format })
  vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
  vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [] })
  return render(<MemoryRouter initialEntries={['/draw?tid=7']}><DrawPage /></MemoryRouter>)
}

describe('抽签与编排按 format 呈现真实能力', () => {
  it('GROUP_KNOCKOUT 展示种子、分组和真实小组赛生成入口', async () => {
    prepareDraw('GROUP_KNOCKOUT')
    expect(await screen.findByRole('heading', { name: '种子设置' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '小组抽签结果' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '生成分组' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /开始小组抽签/ })).toBeNull()
    expect(screen.getByText(/Draw Revision 契约/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '生成小组比赛' })).toBeTruthy()
  })

  it('GROUP_KNOCKOUT 只读展示后端 qualify_count，不再在抽签页编辑', async () => {
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, format_code: 'GROUP_KNOCKOUT' })
    vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
    vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [{
      id: 31, name: 'A组', sort_order: 0, qualify_count: 2,
      players: [{ id: 1, name: '张敏', college: null }], entries: [],
    }] })
    render(<MemoryRouter initialEntries={['/draw?tid=7']}><DrawPage /></MemoryRouter>)
    expect(await screen.findByText('晋级：前 2 名')).toBeTruthy()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByRole('button', { name: '重新生成分组' })).toBeTruthy()
    expect(screen.queryByText(/正式重新抽签已记录/)).toBeNull()
  })

  it('ROUND_ROBIN 不展示种子或小组晋级，并明确等待正式接口', async () => {
    prepareDraw('ROUND_ROBIN')
    expect(await screen.findByRole('heading', { name: '单循环编排' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '种子设置' })).toBeNull()
    expect(screen.queryByText('每组晋级')).toBeNull()
    expect(screen.getByText(/等待单循环生成接口/)).toBeTruthy()
  })

  it('SINGLE_ELIMINATION 允许保存种子，但不伪造淘汰签生成成功', async () => {
    prepareDraw('SINGLE_ELIMINATION')
    expect(await screen.findByRole('heading', { name: '种子设置' })).toBeTruthy()
    expect(screen.getByText(/正式单淘汰种子落位规则等待后端契约/)).toBeTruthy()
    expect(screen.queryByText(/ITTF.*已落地/)).toBeNull()
    expect(screen.getByText('等待 · 淘汰签生成')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /生成淘汰/ })).toBeNull()
  })

  it('DOUBLES 不展示会写错实体的 Player 种子编辑器', async () => {
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, event_type: 'DOUBLES', format_code: 'GROUP_KNOCKOUT' })
    vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
    vi.spyOn(api, 'getGroups').mockResolvedValue({ groups: [] })
    render(<MemoryRouter initialEntries={['/draw?tid=7']}><DrawPage /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: '当前项目暂不提供种子编辑' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '种子设置' })).toBeNull()
    expect(screen.queryByText('种子顺序已保存。')).toBeNull()
  })

  it('历史赛事 format 为空时不默认成小组赛', async () => {
    prepareDraw(null)
    expect(await screen.findByRole('heading', { name: '请先保存赛事赛制' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '小组抽签结果' })).toBeNull()
  })
})

describe('参赛名单与待确认报名', () => {
  it('确认 PENDING 报名后调用后端确认接口，不创建本地候选状态', async () => {
    const registration: Registration = {
      id: 19, tournament_id: 7, name: '李华', affiliation: '青鸟俱乐部', contact: '13800000000',
      rating_points: 1200, status: 'PENDING', confirmed_player_id: null, confirmed_by_user_id: null,
      confirmed_at: null, created_at: '2026-09-23T08:00:00Z', updated_at: '2026-09-23T08:00:00Z',
    }
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, roster_confirmed: false })
    vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
    vi.spyOn(api, 'listRegistrations').mockResolvedValue([registration])
    vi.spyOn(api, 'listEntries').mockResolvedValue([])
    const confirm = vi.spyOn(api, 'confirmRegistration').mockResolvedValue({ registration: { ...registration, status: 'CONFIRMED', confirmed_player_id: 2 }, player: { ...player, id: 2, name: '李华', college: '青鸟俱乐部', rating_points: 1200 } })
    render(<MemoryRouter initialEntries={['/players?tid=7']}><PlayersPage /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('tab', { name: /待确认报名/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认并加入名单' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(7, 19))
  })

  it('正式名单将缺失 college 标为未填写，且没有种子和分组列', async () => {
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, roster_confirmed: false })
    vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
    vi.spyOn(api, 'listRegistrations').mockResolvedValue([])
    vi.spyOn(api, 'listEntries').mockResolvedValue([])
    render(<MemoryRouter initialEntries={['/players?tid=7']}><PlayersPage /></MemoryRouter>)
    expect(await screen.findByText('未填写')).toBeTruthy()
    expect(screen.queryByRole('columnheader', { name: '种子' })).toBeNull()
    expect(screen.queryByRole('columnheader', { name: '分组' })).toBeNull()
  })

  it('所属单位作为推荐抽签信息，CSV 只将积分留空', async () => {
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, roster_confirmed: false })
    vi.spyOn(api, 'listPlayers').mockResolvedValue([])
    vi.spyOn(api, 'listRegistrations').mockResolvedValue([])
    vi.spyOn(api, 'listEntries').mockResolvedValue([])
    render(<MemoryRouter initialEntries={['/players?tid=7']}><PlayersPage /></MemoryRouter>)
    const affiliation = await screen.findByLabelText('所属单位')
    expect(affiliation.getAttribute('placeholder')).toBe('所属单位')
    expect(screen.getByText(/用于同单位抽签规避/)).toBeTruthy()
    expect(RECOMMENDED_ROSTER_CSV).toContain('李四,自动化学院,\n')
    expect(RECOMMENDED_ROSTER_CSV).not.toContain('李四,,')
    const rating = screen.getByLabelText('运动员积分') as HTMLInputElement
    expect(rating.value).toBe('1000')
    expect(rating.required).toBe(true)
    expect(screen.getByText(/手工录入的运动员积分默认填写 1000；CSV 导入时积分可留空/)).toBeTruthy()
  })

  it('名单确认后冻结 CRUD、报名确认和重复确认', async () => {
    const pending: Registration = {
      id: 20, tournament_id: 7, name: '王强', affiliation: null, contact: null, rating_points: 1000,
      status: 'PENDING', confirmed_player_id: null, confirmed_by_user_id: null, confirmed_at: null,
      created_at: '2026-09-23T08:00:00Z', updated_at: '2026-09-23T08:00:00Z',
    }
    vi.spyOn(api, 'getTournament').mockResolvedValue({ ...baseTournament, roster_confirmed: true })
    vi.spyOn(api, 'listPlayers').mockResolvedValue([player])
    vi.spyOn(api, 'listRegistrations').mockResolvedValue([pending])
    vi.spyOn(api, 'listEntries').mockResolvedValue([])
    render(<MemoryRouter initialEntries={['/players?tid=7']}><PlayersPage /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: '参赛名单已确认' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '确认参赛名单' })).toBeNull()
    expect((screen.getByRole('button', { name: '修改' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '删除' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('tab', { name: /待确认报名/ }))
    expect((screen.getByRole('button', { name: '确认并加入名单' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
