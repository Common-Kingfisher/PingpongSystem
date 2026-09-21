/**
 * 手机录分提交载荷构造（D 轨 Day 3）。
 *
 * ## 边界（本文件的核心约束）
 *
 * **服务端是比分合法性的唯一权威。** 这里只做“现场交互提示”级别的最小检查：
 *
 * - 字段是否填了（空值提示）
 * - 是不是非负整数（数字输入）
 * - 大比分两边是不是相同（明显笔误）
 * - 小比分是否出现半局（只有一边填了）
 *
 * 这里**刻意不做**、以后也不得搬进来的判定：
 *
 * - 合法比分判定（每局到几分、平分延长、胜局数上限的完整规则）
 * - winner 计算
 * - 小比分与大比分一致性算法
 * - 淘汰赛推进 / 改分下游影响
 *
 * 上述规则全部由后端 `backend/app/services/scores.py` 返回的 422 / 409 业务文案表达，
 * 页面原样展示即可。前端一旦复制这些规则，就会出现“第二套真相源”，
 * 必然在某次规则调整后与后端不一致。
 *
 * ## 载荷形状
 *
 * 必须严格使用当前 OpenAPI contract（`components['schemas']['ScoreRequest']`）：
 *
 * ```jsonc
 * {
 *   "player_a_score": 2,          // 正常比赛必填
 *   "player_b_score": 1,          // 正常比赛必填
 *   "games": [ { "side_a_score": 11, "side_b_score": 7 } ],  // 可选；不录就整体省略
 *   "result_type": "NORMAL",      // 或 FORFEIT / WALKOVER / NO_SHOW / DISQUALIFIED
 *   "forfeit_entry_id": null,     // 异常结果必填：弃权/未到场的一方
 *   "note": null,
 *   "operator_name": "张三",
 *   "request_id": "<uuid>"
 * }
 * ```
 *
 * 不得发明 `gameScores` / `roundScores` / `abnormal` 之类的临时字段 —— 后端会直接忽略它们，
 * 结果就是“页面显示成功、服务端没保存”。
 */

import type { Match, ResultType, ScorePayload } from './api'

/** 逐局小比分的输入草稿（字符串，因为输入框可能为空）。 */
export interface GameDraft {
  a: string
  b: string
}

/**
 * 后端 `ResultType` 的中文展示名。
 *
 * 取值必须与 OpenAPI `ResultType` 枚举逐一对应；前端**不得**新增枚举值。
 * 见 `backend/app/models.py::ResultType`。
 */
export const RESULT_TYPE_LABELS: Record<ResultType, string> = {
  NORMAL: '正常完赛',
  FORFEIT: '主动弃权',
  WALKOVER: '直接晋级（对手未到场）',
  NO_SHOW: '未到场',
  DISQUALIFIED: '取消资格',
}

/**
 * 异常结果下拉可选项：**排除 NORMAL**（正常完赛有独立入口）。
 *
 * 顺序固定为“现场最常用 → 最少用”，减少裁判在手机上误选。
 */
export const ABNORMAL_RESULT_TYPES: ResultType[] = [
  'FORFEIT',
  'NO_SHOW',
  'WALKOVER',
  'DISQUALIFIED',
]

export interface ScoreSideLabels {
  a: string
  b: string
}

/**
 * 异常结果的一句话描述，例如「李四弃权」。
 *
 * 语义要求（Day 3 冻结）：
 *
 * - 异常结果**不得**显示成 `张三 2:0 李四`；
 * - 但小组赛的后端会为排名写入行政比分（胜方 `games_to_win` : 0），
 *   因此页面在需要展示比分时必须**同时**标明这是异常结果，而不是逐局比分。
 */
export function abnormalResultLabel(
  resultType: ResultType,
  forfeitEntryId: number | null | undefined,
  sides: ScoreSideLabels | null,
  entryIds?: { a: number | null; b: number | null },
): string {
  const typeLabel = RESULT_TYPE_LABELS[resultType] ?? resultType
  if (resultType === 'NORMAL') return typeLabel

  let sideLabel: string | null = null
  if (sides && entryIds && forfeitEntryId != null) {
    if (entryIds.a != null && entryIds.a === forfeitEntryId) sideLabel = sides.a
    else if (entryIds.b != null && entryIds.b === forfeitEntryId) sideLabel = sides.b
  }

  switch (resultType) {
    case 'FORFEIT':
      return sideLabel ? `${sideLabel}弃权` : '弃权（未指定弃权方）'
    case 'NO_SHOW':
      return sideLabel ? `${sideLabel}未到场` : '未到场（未指定一方）'
    case 'DISQUALIFIED':
      return sideLabel ? `${sideLabel}被取消资格` : '取消资格'
    case 'WALKOVER':
      return sideLabel ? `${sideLabel}未到场，对手直接晋级` : '直接晋级（对手未到场）'
    default:
      return typeLabel
  }
}

/** 逐局小比分的一行展示文案，例如 `11-7`。 */
export function gameScoreLabel(game: { side_a_score: number; side_b_score: number }): string {
  return `${game.side_a_score}-${game.side_b_score}`
}

/** 逐局小比分整体展示文案，例如 `11-7 / 9-11 / 11-8`。 */
export function gamesScoreLabel(games: { side_a_score: number; side_b_score: number }[]): string {
  return games.map(gameScoreLabel).join(' / ')
}

// ------------------------------------------------------------------ 输入解析

/** 输入框字符串 → 非负整数；空串 / 非数字 / 负数 → null。 */
export function parseScoreInput(raw: string): number | null {
  const text = raw.trim()
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  return Number.isSafeInteger(value) ? value : null
}

/** 大比分状态。 */
export interface BigScoreState {
  /** 双方都填了合法非负整数 */
  filled: boolean
  a: number | null
  b: number | null
}

export function readBigScore(scoreA: string, scoreB: string): BigScoreState {
  const a = parseScoreInput(scoreA)
  const b = parseScoreInput(scoreB)
  return { filled: a !== null && b !== null, a, b }
}

/**
 * 构造正常完赛的请求载荷。返回 `error` 时**不发请求**（这只是省掉一次必然失败的往返）。
 *
 * 注意两个刻意的行为：
 *
 * 1. 不展开 / 未填写逐局小比分时，`games` 字段**整体省略**（不是 `[]`、更不是伪造的局分）。
 *    后端 `_validate_normal_score_payload` 只在 `games is not None` 时才校验小比分；
 *    传 `[]` 会被当成“提供了空的小比分”而报错。
 * 2. 逐局小分只有一边填了（半局）时直接拦下：半局数据在后端同样会被拒绝，
 *    但在这里提示能让裁判立刻知道是哪一局没填完。
 */
export function buildNormalScorePayload(params: {
  scoreA: string
  scoreB: string
  games: GameDraft[]
  gamesToWin: number
  operatorName?: string
  note?: string
  requestId?: string
}): { payload: ScorePayload | null; error: string | null } {
  const { scoreA, scoreB, games, gamesToWin, operatorName, note, requestId } = params

  if (scoreA.trim() === '' || scoreB.trim() === '') {
    return { payload: null, error: '请先填写双方大比分。' }
  }

  const big = readBigScore(scoreA, scoreB)
  if (!big.filled || big.a === null || big.b === null) {
    return { payload: null, error: '大比分只能填写 0 以上的整数。' }
  }
  if (big.a === big.b) {
    return { payload: null, error: '大比分不能平局，请检查后重新填写。' }
  }
  if (Math.max(big.a, big.b) !== gamesToWin) {
    return {
      payload: null,
      error: `本赛事为 ${gamesToWin} 局制：胜方大比分必须是 ${gamesToWin}，负方为 0 ~ ${gamesToWin - 1}。`,
    }
  }

  const payload: ScorePayload = {
    player_a_score: big.a,
    player_b_score: big.b,
    result_type: 'NORMAL',
  }
  if (operatorName && operatorName.trim() !== '') payload.operator_name = operatorName.trim()
  if (note && note.trim() !== '') payload.note = note.trim()
  if (requestId) payload.request_id = requestId

  if (games.length > 0) {
    const parsed: { side_a_score: number; side_b_score: number }[] = []
    for (const [index, game] of games.entries()) {
      const a = parseScoreInput(game.a)
      const b = parseScoreInput(game.b)
      if (a === null && b === null) {
        return { payload: null, error: `第 ${index + 1} 局还没填完。请填写，或删除这一局。` }
      }
      if (a === null || b === null) {
        return { payload: null, error: `第 ${index + 1} 局的双方分数都要填写（不能只填一边）。` }
      }
      parsed.push({ side_a_score: a, side_b_score: b })
    }
    payload.games = parsed
  }

  return { payload, error: null }
}

/**
 * 构造异常结果的请求载荷。
 *
 * 关键规则：**异常结果不带任何逐局小比分**。
 * 不为了在界面上凑出 `2:0` 而在前端伪造局分；需要行政比分时由后端按赛事规则写入。
 */
export function buildAbnormalScorePayload(params: {
  resultType: ResultType
  forfeitEntryId: number | null
  operatorName?: string
  note?: string
  requestId?: string
}): { payload: ScorePayload | null; error: string | null } {
  const { resultType, forfeitEntryId, operatorName, note, requestId } = params

  if (resultType === 'NORMAL') {
    return { payload: null, error: '异常结果不能使用“正常完赛”类型。' }
  }
  if (forfeitEntryId === null) {
    return { payload: null, error: '请选择异常结果对应的一方。' }
  }

  const payload: ScorePayload = {
    result_type: resultType,
    forfeit_entry_id: forfeitEntryId,
  }
  if (operatorName && operatorName.trim() !== '') payload.operator_name = operatorName.trim()
  if (note && note.trim() !== '') payload.note = note.trim()
  if (requestId) payload.request_id = requestId

  return { payload, error: null }
}

// ------------------------------------------------------------------ 比赛展示

/** 比赛状态的中文文案。 */
export function matchStatusLabel(status: Match['status']): string {
  switch (status) {
    case 'WAITING':
      return '待开始'
    case 'PLAYING':
      return '进行中'
    case 'FINISHED':
      return '已结束'
    default:
      return status
  }
}

/** 赛段中文文案；`groupName` 由调用方从赛事分组数据映射，缺省时不猜。 */
export function matchStageLabel(match: Pick<Match, 'stage' | 'round'>, groupName?: string | null): string {
  if (match.stage === 'GROUP') {
    const base = groupName && groupName !== '' ? `${groupName} · 小组赛` : '小组赛'
    return match.round > 0 ? `${base} · 第 ${match.round} 轮` : base
  }
  return match.round > 0 ? `淘汰赛 · 第 ${match.round} 轮` : '淘汰赛'
}

/** 比赛双方是否都已就绪（避免对“等待上一轮胜者”的比赛录分）。 */
export function matchSidesReady(match: Pick<Match, 'entry_a_id' | 'entry_b_id' | 'player_a_id' | 'player_b_id'>): boolean {
  const sideA = match.entry_a_id ?? match.player_a_id
  const sideB = match.entry_b_id ?? match.player_b_id
  return sideA != null && sideB != null
}
