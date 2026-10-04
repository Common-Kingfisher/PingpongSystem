import { Match, TableWithMatch } from '../api'
import { matchStatusLabel } from '../mobileScore'

/**
 * 现场球台卡片（C-D5 Phase 2）。
 *
 * 卡片只展示后端事实 + 触发回调：
 * - 是否可安排比赛由 `assignDisabledReason` 决定（上游来自后端 `completion` / `next_playable`）；
 * - “后端推荐”只读展示 `recommended_match_id` 对应的比赛，卡片不挑比赛。
 */
export default function LiveTableCard({ table, sideName, stageLabel, busy, assignDisabledReason, recommendedMatch, onAssign, onScore, onRelease }: {
  table: TableWithMatch
  sideName: (match: Match, side: 'a' | 'b') => string
  stageLabel: (match: Match) => string
  busy: boolean
  /** 非空时禁用"安排比赛"并把这句话作为禁用原因显示。 */
  assignDisabledReason?: string
  /** 后端为该空闲球台给出的推荐比赛（只读，不参与计算）。 */
  recommendedMatch?: Match
  onAssign: (table: TableWithMatch) => void
  onScore: (match: Match) => void
  onRelease: (match: Match) => void
}) {
  const match = table.match
  const assignable = match === null && assignDisabledReason === undefined

  return <article className={`live-table-card ${match ? 'is-playing' : 'is-free'}`}>
    <div className="live-table-head">
      <span className="live-table-index">{String(table.id).padStart(2, '0')}</span>
      <strong title={table.name}>{table.name}</strong>
      <small><i />{match ? '进行中' : '空闲'}</small>
    </div>
    <div className="live-table-matchup">
      <div className="live-side live-side-a">
        <b>{match ? sideName(match, 'a').slice(0, 1) : '—'}</b>
        <span>
          <strong>{match ? sideName(match, 'a') : '空闲'}</strong>
          <small>{match ? `${stageLabel(match)} · ${matchStatusLabel(match.status)}` : '待安排'}</small>
        </span>
      </div>
      <div className="live-table-visual" aria-label="乒乓球台">
        <i className="live-net" />{match && <i className="live-ball" />}
      </div>
      <div className="live-side live-side-b">
        <b>{match ? sideName(match, 'b').slice(0, 1) : '—'}</b>
        <span>
          <strong>{match ? sideName(match, 'b') : '空闲'}</strong>
          <small>{match ? `${stageLabel(match)} · ${matchStatusLabel(match.status)}` : '待安排'}</small>
        </span>
      </div>
    </div>
    <div className="live-table-actions">
      {match ? <>
        <button className="btn small primary" onClick={() => onScore(match)} disabled={busy}>录入大比分</button>
        <button className="btn small live-ghost" onClick={() => onRelease(match)} disabled={busy}>下球台</button>
      </> : <button
        className="btn small live-assign"
        onClick={() => onAssign(table)}
        disabled={busy || !assignable}
      >
        {assignable ? '安排比赛' : assignDisabledReason}
      </button>}
    </div>
    {!match && recommendedMatch && (
      <p className="live-table-prefer">
        后端推荐：{sideName(recommendedMatch, 'a')} vs {sideName(recommendedMatch, 'b')}
      </p>
    )}
    {!match && !recommendedMatch && (
      <p className="live-table-prefer">空闲 · 等待安排比赛</p>
    )}
  </article>
}
