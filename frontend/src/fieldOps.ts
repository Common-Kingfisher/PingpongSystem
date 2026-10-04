/**
 * C-D5 现场运行展示映射（Console / Schedule 共用）。
 *
 * ## 边界（review 时请重点检查这一节）
 *
 * 本模块**只做三件事**：
 *
 * 1. 把后端已经给出的事实换成人话（`state` 字符串 → 中文标题与说明）；
 * 2. 决定某个操作入口此刻是否可见 / 可点；
 * 3. 球台按编号稳定排序。
 *
 * 它**刻意不做**、以后也不得搬进来的判定：
 *
 * - 阶段是否结束 / 是否可以晋级（唯一权威是后端 Dashboard `completion`，
 *   它由 `backend/app/services/formats.py` 的赛制 Handler 计算）；
 * - “哪一场比赛最应该先打”（唯一权威是后端 `next_playable` 与每张空闲球台的
 *   `recommended_match_id`，由 `backend/app/services/scheduling.py` 的同一套规则算出）；
 * - 组台亲和（后端 `group_table_affinity` 软约束，前端不复制）；
 * - 排名、BYE、种子、比分合法性、下一轮生成规则。
 *
 * 因此本文件里出现的每个分支都必须能指回一个后端字段。前端一旦开始“统计比赛条数
 * 自行判断小组赛是否结束”，就会在赛制调整（循环赛 / 单淘汰 / 小组淘汰）后与后端不一致 —
 * 这正是 C-D5 要收掉的历史问题。
 */

import type { Dashboard, Match, TableWithMatch, TournamentFormat } from './api'

/** Console 现场状态刷新间隔（C-D5 Phase 2 冻结为 5 秒）。 */
export const CONSOLE_POLL_INTERVAL_MS = 5_000

export type CompletionNoticeTone = 'ok' | 'warn' | 'info'

export interface CompletionNotice {
  tone: CompletionNoticeTone
  title: string
  detail: string
  action?: { label: string; to: string }
}

/** 球台固定按台号排列；OCCUPIED / FREE 变化不得导致顺序跳动。 */
export function sortTablesByNumber(tables: TableWithMatch[]): TableWithMatch[] {
  return [...tables].sort((a, b) => a.id - b.id || a.name.localeCompare(b.name, 'zh-CN'))
}

/**
 * 后端给这张空闲球台的调度建议（只读消费）。
 *
 * `recommended_match_id` 由后端调度器算出；前端只把它对应的比赛取出来展示，
 * 不重新计算优先级，也不在没有建议时自行挑一场“最优比赛”。
 */
export function recommendedMatchForTable(
  dashboard: Dashboard | null,
  table: TableWithMatch,
): Match | undefined {
  const matchId = table.recommended_match_id
  if (matchId === null || matchId === undefined) return undefined
  return dashboard?.next_playable.find((match) => match.id === matchId)
}

/**
 * 阶段完成提示：`completion.state` → 现场文案。
 *
 * ## `state` 取值全集（来自后端，前端不得增删）
 *
 * `services/scheduling.py::resolve_completion_state` 透传，来源是
 * `services/formats.py` 三个 Handler 的 `get_completion_state`：
 *
 * ```text
 * GroupKnockoutHandler    GROUP_MATCHES_NOT_GENERATED / GROUP_STAGE_IN_PROGRESS /
 *                         QUALIFICATION_UNRESOLVED / KNOCKOUT_NOT_READY /
 *                         KNOCKOUT_READY / KNOCKOUT_IN_PROGRESS / COMPLETED
 * RoundRobinHandler       MATCHES_NOT_GENERATED / ROUND_ROBIN_IN_PROGRESS /
 *                         RANKING_DATA_INSUFFICIENT / RANKING_UNRESOLVED / COMPLETED
 * SingleEliminationHandler MATCHES_NOT_GENERATED / KNOCKOUT_IN_PROGRESS / COMPLETED
 * scheduling.resolve_completion_state 追加 NOT_APPLICABLE / UNAVAILABLE
 * ```
 *
 * ⚠️ 注意 `GROUP_MATCHES_NOT_GENERATED`（小组淘汰）与 `MATCHES_NOT_GENERATED`
 * （循环赛 / 单淘汰）是**两个不同**的字符串，必须分别匹配 —— 这里合流是因为它们
 * 表达同一件事（本赛制的首阶段比赛尚未生成），只是文案按 `format_code` 区分。
 *
 * 返回值 `null` 表示"正常进行中，不需要额外横幅"。
 * 所有分支都由后端 `completion` + 赛事 `format_code` 决定，前端不推断阶段是否结束。
 */
export function completionNotice(
  dashboard: Dashboard | null,
  tournamentId: number,
): CompletionNotice | null {
  const completion = dashboard?.completion
  if (!completion) return null
  const format: TournamentFormat | null | undefined = completion.format_code
  const query = `?tid=${tournamentId}`

  switch (completion.state) {
    case 'NOT_APPLICABLE':
      // 团体赛有独立链路（本页不渲染个人赛 Console）；未设置赛制的历史赛事要说清楚。
      return format === null || format === undefined
        ? {
            tone: 'warn',
            title: '尚未设置赛制',
            detail: '当前赛事还没有赛制，无法判断阶段推进。请先在「赛事设置 → 赛制与规则」选择并保存赛制。',
            action: { label: '前往赛事设置', to: `/settings${query}` },
          }
        : null

    case 'UNAVAILABLE':
      return {
        tone: 'warn',
        title: '赛制配置无法解析',
        detail: '后端赛制处理器拒绝了当前赛事配置，暂时无法给出权威的阶段状态。请先检查赛制与规则设置。',
        action: { label: '检查赛事设置', to: `/settings${query}` },
      }

    case 'MATCHES_NOT_GENERATED':
    case 'GROUP_MATCHES_NOT_GENERATED': {
      if (format === 'ROUND_ROBIN') {
        return {
          tone: 'info',
          title: '循环赛尚未生成',
          detail: '循环赛不设小组阶段，也没有淘汰阶段：请先在「抽签与编排」生成循环赛程。',
          action: { label: '前往抽签与编排', to: `/draw${query}` },
        }
      }
      if (format === 'SINGLE_ELIMINATION') {
        return {
          tone: 'info',
          title: '淘汰签尚未生成',
          detail: '单淘汰赛不存在小组阶段：请先在「抽签与编排」生成淘汰签表。',
          action: { label: '前往抽签与编排', to: `/draw${query}` },
        }
      }
      return {
        tone: 'info',
        title: '小组赛尚未生成',
        detail: '请先在「抽签与编排」完成分组并生成小组循环赛。',
        action: { label: '前往抽签与编排', to: `/draw${query}` },
      }
    }

    case 'GROUP_STAGE_IN_PROGRESS':
    case 'ROUND_ROBIN_IN_PROGRESS':
    case 'KNOCKOUT_IN_PROGRESS':
      return null

    case 'QUALIFICATION_UNRESOLVED':
      return {
        tone: 'warn',
        title: '小组出线存在无法判定的并列',
        detail: '小组赛已结束，但仍有无法判定的晋级并列。请先到「排名」处理，再继续推进阶段。',
        action: { label: '前往排名', to: `/rankings${query}` },
      }

    case 'KNOCKOUT_NOT_READY':
      return {
        tone: 'warn',
        title: '小组赛已结束，淘汰签暂时无法生成',
        detail: '后端前置检查未通过。请先核对「排名」中的出线与并列情况。',
        action: { label: '前往排名', to: `/rankings${query}` },
      }

    case 'KNOCKOUT_READY':
      return {
        tone: 'ok',
        title: '小组赛已全部完成',
        detail: '晋级名单已经确定，本阶段不再有可安排的比赛。可以进入淘汰赛生成签表。',
        action: { label: '进入淘汰赛', to: `/knockout${query}` },
      }

    case 'RANKING_DATA_INSUFFICIENT':
      return {
        tone: 'warn',
        title: '循环赛已结束，排名数据不足',
        detail: '存在并列且缺少关键场次的逐局小分。请先到「排名」补录后再确认最终名次。',
        action: { label: '前往排名', to: `/rankings${query}` },
      }

    case 'RANKING_UNRESOLVED':
      return {
        tone: 'warn',
        title: '循环赛已结束，但仍有无法判定的并列',
        detail: '并列无法由现有比分自动判定。请先到「排名」处理后再确认最终名次。',
        action: { label: '前往排名', to: `/rankings${query}` },
      }

    case 'COMPLETED':
      if (format === 'ROUND_ROBIN') {
        return {
          tone: 'ok',
          title: '循环赛已全部完成',
          detail: '循环赛不产生淘汰阶段，最终名次以「排名」为准。',
          action: { label: '查看排名', to: `/rankings${query}` },
        }
      }
      return {
        tone: 'ok',
        title: '赛事已全部完成',
        detail: '全部比赛已结束，名次与签表结果已经确定。',
        action: { label: '查看排名', to: `/rankings${query}` },
      }

    default: {
      /*
       * 编译期穷尽检查（PR #66 Warning 2）。
       *
       * `DashboardCompletion.state` 现在是 OpenAPI 生成的**封闭联合**，不是裸 string。
       * 这里把 default 分支的收窄结果赋给 `never`：后端一旦新增 / 改名 state 而这里没有
       * 对应 case，`pnpm exec tsc --noEmit` 会直接失败，而不是静默返回 null
       * （静默返回 null = 横幅消失，正好落入"静默错误 UI"）。
       *
       * 运行期同时兜底：服务端违反契约返回了未知值时，明确告知而不是白屏或静默。
       */
      const unexpectedState: never = completion.state
      return {
        tone: 'warn',
        title: '无法识别赛事状态',
        detail: `后端返回了当前前端无法识别的阶段状态：${String(unexpectedState)}。请刷新页面；若仍出现请联系系统管理员。`,
      }
    }
  }
}

/**
 * 此刻能否给空闲球台安排比赛。
 *
 * 依据全部来自后端：比赛必须存在于 `next_playable`（后端已过滤掉未就绪、
 * 选手正在其他场次、已结束的比赛），且阶段尚未收口。
 */
export function canAssignMatches(dashboard: Dashboard | null): boolean {
  if (!dashboard) return false
  const completion = dashboard.completion
  if (completion.completed || completion.can_advance) return false
  return dashboard.next_playable.length > 0
}

/** 此刻是否还存在可自动安排的比赛。`stats.waiting` 是后端统计，不是前端重算。 */
export function canScheduleBatch(dashboard: Dashboard | null): boolean {
  if (!dashboard) return false
  const completion = dashboard.completion
  if (completion.completed || completion.can_advance) return false
  return dashboard.stats.waiting > 0
}

/** 空闲球台"安排比赛"被禁用时的原因文案；可安排时返回 `undefined`。 */
export function assignDisabledReason(dashboard: Dashboard | null): string | undefined {
  if (!dashboard) return '现场数据尚未就绪'
  const completion = dashboard.completion
  if (completion.completed) return '赛事已全部结束'
  if (completion.can_advance) return '本阶段已结束'
  if (dashboard.next_playable.length === 0) return '当前没有可安排的比赛'
  return undefined
}

/**
 * 「指定球台」的候选球台：只能是后端**此刻确实是 FREE** 的球台。
 *
 * 直接读 `dashboard.tables[].status`，不推断、不缓存、不拿历史状态凑数 ——
 * 前端一旦自己维护"哪张台空着"，就会在别的终端抢占球台后给出一个假空闲列表。
 */
export function freeTables(dashboard: Dashboard | null): TableWithMatch[] {
  if (!dashboard) return []
  return sortTablesByNumber(dashboard.tables.filter((table) => table.status === 'FREE'))
}

/**
 * 某场待进行比赛此刻能否被「指定球台」。
 *
 * 判定完全复用既有的 `canAssignMatches`（后端 `completion` 收口状态）+
 * `dashboard.next_playable` 成员资格：`next_playable` 是后端调度器过滤后的
 * **合法可安排集合**（已就绪、选手不在其他场次、未结束）。
 *
 * ⚠️ 这里刻意**不**用「双方选手非空」或「阶段是小组赛」之类的前端条件替代它：
 * 那等于在前端重写一遍 scheduling 的硬约束。"待进行比赛"列表来自
 * `listMatches(status=WAITING)`，它是 `next_playable` 的**超集**，因此必须按
 * `next_playable` 收窄，否则会把选手正在别处比赛的场次也放上球台（后端会 409）。
 */
export function isPlayableMatch(dashboard: Dashboard | null, match: Match): boolean {
  if (!canAssignMatches(dashboard)) return false
  return (dashboard as Dashboard).next_playable.some((candidate) => candidate.id === match.id)
}
