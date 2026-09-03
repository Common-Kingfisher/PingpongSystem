/**
 * 后端 API 类型定义与 fetch 封装。
 * 类型与后端 Enum code 一一对应（backend/app/models.py）。
 */

export type MatchStatus = 'WAITING' | 'PLAYING' | 'FINISHED'
export type TableStatus = 'FREE' | 'OCCUPIED'
export type TournamentStage = 'REGISTRATION' | 'GROUP_STAGE' | 'KNOCKOUT' | 'FINISHED'
export type MatchStage = 'GROUP' | 'KNOCKOUT'
export type EventType = 'SINGLES' | 'DOUBLES'
export type BronzeMode = 'BRONZE_MATCH' | 'JOINT_BRONZE'
export type PlacementMode = 'OFF' | 'COMPLETE' | 'TIERED'
export type MatchBracket = 'GROUP' | 'MAIN' | 'PLACEMENT'
export type ResultType = 'NORMAL' | 'FORFEIT' | 'WALKOVER' | 'NO_SHOW' | 'DISQUALIFIED'

export interface Tournament {
  id: number
  name: string
  date: string
  table_count: number
  group_count: number
  qualify_per_group: number
  stage: TournamentStage
  created_at: string
  event_type: EventType
  bronze_mode: BronzeMode
  placement_mode: PlacementMode
  games_to_win: number
  points_to_win: number
  roster_confirmed: boolean
  confirmed_at: string | null
}

export interface Player {
  id: number
  tournament_id: number
  name: string
  college: string | null
  group_id: number | null
  seed_no: number | null
  rating_points: number
}

export interface EntryMember {
  player_id: number
  name: string
  college: string | null
  rating_points: number
  member_order: number
}

export interface Entry {
  id: number
  tournament_id: number
  entry_type: EventType
  display_name: string
  rating_points: number
  group_id: number | null
  seed_no: number | null
  status: 'ACTIVE' | 'WITHDRAWN'
  members: EntryMember[]
}

export interface PairingResult {
  entries: Entry[]
  unpaired_players: Player[]
  pairing_seed: number
}

export interface ConfirmRosterResult {
  tournament: Tournament
  entries: Entry[]
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
  qualify_count: number | null
  players: GroupPlayer[]
  entries: Entry[]
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
  entry_a_id: number | null
  entry_b_id: number | null
  winner_entry_id: number | null
  entry_a_name: string | null
  entry_b_name: string | null
  result_type: ResultType | null
  forfeit_entry_id: number | null
  bracket: MatchBracket
  placement_min: number | null
  placement_max: number | null
  games: MatchGame[]
}

export interface MatchGame {
  id: number
  match_id: number
  game_no: number
  side_a_score: number
  side_b_score: number
  winner_entry_id: number | null
}

export interface ScorePayload {
  player_a_score?: number
  player_b_score?: number
  games?: { side_a_score: number; side_b_score: number }[]
  result_type?: ResultType
  forfeit_entry_id?: number | null
  note?: string
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

export interface ImportRowError {
  row: number
  message: string
}

export interface ImportPlayersResult {
  total_rows: number
  imported: number
  skipped: number
  errors: ImportRowError[]
}

export interface ImportPreviewResult {
  total_rows: number
  valid_rows: number
  skipped: number
  errors: ImportRowError[]
  rows: Array<{
    row: number
    name: string
    college: string | null
    rating_points: number
    seed_no: number | null
    status: 'valid' | 'warning' | 'error'
    message: string | null
  }>
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
  entry_id: number | null
  match_points: number
  points_won: number
  points_lost: number
  point_difference: number
  point_ratio: number
}

export interface GroupRanking {
  group_id: number
  group_name: string
  qualify_count: number
  total_matches: number
  finished_matches: number
  ambiguous_qualification: boolean
  needs_point_scores: boolean
  point_score_match_ids: number[]
  entries: RankingEntry[]
}

export interface RankingsResult {
  rankings: GroupRanking[]
}

export interface PlayerBrief {
  id: number
  name: string | null
  seed_no: number | null
  member_names: string[]
}

export interface KnockoutMatch {
  id: number
  round: number
  match_index: number
  status: MatchStatus
  player_a: PlayerBrief | null
  player_b: PlayerBrief | null
  player_a_score: number | null
  player_b_score: number | null
  winner_id: number | null
  table_id: number | null
  prev_match_a_id: number | null
  prev_match_b_id: number | null
  bracket: MatchBracket
  placement_min: number | null
  placement_max: number | null
  result_type: ResultType | null
}

export interface KnockoutRound {
  round: number
  label: string
  matches: KnockoutMatch[]
}

export interface KnockoutTree {
  tournament: Tournament
  rounds: KnockoutRound[]
  champion: PlayerBrief | null
  runner_up: PlayerBrief | null
  placements: Array<Record<string, unknown>>
  placement_matches: Array<{ range: [number | null, number | null]; match: KnockoutMatch }>
  champion_path_match_ids: number[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData 上传时由浏览器自动生成 multipart boundary，不能手动设 Content-Type
  const isForm = init?.body instanceof FormData
  const resp = await fetch(path, {
    headers: isForm ? undefined : { 'Content-Type': 'application/json' },
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
    // 开发期诊断：把失败请求的 method/url/status/detail 打到浏览器 Console
    console.error(`[api] ${init?.method ?? 'GET'} ${path} -> ${resp.status}`, detail)
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
    event_type?: EventType
    bronze_mode?: BronzeMode
    placement_mode?: PlacementMode
    games_to_win?: number
    points_to_win?: number
  }) => request<Tournament>('/api/tournaments', { method: 'POST', body: JSON.stringify(body) }),
  getTournament: (id: number) => request<Tournament>(`/api/tournaments/${id}`),
  deleteTournament: (id: number) =>
    request<void>(`/api/tournaments/${id}`, { method: 'DELETE' }),

  listPlayers: (tournamentId: number) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/players`),
  addPlayer: (
    tournamentId: number,
    body: { name: string; college?: string | null; rating_points?: number },
  ) =>
    request<Player>(`/api/tournaments/${tournamentId}/players`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updatePlayer: (
    tournamentId: number,
    playerId: number,
    body: { name?: string; college?: string | null; rating_points?: number },
  ) =>
    request<Player>(`/api/tournaments/${tournamentId}/players/${playerId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deletePlayer: (tournamentId: number, playerId: number) =>
    request<void>(`/api/tournaments/${tournamentId}/players/${playerId}`, { method: 'DELETE' }),

  setSeeds: (tournamentId: number, playerIds: number[]) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/seeds`, {
      method: 'PUT',
      body: JSON.stringify({ player_ids: playerIds }),
    }),

  generateDemoPlayers: (tournamentId: number, count: number, with_seeds: boolean) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/demo/generate-players`, {
      method: 'POST',
      body: JSON.stringify({ count, with_seeds }),
    }),
  finishGroupStage: (tournamentId: number) =>
    request<{ finished: number }>(`/api/tournaments/${tournamentId}/demo/finish-group-stage`, {
      method: 'POST',
    }),
  importPlayers: (tournamentId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImportPlayersResult>(`/api/tournaments/${tournamentId}/players/import`, {
      method: 'POST',
      body: form,
    })
  },
  previewPlayersImport: (tournamentId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImportPreviewResult>(`/api/tournaments/${tournamentId}/players/import/preview`, {
      method: 'POST',
      body: form,
    })
  },

  listEntries: (tournamentId: number) =>
    request<Entry[]>(`/api/tournaments/${tournamentId}/entries`),
  pairDoubles: (tournamentId: number, pairingSeed?: number) =>
    request<PairingResult>(`/api/tournaments/${tournamentId}/pair-doubles`, {
      method: 'POST',
      body: JSON.stringify({ pairing_seed: pairingSeed ?? null }),
    }),
  confirmRoster: (tournamentId: number) =>
    request<ConfirmRosterResult>(`/api/tournaments/${tournamentId}/confirm-roster`, {
      method: 'POST',
    }),

  getGroups: (tournamentId: number) =>
    request<GroupingResult>(`/api/tournaments/${tournamentId}/groups`),
  autoGroup: (tournamentId: number) =>
    request<GroupingResult>(`/api/tournaments/${tournamentId}/auto-group`, { method: 'POST' }),
  ungroup: (tournamentId: number) =>
    request<void>(`/api/tournaments/${tournamentId}/ungroup`, { method: 'POST' }),
  setGroupQualification: (tournamentId: number, groupId: number, qualifyCount: number) =>
    request<GroupInfo>(`/api/tournaments/${tournamentId}/groups/${groupId}/qualification`, {
      method: 'PATCH',
      body: JSON.stringify({ qualify_count: qualifyCount }),
    }),

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

  recordScore: (
    matchId: number,
    player_a_score: number | ScorePayload,
    player_b_score?: number,
  ) =>
    request<Match>(`/api/matches/${matchId}/score`, {
      method: 'POST',
      body: JSON.stringify(
        typeof player_a_score === 'number'
          ? { player_a_score, player_b_score }
          : player_a_score,
      ),
    }),
  reviseScore: (
    matchId: number,
    player_a_score: number | ScorePayload,
    player_b_score?: number,
  ) =>
    request<Match>(`/api/matches/${matchId}/revise-score`, {
      method: 'POST',
      body: JSON.stringify(
        typeof player_a_score === 'number'
          ? { player_a_score, player_b_score }
          : player_a_score,
      ),
    }),
  getRankings: (tournamentId: number) =>
    request<RankingsResult>(`/api/tournaments/${tournamentId}/rankings`),

  generateKnockout: (tournamentId: number) =>
    request<KnockoutTree>(`/api/tournaments/${tournamentId}/generate-knockout`, {
      method: 'POST',
    }),
  getKnockout: (tournamentId: number) =>
    request<KnockoutTree>(`/api/tournaments/${tournamentId}/knockout`),
}
