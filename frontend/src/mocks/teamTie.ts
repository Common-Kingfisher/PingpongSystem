import { TeamPermission, TeamRubberView, TeamTieView } from '../team/types'

const disabled: TeamPermission = {
  can_edit_lineup: false, can_confirm_lineup: false, can_start: false, can_record_score: false, can_revise_score: false,
}
const editable: TeamPermission = { ...disabled, can_edit_lineup: true, can_confirm_lineup: true }
const editableButUnconfirmed: TeamPermission = { ...disabled, can_edit_lineup: true }
const playing: TeamPermission = { ...disabled, can_record_score: true }

const options = [
  { player_id: 101, name: '陈晨', available: true, unavailable_reason: null },
  { player_id: 102, name: '林涛', available: true, unavailable_reason: null },
  { player_id: 103, name: '周宁', available: false, unavailable_reason: '该队员当前不可出场' },
]

const rubber = (id: number, sequence: number, rubber_type: TeamRubberView['rubber_type'], status: TeamRubberView['status'], permissions = disabled): TeamRubberView => ({
  id,
  sequence,
  rubber_type,
  status,
  home_slots: ['主队出场阵容'],
  away_slots: ['客队出场阵容'],
  home_players: status === 'PENDING' ? [] : ['陈晨'],
  away_players: status === 'PENDING' ? [] : ['孙越'],
  home_score: status === 'FINISHED' ? 2 : null,
  away_score: status === 'FINISHED' ? 1 : null,
  winner_side: status === 'FINISHED' ? 'HOME' : null,
  permissions,
  lineup_options: options,
})

const base = (status: TeamTieView['status']): TeamTieView => ({
  id: 9001,
  tournament_id: 88,
  stage: 'GROUP',
  status,
  home_team: { entry_id: 11, display_name: '星河队', status: 'ACTIVE', members: ['陈晨', '林涛', '周宁'] },
  away_team: { entry_id: 12, display_name: '先锋队', status: 'ACTIVE', members: ['孙越', '何川', '吴然'] },
  home_score: 0,
  away_score: 0,
  target_wins: null,
  format: { code: null, version: null, display_name: '等待赛制冻结' },
  rubbers: [],
  winner_entry_id: null,
  permissions: disabled,
})

export const teamTieWaitingMock: TeamTieView = {
  ...base('WAITING'),
  rubbers: [rubber(1, 1, 'DOUBLES', 'READY', editableButUnconfirmed), rubber(2, 2, 'SINGLES', 'PENDING'), rubber(3, 3, 'SINGLES', 'PENDING')],
}

export const teamTiePlayingMock: TeamTieView = {
  ...base('PLAYING'),
  home_score: 1,
  rubbers: [rubber(1, 1, 'DOUBLES', 'FINISHED'), rubber(2, 2, 'SINGLES', 'PLAYING', playing), rubber(3, 3, 'SINGLES', 'READY', editable)],
}

export const teamTieFinishedMock: TeamTieView = {
  ...base('FINISHED'),
  home_score: 2,
  away_score: 1,
  winner_entry_id: 11,
  rubbers: [rubber(1, 1, 'DOUBLES', 'FINISHED'), rubber(2, 2, 'SINGLES', 'FINISHED'), rubber(3, 3, 'SINGLES', 'FINISHED')],
}

export const teamTieWithSkippedRubbersMock: TeamTieView = {
  ...teamTieFinishedMock,
  rubbers: [...teamTieFinishedMock.rubbers, rubber(4, 4, 'DOUBLES', 'SKIPPED'), rubber(5, 5, 'SINGLES', 'SKIPPED')],
}

export const teamTieMocks = {
  waiting: teamTieWaitingMock,
  playing: teamTiePlayingMock,
  finished: teamTieFinishedMock,
  skipped: teamTieWithSkippedRubbersMock,
}
