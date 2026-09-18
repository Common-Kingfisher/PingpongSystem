/**
 * 后端 API 类型定义与 fetch 封装。
 *
 * 契约源：backend/app/schemas.py → FastAPI OpenAPI → docs/openapi-v0.2.json
 *         → frontend/src/generated/openapi.d.ts（由 openapi-typescript 生成）。
 * 下面的 API DTO 一律从 generated contract 派生，不再手工复制。
 */

import type { components } from './generated/openapi'

type Schemas = components['schemas']

// ------------------------------------------------------------------ 枚举（来自 OpenAPI 独立 schema）

export type MatchStatus = Schemas['MatchStatus']
export type TableStatus = Schemas['TableStatus']
export type TournamentStage = Schemas['TournamentStage']
export type MatchStage = Schemas['MatchStage']
export type EventType = Schemas['EventType']
export type TeamTieStatus = Schemas['TeamTieStatus']
export type TeamRubberStatus = Schemas['TeamRubberStatus']
export type TeamRubberType = Schemas['TeamRubberType']
export type TournamentMode = Schemas['TournamentMode']
export type BronzeMode = Schemas['BronzeMode']
export type PlacementMode = Schemas['PlacementMode']
export type MatchBracket = Schemas['MatchBracket']
export type ResultType = Schemas['ResultType']

// ------------------------------------------------------------------ 响应 / 请求 DTO（来自 OpenAPI schema）

export type Tournament = Schemas['TournamentOut']
export type Player = Schemas['PlayerOut']
export type EntryMember = Schemas['EntryMemberOut']
export type Entry = Schemas['EntryOut']
export type EntryWithdrawalResult = Schemas['EntryWithdrawalResult']
export type PairingResult = Schemas['PairingResult']
export type ConfirmRosterResult = Schemas['ConfirmRosterResult']
// 团体赛（A3）：队伍就是 entry_type='TEAM' 的 Entry，所以复用 Entry 类型，不复制字段。
export type TeamTie = Schemas['TeamTieOut']
export type TeamTieDetail = Schemas['TeamTieDetailOut']
export type TeamRubber = Schemas['TeamRubberOut']
export type GroupPlayer = Schemas['GroupPlayerOut']
export type GroupInfo = Schemas['GroupOut']
export type GroupingResult = Schemas['GroupingResult']
export type MatchGame = Schemas['MatchGameOut']
export type ScorePayload = Schemas['ScoreRequest']
export type ScoreRevisionPayload = Schemas['ScoreRevisionRequest']
export type ScoreAudit = Schemas['ScoreAuditOut']
export type GenerateMatchesResult = Schemas['GenerateMatchesResult']
export type DashboardStats = Schemas['DashboardStats']
export type ScheduleNextResult = Schemas['ScheduleNextResult']
export type ImportRowError = Schemas['ImportRowError']
export type ImportPlayersResult = Schemas['ImportPlayersResult']
export type ImportPreviewResult = Schemas['ImportPreviewResult']
export type RankingEntry = Schemas['RankingEntryOut']
export type GroupRanking = Schemas['GroupRankingOut']
export type RankingsResult = Schemas['RankingsResult']
export type QualificationDecision = Schemas['QualificationDecisionOut']
export type PlayerBrief = Schemas['PlayerBrief']
export type KnockoutMatch = Schemas['KnockoutMatchOut']
export type KnockoutRound = Schemas['KnockoutRoundOut']
export type ScheduleEstimateMatch = Schemas['ScheduleEstimateMatch']
export type ScheduleEstimates = Schemas['ScheduleEstimates']

export type Match = Schemas['MatchOut']
export type TableWithMatch = Schemas['TableWithMatch']
export type Dashboard = Schemas['Dashboard']
export type OrderBookSnapshot = Schemas['OrderBookSnapshot']
export type KnockoutTree = Schemas['KnockoutTree']
export type PreflightResult = Schemas['PreflightResult']

// Client request helper（非 transport contract）：
// generated TournamentCreate 将带非 null 默认值的字段标为 required，
// 但客户端可省略 games_to_win / points_to_win（由服务端填充默认值）。
type TournamentCreateRequest = Omit<Schemas['TournamentCreate'], 'games_to_win' | 'points_to_win'> & {
  games_to_win?: number
  points_to_win?: number
}

// ------------------------------------------------------------------ client-only

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

// ------------------------------------------------------------------ client-only view model（非 API contract DTO）

// 后端 KnockoutTree.placement_matches 是 list[dict]，OpenAPI 只能生成 Record<string, unknown>[]；
// 这里描述其真实运行时结构，供 UI 使用。
export interface PlacementMatch {
  range: [number | null, number | null]
  match: KnockoutMatch
}

export function normalizePlacementMatches(raw: KnockoutTree['placement_matches']): PlacementMatch[] {
  const result: PlacementMatch[] = []
  for (const item of raw) {
    const range = item.range
    const match = item.match
    if (Array.isArray(range) && range.length === 2 && typeof match === 'object' && match !== null) {
      const [a, b] = range
      if ((a === null || typeof a === 'number') && (b === null || typeof b === 'number')) {
        result.push({ range: [a, b], match: match as KnockoutMatch })
      }
    }
  }
  return result
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // 局域网 HTTP 访问可能没有 secure-context Web Crypto；仍生成合法 UUID 供后端幂等键使用。
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16)
    return (char === 'x' ? value : (value & 0x3) | 0x8).toString(16)
  })
}

async function submitScore(path: string, payload: ScorePayload): Promise<Match> {
  const body = JSON.stringify({
    ...payload,
    request_id: payload.request_id ?? newRequestId(),
  })
  try {
    return await request<Match>(path, { method: 'POST', body })
  } catch (error) {
    // 网络在服务端提交成功后中断时，用同一 request_id 重试一次；后端会返回同一结果而不重复写入。
    if (error instanceof ApiError) throw error
    return request<Match>(path, { method: 'POST', body })
  }
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),

  listTournaments: () => request<Tournament[]>('/api/tournaments'),
  createTournament: (body: TournamentCreateRequest) =>
    request<Tournament>('/api/tournaments', { method: 'POST', body: JSON.stringify(body) }),
  getTournament: (id: number) => request<Tournament>(`/api/tournaments/${id}`),
  deleteTournament: (id: number, confirmName?: string) =>
    request<void>(`/api/tournaments/${id}${confirmName ? `?confirm_name=${encodeURIComponent(confirmName)}` : ''}`, { method: 'DELETE' }),

  listPlayers: (tournamentId: number) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/players`),
  addPlayer: (tournamentId: number, body: Schemas['PlayerCreate']) =>
    request<Player>(`/api/tournaments/${tournamentId}/players`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updatePlayer: (tournamentId: number, playerId: number, body: Schemas['PlayerUpdate']) =>
    request<Player>(`/api/tournaments/${tournamentId}/players/${playerId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deletePlayer: (tournamentId: number, playerId: number) =>
    request<void>(`/api/tournaments/${tournamentId}/players/${playerId}`, { method: 'DELETE' }),

  setSeeds: (tournamentId: number, playerIds: number[]) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/seeds`, {
      method: 'PUT',
      body: JSON.stringify({ player_ids: playerIds } satisfies Schemas['SetSeedsRequest']),
    }),
  autoSeeds: (tournamentId: number) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/seeds/auto`, { method: 'POST' }),

  generateDemoPlayers: (tournamentId: number, count: number, with_seeds: boolean) =>
    request<Player[]>(`/api/tournaments/${tournamentId}/demo/generate-players`, {
      method: 'POST',
      body: JSON.stringify({ count, with_seeds } satisfies Schemas['GenerateDemoPlayersRequest']),
    }),
  finishGroupStage: (tournamentId: number) =>
    request<Schemas['DemoFinishGroupStageResult']>(
      `/api/tournaments/${tournamentId}/demo/finish-group-stage`,
      { method: 'POST' },
    ),
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
      body: JSON.stringify({ pairing_seed: pairingSeed ?? null } satisfies Schemas['PairingRequest']),
    }),
  confirmRoster: (tournamentId: number) =>
    request<ConfirmRosterResult>(`/api/tournaments/${tournamentId}/confirm-roster`, {
      method: 'POST',
    }),
  withdrawEntry: (tournamentId: number, entryId: number, body: Schemas['EntryWithdrawRequest']) =>
    request<EntryWithdrawalResult>(`/api/tournaments/${tournamentId}/entries/${entryId}/withdraw`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // 团体赛（A3）：队伍即 Entry（entry_type='TEAM'），队员即 entry_members。
  // 这些接口暂时没有对应界面（队伍名单/团体对抗编排不在本版本范围内），先按契约收口，
  // 便于后续直接接入；所有业务错误（非团体赛事、名单已锁定、队员重复等）由后端返回可读 detail。
  listTeams: (tournamentId: number) =>
    request<Entry[]>(`/api/tournaments/${tournamentId}/teams`),
  createTeam: (tournamentId: number, body: Schemas['TeamEntryCreate']) =>
    request<Entry>(`/api/tournaments/${tournamentId}/teams`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getTeam: (tournamentId: number, entryId: number) =>
    request<Entry>(`/api/tournaments/${tournamentId}/teams/${entryId}`),
  updateTeam: (tournamentId: number, entryId: number, body: Schemas['TeamEntryUpdate']) =>
    request<Entry>(`/api/tournaments/${tournamentId}/teams/${entryId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteTeam: (tournamentId: number, entryId: number) =>
    request<void>(`/api/tournaments/${tournamentId}/teams/${entryId}`, { method: 'DELETE' }),

  // 团体对抗与盘骨架：A3 只能建"骨架"（每盘需要几个出场位置），不创建任何普通比赛。
  // 赛制必须来自后端已冻结的注册表，未登记的赛制会返回 422，前端不做任何本地兜底规则。
  listTeamTies: (tournamentId: number) =>
    request<TeamTie[]>(`/api/tournaments/${tournamentId}/team-ties`),
  createTeamTie: (tournamentId: number, body: Schemas['TeamTieCreate']) =>
    request<TeamTie>(`/api/tournaments/${tournamentId}/team-ties`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getTeamTie: (tournamentId: number, tieId: number) =>
    request<TeamTieDetail>(`/api/tournaments/${tournamentId}/team-ties/${tieId}`),
  buildRubberSkeleton: (
    tournamentId: number,
    tieId: number,
    body: Schemas['RubberSkeletonRequest'],
  ) =>
    request<TeamTieDetail>(`/api/tournaments/${tournamentId}/team-ties/${tieId}/rubber-skeleton`, {
      method: 'POST',
      body: JSON.stringify(body),
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
      body: JSON.stringify({ qualify_count: qualifyCount } satisfies Schemas['GroupQualifyUpdate']),
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
      body: JSON.stringify({ table_id: tableId } satisfies Schemas['AssignTableRequest']),
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
  ) => submitScore(
    `/api/matches/${matchId}/score`,
    typeof player_a_score === 'number'
      ? { player_a_score, player_b_score, result_type: 'NORMAL' }
      : player_a_score,
  ),
  reviseScore: (matchId: number, payload: ScoreRevisionPayload) => submitScore(
    `/api/matches/${matchId}/revise-score`,
    payload,
  ),
  listScoreAudits: (matchId: number) =>
    request<ScoreAudit[]>(`/api/matches/${matchId}/score-audits`),
  getRankings: (tournamentId: number) =>
    request<RankingsResult>(`/api/tournaments/${tournamentId}/rankings`),
  createQualificationDecision: (
    tournamentId: number,
    groupId: number,
    body: Schemas['QualificationDecisionCreate'],
  ) => request<QualificationDecision>(
    `/api/tournaments/${tournamentId}/groups/${groupId}/qualification-decision`,
    { method: 'POST', body: JSON.stringify(body) },
  ),
  revokeQualificationDecision: (
    tournamentId: number,
    groupId: number,
    body: Schemas['QualificationDecisionRevoke'],
  ) => request<QualificationDecision>(
    `/api/tournaments/${tournamentId}/groups/${groupId}/qualification-decision/revoke`,
    { method: 'POST', body: JSON.stringify(body) },
  ),
  listQualificationDecisions: (tournamentId: number, groupId: number) =>
    request<QualificationDecision[]>(
      `/api/tournaments/${tournamentId}/groups/${groupId}/qualification-decisions`,
    ),

  generateKnockout: (tournamentId: number) =>
    request<KnockoutTree>(`/api/tournaments/${tournamentId}/generate-knockout`, {
      method: 'POST',
    }),
  getKnockout: (tournamentId: number) =>
    request<KnockoutTree>(`/api/tournaments/${tournamentId}/knockout`),
  // 撤销淘汰签表：淘汰赛未开始时可用，已开赛返回 409（后端保护，前端只需展示错误）。
  undoKnockout: (tournamentId: number) =>
    request<Schemas['KnockoutUndoResult']>(`/api/tournaments/${tournamentId}/knockout/undo`, {
      method: 'POST',
    }),
  // 赛事结构化导出（只读）：可用于删除前的人工备份。
  exportTournament: (tournamentId: number) =>
    request<Schemas['TournamentExport']>(`/api/tournaments/${tournamentId}/export`),
  // 预计上场时间（只读模拟，与自动排台同一套规则）；签位未定的场次为 null。
  getScheduleEstimates: (tournamentId: number) =>
    request<Schemas['ScheduleEstimates']>(
      `/api/tournaments/${tournamentId}/schedule-estimates`,
    ),
  getOrderBookSnapshot: (tournamentId: number) =>
    request<OrderBookSnapshot>(`/api/tournaments/${tournamentId}/order-book-snapshot`),
  getPreflight: (tournamentId: number) =>
    request<PreflightResult>(`/api/tournaments/${tournamentId}/preflight`),
}
