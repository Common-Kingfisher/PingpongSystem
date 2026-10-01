/**
 * D 轨 · Public 报名有效状态的**唯一**判定点。
 *
 * ## 为什么不能只看 raw `registration_enabled`
 *
 * raw 开关只表示「管理员保存过开启」，它**不等于**「现在还能报名」：
 * 名单确认 / 进入比赛阶段 / TEAM 赛事都不会把 raw 开关自动清零
 * （`repo.confirm_tournament_roster()` 只写 `roster_confirmed` + `confirmed_at`），
 * 因此 `raw=true` 之后赛事仍然可能已经不可报名。
 *
 * 后端的 `create_pending_registration()` 会依次拒绝：
 *
 * ```text
 * event_type === TEAM        → 409 UNSUPPORTED_REGISTRATION_EVENT_TYPE
 * stage !== REGISTRATION     → 409 REGISTRATION_CLOSED
 * roster_confirmed === true  → 409 REGISTRATION_CLOSED
 * registration_enabled=false → 409 REGISTRATION_CLOSED
 * ```
 *
 * 所以 Public 页面必须消费与后端 / 管理端一致的**有效状态**，否则会出现：
 *
 * ```text
 * 管理员开启报名 → 确认名单（raw 仍为 true）
 * → 管理端显示“报名已关闭”，Public 仍显示表单 + 二维码
 * → 用户提交 → 后端必然 409 REGISTRATION_CLOSED
 * ```
 *
 * ## 边界（reviewer 指定）
 *
 * - 纯函数：无副作用、不发请求、不读 localStorage、不读 URL；
 * - 不手写第二套 DTO，只消费 generated contract 派生出的 `Tournament`；
 * - 语义与后端冻结的规则、以及管理端 `TournamentSettingsPage` 的有效报名状态一致
 *   （`registration_enabled && stage === 'REGISTRATION' && !roster_confirmed && event_type !== 'TEAM'`）。
 *
 * TEAM 赛事当前不支持公开**个人**报名，因此即使存在历史 `raw=true` 也必须关闭。
 */

import type { Tournament } from './api'

/**
 * 当前赛事是否允许公开报名。
 *
 * OPEN 需同时满足：
 *
 * ```text
 * registration_enabled === true
 * && stage === 'REGISTRATION'
 * && roster_confirmed === false
 * && event_type !== 'TEAM'
 * ```
 *
 * 任一不满足即为 CLOSED（只读关闭态：无表单、无二维码、无提交动作）。
 */
export function isPublicRegistrationOpen(tournament: Tournament): boolean {
  return (
    tournament.registration_enabled
    && tournament.stage === 'REGISTRATION'
    && !tournament.roster_confirmed
    && tournament.event_type !== 'TEAM'
  )
}
