import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { Tournament } from '../api'
import AdminLayout from '../layouts/AdminLayout'
import TournamentSettingsPage from '../pages/TournamentSettingsPage'

const tournament: Tournament = {
  id: 12,
  name: '秋季乒乓赛',
  date: '2026-09-22',
  table_count: 8,
  group_count: 4,
  qualify_per_group: 2,
  stage: 'REGISTRATION',
  created_at: '2026-09-22T09:00:00Z',
  event_type: 'SINGLES',
  bronze_mode: 'BRONZE_MATCH',
  placement_mode: 'TIERED',
  games_to_win: 3,
  points_to_win: 11,
  roster_confirmed: false,
  operation_mode: 'LIVE',
  registration_enabled: false,
}

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('赛事设置骨架', () => {
  it('按生成的赛事契约展示真实规则，并将尚无契约的设置保持只读', () => {
    render(<TournamentSettingsPage tournament={tournament} />)

    expect(screen.getAllByRole('tab')).toHaveLength(5)
    expect(screen.getByRole('tab', { name: '赛制与规则' }).getAttribute('aria-selected')).toBe('true')
    for (const value of ['单打', '4 组', '先胜 3 局', '11 分', '前 2 名', '举行季军赛', '分层名次赛', '等待赛制接口']) {
      expect(screen.getByText(value)).toBeTruthy()
    }
    expect((screen.getByRole('button', { name: '保存设置' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '取消修改' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('没有赛事数据时不伪造规则；未接入的分类明确标注待接入', () => {
    render(<TournamentSettingsPage />)
    expect(screen.getAllByText('等待赛事数据').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('tab', { name: '报名设置' }))
    expect(screen.getByText(/等待对应的后端数据与权限契约后接入/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '保存设置' })).toBeNull()
  })
})

describe('管理端 Public 入口', () => {
  it('选中赛事时以新标签打开对应 Public live 路由', () => {
    render(<MemoryRouter initialEntries={['/settings?tid=12']}><AdminLayout><div /></AdminLayout></MemoryRouter>)
    const link = screen.getByRole('link', { name: '打开 Public 页面' }) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/public/t/12/live')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noreferrer')
  })

  it('未选中赛事时不生成 Public 链接', () => {
    render(<MemoryRouter initialEntries={['/settings']}><AdminLayout><div /></AdminLayout></MemoryRouter>)
    expect(screen.queryByRole('link', { name: '打开 Public 页面' })).toBeNull()
    expect(screen.getByText('打开 Public 页面').getAttribute('aria-disabled')).toBe('true')
  })
})
