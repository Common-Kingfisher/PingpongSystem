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
}
