import { TeamRubberView, TeamTieView } from '../../team/types'

const statusLabel: Record<TeamRubberView['status'], string> = {
  PENDING: '待阵容', READY: '可开始', PLAYING: '进行中', FINISHED: '已结束', SKIPPED: '不再进行',
}
const tieStatusLabel: Record<TeamTieView['status'], string> = { WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束' }

type RubberAction = 'lineup' | 'start' | 'score'

function unavailableReason(tie: TeamTieView, rubber: TeamRubberView, action: RubberAction, busy: boolean): string {
  if (busy) return '正在提交其他操作，请稍候'

  const actionName = action === 'lineup' ? '设置阵容' : action === 'start' ? '开始本盘' : '录入比分'
  if (rubber.status === 'SKIPPED') return `本盘因对抗已提前结束而跳过，不能${actionName}`
  if (rubber.status === 'FINISHED') {
    return action === 'score' ? '本盘已经结束，本版不支持改分' : `本盘已经结束，不能${actionName}`
  }
  if (tie.status === 'FINISHED') return `对抗已结束，不能${actionName}`

  if (action === 'lineup') {
    return rubber.status === 'PLAYING' ? '本盘正在进行中，不能修改阵容' : '当前盘次不能修改阵容'
  }
  if (action === 'score') return '请先开始本盘再录分'
  if (rubber.status === 'PENDING') return '请先提交本盘的合法阵容，再开始比赛'
  if (!rubber.lineup_valid && rubber.lineup_invalid_reason) return `${rubber.lineup_invalid_reason}，可重新提交阵容`
  if (rubber.status === 'PLAYING') return '本盘正在进行中，不能重复开始'

  const playing = tie.rubbers.find((item) => item.status === 'PLAYING')
  if (playing) return `第 ${playing.sequence} 盘正在进行中，同一对抗同时只能进行一盘`
  return '当前盘次暂不能开始，请以最新对抗状态为准'
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
            const reasons: string[] = []
            if (busy || !rubber.permissions.can_edit_lineup) reasons.push(`设置阵容：${unavailableReason(tie, rubber, 'lineup', busy)}`)
            if (busy || !rubber.permissions.can_start) reasons.push(`开始本盘：${unavailableReason(tie, rubber, 'start', busy)}`)
            if (busy || !rubber.permissions.can_record_score) reasons.push(`录入比分：${unavailableReason(tie, rubber, 'score', busy)}`)
            return reasons.length > 0 ? <p className="rubber-action-hint" role="status">{reasons.join('；')}</p> : null
          })()}
        </article>)}</div>
      )}
    </section>
  )
}
