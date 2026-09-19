import { TeamRubberView, TeamTieView } from '../../team/types'

const statusLabel: Record<TeamRubberView['status'], string> = {
  PENDING: '待阵容', READY: '可开始', PLAYING: '进行中', FINISHED: '已结束', SKIPPED: '不再进行',
}
const tieStatusLabel: Record<TeamTieView['status'], string> = { WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束' }

function unavailableReason(busy: boolean): string {
  if (busy) return '正在提交其他操作，请稍候'
  return '当前服务端规则不允许此操作，请刷新后重试'
}

export default function TeamScorePanel({ tie, busy, onLineup, onStart, onScore }: {
  tie: TeamTieView
  busy: boolean
  onLineup: (rubber: TeamRubberView, trigger: HTMLButtonElement) => void
  onStart: (rubber: TeamRubberView, trigger: HTMLButtonElement) => void
  onScore: (rubber: TeamRubberView, trigger: HTMLButtonElement) => void
}) {
  return (
    <section className="team-score-panel" aria-label="团体赛比分面板">
      <div className="team-panel-heading"><div><span className="eyebrow">RUBBERS</span><h3>盘次列表</h3></div><span className={`team-status ${tie.status.toLowerCase()}`}>{tieStatusLabel[tie.status]}</span></div>
      {tie.rubbers.length === 0 ? <p className="muted">暂无盘次。真实数据到位后由后端返回顺序与状态。</p> : (
        <div className="rubber-list">{tie.rubbers.map((rubber) => <article className={`rubber-card ${rubber.status.toLowerCase()}`} key={rubber.id}>
          <div className="rubber-card-head"><strong>第 {rubber.sequence} 盘 · {rubber.rubber_type === 'SINGLES' ? '单打' : '双打'}</strong><span>{statusLabel[rubber.status]}</span></div>
          <div className="rubber-sides"><div><small>{tie.home_team.display_name}</small><b>{rubber.home_players.join(' / ') || '阵容待确认'}</b></div><em>{rubber.home_score ?? '—'} : {rubber.away_score ?? '—'}</em><div><small>{tie.away_team.display_name}</small><b>{rubber.away_players.join(' / ') || '阵容待确认'}</b></div></div>
          {!rubber.lineup_valid && rubber.lineup_invalid_reason && <p className="status-error">{rubber.lineup_invalid_reason}</p>}
          <div className="rubber-actions"><button className="btn small" disabled={busy || !rubber.permissions.can_edit_lineup} onClick={(event) => onLineup(rubber, event.currentTarget)}>设置阵容</button><button className="btn small" disabled={busy || !rubber.permissions.can_start} onClick={(event) => onStart(rubber, event.currentTarget)}>开始本盘</button><button className="btn small primary" disabled={busy || !rubber.permissions.can_record_score} onClick={(event) => onScore(rubber, event.currentTarget)}>录入比分</button></div>
          {(() => {
            const reasons = [
              (busy || !rubber.permissions.can_edit_lineup) && `设置阵容：${unavailableReason(busy)}`,
              (busy || !rubber.permissions.can_start) && `开始本盘：${unavailableReason(busy)}`,
              (busy || !rubber.permissions.can_record_score) && `录入比分：${unavailableReason(busy)}`,
            ].filter(Boolean)
            return reasons.length > 0 ? <p className="rubber-action-hint" role="status">{reasons.join('；')}</p> : null
          })()}
        </article>)}</div>
      )}
    </section>
  )
}
