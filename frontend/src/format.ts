// 赛制文案：局制（三局两胜 / 五局三胜 / 七局四胜）与每局目标分统一从这里读取，
// 页面不得写死"三局两胜"或"11 分"。
import type { EventType, TournamentFormat, TournamentStage } from './api'

const chineseNumber = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']

function numberLabel(value: number): string {
  return chineseNumber[value] ?? String(value)
}

/** 「三局两胜」「五局三胜」「七局四胜」等业务语言。 */
export function formatName(gamesToWin: number): string {
  return `${numberLabel(gamesToWin * 2 - 1)}局${numberLabel(gamesToWin)}胜`
}

/** 「三局两胜 · 每局 11 分」。 */
export function formatSummary(tournament: { games_to_win: number; points_to_win: number }): string {
  return `${formatName(tournament.games_to_win)} · 每局 ${tournament.points_to_win} 分`
}

/** 创建/编辑下拉选项：业务语言 ↔ games_to_win。 */
export const formatOptions: { value: number; label: string }[] = [2, 3, 4].map((games) => ({
  value: games,
  label: formatName(games),
}))

/**
 * 参赛项目文案。
 *
 * 显式覆盖三个分支：TEAM 不能被"非双打即单打"的旧写法显示成"单打"。
 * （团体赛的队名单/对抗界面尚未提供，但赛事列表与详情必须显示正确的项目名。）
 */
export function eventTypeLabel(eventType: EventType): string {
  switch (eventType) {
    case 'SINGLES':
      return '单打'
    case 'DOUBLES':
      return '双打'
    case 'TEAM':
      return '团体赛'
  }
}

export function tournamentFormatLabel(format: TournamentFormat | null | undefined): string {
  switch (format) {
    case 'ROUND_ROBIN':
      return '循环赛'
    case 'SINGLE_ELIMINATION':
      return '单淘汰赛'
    case 'GROUP_KNOCKOUT':
      return '小组赛 + 淘汰赛'
    default:
      return '赛制待设置'
  }
}

/** 只负责用户可读文案；赛事阶段推进仍完全由后端负责。 */
export function tournamentStageLabel(
  stage: TournamentStage,
  format: TournamentFormat | null | undefined,
): string {
  switch (stage) {
    case 'REGISTRATION':
      return '报名与赛前准备'
    case 'GROUP_STAGE':
      return format === 'ROUND_ROBIN' ? '循环赛阶段' : '小组赛阶段'
    case 'KNOCKOUT':
      return '淘汰赛阶段'
    case 'FINISHED':
      return '赛事已结束'
  }
}
