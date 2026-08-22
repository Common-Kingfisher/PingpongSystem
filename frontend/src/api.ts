/**
 * 后端 API 类型定义与 fetch 封装。
 * 类型与后端 Enum code 一一对应（backend/app/models.py）。
 */

export type MatchStatus = 'WAITING' | 'PLAYING' | 'FINISHED'
export type TableStatus = 'FREE' | 'OCCUPIED'
export type TournamentStage = 'REGISTRATION' | 'GROUP_STAGE' | 'KNOCKOUT' | 'FINISHED'
export type MatchStage = 'GROUP' | 'KNOCKOUT'

export interface Tournament {
  id: number
  name: string
  date: string
  table_count: number
  group_count: number
  qualify_per_group: number
  stage: TournamentStage
  created_at: string
}

export interface Player {
  id: number
  tournament_id: number
  name: string
  college: string | null
  group_id: number | null
}

export interface TableInfo {
  id: number
  tournament_id: number
  name: string
  status: TableStatus
}

export interface GroupPlayer {
  id: number
  name: string
  college: string | null
}

export interface GroupInfo {
  id: number
  name: string
  sort_order: number
  players: GroupPlayer[]
}

export interface GroupingResult {
  groups: GroupInfo[]
}

export interface Match {
  id: number
  tournament_id: number
  stage: MatchStage
  group_id: number | null
  round: number
  match_index: number | null
  player_a_id: number | null
  player_b_id: number | null
  player_a_score: number | null
  player_b_score: number | null
  winner_id: number | null
  table_id: number | null
  status: MatchStatus
  prev_match_a_id: number | null
  prev_match_b_id: number | null
}

export interface GenerateMatchesResult {
  matches_generated: number
  per_group: Record<string, number>
  tournament: Tournament
}

export interface DashboardStats {
  total: number
  finished: number
  playing: number
  waiting: number
}

export interface TableWithMatch {
  id: number
  name: string
  status: TableStatus
  match: Match | null
}

export interface Dashboard {
  tournament: Tournament
  stats: DashboardStats
  tables: TableWithMatch[]
  next_playable: Match[]
}

export interface ScheduleNextResult {
  assigned: number
  assignments: { match_id: number; table_id: number }[]
}

export interface RankingEntry {
  player_id: number
  name: string
  wins: number
  losses: number
  games_won: number
  games_lost: number
  rank: number
  tied: boolean
  qualified: boolean
}

export interface GroupRanking {
  group_id: number
  group_name: string
  total_matches: number
  finished_matches: number
  ambiguous_qualification: boolean
  entries: RankingEntry[]
}

export interface RankingsResult {
  rankings: GroupRanking[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`
    try {
      const body = await resp.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // 非 JSON 错误体，保留默认信息
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),

  listTournaments: () => request<Tournament[]>('/api/tournaments'),
  createTournament: (body: {
    name: string
    date: string
    table_count: number
    group_count: number
    qualify_per_group: number
  }) => request<Tournament>('/api/tournaments', { method: 'POST', body: JSON.stringify(body) }),
  getTournament: (id: number) => request<Tournament>(`/api/tournaments/${id}`),

  listPlayers: (tournamentId: number) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/players`),
  addPlayer: (tournamentId: number, body: { name: string; college?: string | null }) =>
    request<Player>(`/api/tournaments/${tournamentId}/players`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updatePlayer: (
    tournamentId: number,
    playerId: number,
    body: { name?: string; college?: string | null },
  ) =>
    request<Player>(`/api/tournaments/${tournamentId}/players/${playerId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deletePlayer: (tournamentId: number, playerId: number) =>
    request<void>(`/api/tournaments/${tournamentId}/players/${playerId}`, { method: 'DELETE' }),

  getGroups: (tournamentId: number) =>
    request<GroupingResult>(`/api/tournaments/${tournamentId}/groups`),
  autoGroup: (tournamentId: number) =>
    request<GroupingResult>(`/api/tournaments/${tournamentId}/auto-group`, { method: 'POST' }),
  ungroup: (tournamentId: number) =>
    request<void>(`/api/tournaments/${tournamentId}/ungroup`, { method: 'POST' }),

  generateGroupMatches: (tournamentId: number) =>
    request<GenerateMatchesResult>(`/api/tournaments/${tournamentId}/generate-group-matches`, {
      method: 'POST',
    }),
  listMatches: (
    tournamentId: number,
    params?: { stage?: MatchStage; status?: MatchStatus; group_id?: number },
  ) => {
    const qs = new URLSearchParams()
    if (params?.stage) qs.set('stage', params.stage)
    if (params?.status) qs.set('status', params.status)
    if (params?.group_id !== undefined) qs.set('group_id', String(params.group_id))
    const q = qs.toString()
    return request<Match[]>(`/api/tournaments/${tournamentId}/matches${q ? `?${q}` : ''}`)
  },

  assignTable: (matchId: number, tableId: number) =>
    request<Match>(`/api/matches/${matchId}/assign-table`, {
      method: 'POST',
      body: JSON.stringify({ table_id: tableId }),
    }),
  releaseMatch: (matchId: number) =>
    request<Match>(`/api/matches/${matchId}/release`, { method: 'POST' }),
  scheduleNext: (tournamentId: number) =>
    request<ScheduleNextResult>(`/api/tournaments/${tournamentId}/schedule-next`, {
      method: 'POST',
    }),
  getDashboard: (tournamentId: number) =>
    request<Dashboard>(`/api/tournaments/${tournamentId}/dashboard`),

  recordScore: (matchId: number, player_a_score: number, player_b_score: number) =>
    request<Match>(`/api/matches/${matchId}/score`, {
      method: 'POST',
      body: JSON.stringify({ player_a_score, player_b_score }),
    }),
  reviseScore: (matchId: number, player_a_score: number, player_b_score: number) =>
    request<Match>(`/api/matches/${matchId}/revise-score`, {
      method: 'POST',
      body: JSON.stringify({ player_a_score, player_b_score }),
    }),
  getRankings: (tournamentId: number) =>
    request<RankingsResult>(`/api/tournaments/${tournamentId}/rankings`),
}
