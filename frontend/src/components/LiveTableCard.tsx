import { Match, TableWithMatch } from '../api'

export default function LiveTableCard({ table, sideName, stageLabel, busy, groupFinished, stageClosed, hintLabel, onAssign, onScore, onRelease }: {
  table: TableWithMatch
  sideName: (match: Match, side: 'a' | 'b') => string
  stageLabel: (match: Match) => string
  busy: boolean
  /** 小组赛阶段已全部结束（淘汰赛还没生成）：本台此刻不可安排比赛。 */
  groupFinished: boolean
  /** 同样处于"小组赛已结束"的过渡窗口，用于把球台文案说清楚。 */
  stageClosed: boolean
  hintLabel?: string
  onAssign: (tableId: number) => void
  onScore: (match: Match) => void
  onRelease: (match: Match) => void
}) {
  const match = table.match
  return <article className={`live-table-card ${match ? 'is-playing' : 'is-free'}`}>
    <div className="live-table-head">
      <span className="live-table-index">{String(table.id).padStart(2, '0')}</span>
      <strong>{table.name}</strong>
      <small><i />{match ? '进行中' : '空闲'}</small>
    </div>
    <div className="live-table-matchup">
      <div className="live-side live-side-a">
        <b>{match ? sideName(match, 'a').slice(0, 1) : '—'}</b>
        <span><strong>{match ? sideName(match, 'a') : '等待安排'}</strong><small>{match ? stageLabel(match) : 'READY'}</small></span>
      </div>
      <div className="live-table-visual" aria-label="乒乓球台">
        <i className="live-net" />{match && <i className="live-ball" />}
      </div>
      <div className="live-side live-side-b">
        <b>{match ? sideName(match, 'b').slice(0, 1) : '—'}</b>
        <span><strong>{match ? sideName(match, 'b') : '等待安排'}</strong><small>{match ? stageLabel(match) : 'READY'}</small></span>
      </div>
    </div>
    <div className="live-table-actions">
      {match ? <>
        <button className="btn small primary" onClick={() => onScore(match)} disabled={busy}>录入大比分</button>
        <button className="btn small live-ghost" onClick={() => onRelease(match)} disabled={busy}>下球台</button>
      </> : <button className="btn small live-assign" onClick={() => onAssign(table.id)} disabled={busy || groupFinished}>
        {groupFinished ? '小组赛已结束' : '安排比赛'}
      </button>}
    </div>
    {!match && stageClosed && (
      <p className="live-table-prefer">小组赛已结束：本台暂时没有可安排的比赛，请先在淘汰赛页生成签表。</p>
    )}
    {!match && hintLabel && (
      <p className="live-table-prefer">{hintLabel}</p>
    )}
  </article>
}
