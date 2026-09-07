// 编译期 contract type tests：验证 generated OpenAPI 请求 schema 中，
// 带服务端默认值的字段被正确生成为 optional（可省略）。
// 这些是 positive compile tests —— 若生成器将来把 default 字段变回 required，
// `tsc --noEmit` 必须失败。

import type { components } from '../generated/openapi'

type Schemas = components['schemas']

// TournamentCreate：可省略 event_type / bronze_mode / placement_mode / games_to_win / points_to_win。
export const minimalTournament = {
  name: 'Demo',
  date: '2026-09-08',
  table_count: 4,
  group_count: 4,
  qualify_per_group: 2,
} satisfies Schemas['TournamentCreate']

// PlayerCreate：可省略 college / rating_points。
export const minimalPlayer = {
  name: 'Alice',
} satisfies Schemas['PlayerCreate']

// GenerateDemoPlayersRequest：可省略 with_seeds。
export const minimalDemoPlayersRequest = {
  count: 16,
} satisfies Schemas['GenerateDemoPlayersRequest']

// PairingRequest：可完全省略 pairing_seed。
export const emptyPairingRequest = {} satisfies Schemas['PairingRequest']

// ScoreRequest：可省略 result_type / games / forfeit_entry_id / note。
export const minimalScoreRequest = {
  player_a_score: 2,
  player_b_score: 0,
} satisfies Schemas['ScoreRequest']

// PlayerUpdate：partial PATCH 合法（单字段）。
export const partialPlayerUpdate = {
  name: 'Bob',
} satisfies Schemas['PlayerUpdate']

// 额外 default=None 语义：PlayerUpdate 完全为空也应合法。
export const emptyPlayerUpdate = {} satisfies Schemas['PlayerUpdate']
