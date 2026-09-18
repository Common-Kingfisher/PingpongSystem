/**
 * 团体赛运行态消费模型（设计阶段）。字段来源与 nullable 语义以
 * docs/TEAM_RUNTIME_CONTRACT.md 为准；真实机器契约仍以 OpenAPI 为唯一真相源。
 */
export type TeamTieStatus = 'WAITING' | 'PLAYING' | 'FINISHED'
export type TeamRubberStatus = 'PENDING' | 'READY' | 'PLAYING' | 'FINISHED' | 'SKIPPED'
export type TeamRubberType = 'SINGLES' | 'DOUBLES'

export interface TeamPermission {
  can_edit_lineup: boolean
  can_confirm_lineup: boolean
  can_start: boolean
  can_record_score: boolean
  can_revise_score: boolean
}

export interface TeamSummary {
  entry_id: number
  display_name: string
  status: 'ACTIVE' | 'WITHDRAWN'
  members?: string[]
}

export interface TeamFormatView {
  code: string | null
  version: string | null
  display_name: string | null
}

export interface TeamLineupOption {
  player_id: number
  name: string
  available: boolean
  unavailable_reason: string | null
}

export interface TeamRubberView {
  id: number
  sequence: number
  rubber_type: TeamRubberType
  status: TeamRubberStatus
  home_slots: string[]
  away_slots: string[]
  home_players: string[]
  away_players: string[]
  home_score: number | null
  away_score: number | null
  winner_side: 'HOME' | 'AWAY' | null
  permissions: TeamPermission
  lineup_options: TeamLineupOption[]
}

export interface TeamTieView {
  id: number
  tournament_id: number
  stage: 'GROUP' | 'KNOCKOUT'
  status: TeamTieStatus
  home_team: TeamSummary
  away_team: TeamSummary
  home_score: number
  away_score: number
  target_wins: number | null
  format: TeamFormatView
  rubbers: TeamRubberView[]
  winner_entry_id: number | null
  permissions: TeamPermission
}
