/**
 * Public 端「赛制 → 展示能力」唯一映射（D 轨 Day4D，PR #50 review 接线轮）。
 *
 * ## 职责边界（很窄，刻意如此）
 *
 * 本文件只回答一个问题：**某种赛制下，Public 端应该展示哪些模块**。
 * 它返回的是 UI capability，不是业务结果。
 *
 * 明确**不**计算（这些全部由后端 A/B 轨负责）：
 *
 * - 参赛者 / 晋级者 / 冠军
 * - 排名与名次（`rankings` 一律渲染后端返回的行）
 * - BYE / seed / 抽签 / 对阵生成 / 完赛状态 / 阶段推进
 *
 * ## 为什么允许 null，且 null 不等于 GROUP_KNOCKOUT
 *
 * D4A 已冻结：历史赛事的新字段保持 `NULL`，**不得**擅自默认成 `GROUP_KNOCKOUT`。
 * 因此 `format_code === null` 时本模块不做任何赛制推断（不看 stage、不看“有没有 group”、
 * 不看“有没有 knockout tree”），一律返回“全部可见”的 legacy 兼容行为 ——
 * 数据驱动展示：有数据就显示，没数据由页面给出中性空态。
 * 这样既不会破坏 V0.2 旧赛事，也不会凭猜测隐藏入口。
 *
 * ## 类型来源
 *
 * `format_code` 的取值必须来自 generated contract（`Schemas['TournamentFormat']`），
 * 本文件不新建第二套 enum，也不使用 `as any`。
 */

import type { Tournament } from './api'

/** Public 端模块可见性。只有这三个开关，避免长成第二个“前端赛制引擎”。 */
export interface PublicCapabilities {
  /** 是否展示「排名」（`/rankings`） */
  showRankings: boolean
  /** 是否展示「签表 / 淘汰赛」（`/bracket`） */
  showBracket: boolean
  /** 是否展示「冠军 / 冠军之路」（`/champion`） */
  showChampion: boolean
}

/** legacy（`format_code == null`）与 GROUP_KNOCKOUT 共用的“全部可见” */
const ALL_VISIBLE: PublicCapabilities = {
  showRankings: true,
  showBracket: true,
  showChampion: true,
}

/**
 * 按赛事赛制返回 Public 展示能力。
 *
 * | 赛制 | 排名 | 签表 | 冠军 |
 * | --- | --- | --- | --- |
 * | `ROUND_ROBIN` | ✅ | ❌ | ❌ |
 * | `SINGLE_ELIMINATION` | ❌ | ✅ | ✅ |
 * | `GROUP_KNOCKOUT` | ✅ | ✅ | ✅ |
 * | `null` / `undefined`（legacy） | ✅ | ✅ | ✅ |
 *
 * 「实况 / 赛程 / 报名」不在此处控制：三条 Public 路由始终可用。
 */
export function getPublicCapabilities(
  formatCode: Tournament['format_code'],
): PublicCapabilities {
  switch (formatCode) {
    case 'ROUND_ROBIN':
      // 循环赛没有淘汰阶段：排名即最终成绩，也没有“冠军之路”
      return { showRankings: true, showBracket: false, showChampion: false }
    case 'SINGLE_ELIMINATION':
      // 单淘汰没有循环赛排名：晋级情况看签表
      return { showRankings: false, showBracket: true, showChampion: true }
    case 'GROUP_KNOCKOUT':
      return ALL_VISIBLE
    default:
      // null / undefined：legacy 兼容，不做任何赛制推断
      return ALL_VISIBLE
  }
}

/** 是否明确为循环赛（仅用于展示分支，不做业务判断） */
export function isRoundRobin(formatCode: Tournament['format_code']): boolean {
  return formatCode === 'ROUND_ROBIN'
}

/** 是否明确为单淘汰 */
export function isSingleElimination(formatCode: Tournament['format_code']): boolean {
  return formatCode === 'SINGLE_ELIMINATION'
}

/**
 * 排名页标题。
 *
 * 只有明确是「小组 + 淘汰」时才是「小组排名」；循环赛与 legacy(null) 一律用中性的「赛事排名」，
 * 因为并非每场赛事都有小组。管理端（`readOnly=false`）不使用本函数，界面保持「小组排名」不变。
 */
export function getRankingsTitle(formatCode: Tournament['format_code']): string {
  return formatCode === 'GROUP_KNOCKOUT' ? '小组排名' : '赛事排名'
}

/**
 * 阶段徽标文案（纯展示映射，不复制任何状态机）。
 *
 * 纯循环赛在库里同样使用 `stage = GROUP_STAGE`，直接照搬会出现
 * 「循环赛赛事显示为小组赛」的误导，因此这里按赛制给出中性说法。
 */
export function getPublicStageLabel(
  formatCode: Tournament['format_code'],
  stage: Tournament['stage'] | null | undefined,
): string {
  if (!stage) return ''
  if (stage === 'REGISTRATION') return '报名中'
  if (stage === 'FINISHED') return '已结束'

  switch (formatCode) {
    case 'ROUND_ROBIN':
      return '循环赛'
    case 'SINGLE_ELIMINATION':
      return '单淘汰'
    default:
      // GROUP_KNOCKOUT 与 legacy(null) 保持既有文案
      return stage === 'KNOCKOUT' ? '淘汰赛' : '小组赛'
  }
}
