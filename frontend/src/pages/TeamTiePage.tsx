import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import TeamScorePanel from '../components/team/TeamScorePanel'
import { teamTieMocks } from '../mocks/teamTie'
import { TeamRubberView } from '../team/types'

export default function TeamTiePage() {
  const [params] = useSearchParams()
  const fixture = params.get('fixture')
  const key = fixture && Object.prototype.hasOwnProperty.call(teamTieMocks, fixture) ? fixture as keyof typeof teamTieMocks : 'waiting'
  const tie = teamTieMocks[key]
  const [lineupRubber, setLineupRubber] = useState<TeamRubberView | null>(null)
  const [scoreRubber, setScoreRubber] = useState<TeamRubberView | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const restoreFocus = useRef<HTMLButtonElement | null>(null)
  const lineupClose = useRef<HTMLButtonElement | null>(null)
  const scoreClose = useRef<HTMLButtonElement | null>(null)
  const returnFocus = () => requestAnimationFrame(() => restoreFocus.current?.focus())
  const closeLineup = () => { setLineupRubber(null); returnFocus() }
  const closeScore = () => { setScoreRubber(null); returnFocus() }
  const openLineup = (rubber: TeamRubberView, trigger: HTMLButtonElement) => { restoreFocus.current = trigger; setSelected([]); setLineupRubber(rubber) }
  const openScore = (rubber: TeamRubberView, trigger: HTMLButtonElement) => { restoreFocus.current = trigger; setScoreRubber(rubber) }
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (lineupRubber) closeLineup()
        if (scoreRubber) closeScore()
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    if (lineupRubber) lineupClose.current?.focus()
    if (scoreRubber) scoreClose.current?.focus()
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [lineupRubber, scoreRubber])
  return <div className="page team-tie-page">
    <div className="team-mock-banner"><strong>Mock UI 模式</strong><span>仅用于运行态 Contract 与交互状态验收；未连接真实团体 API，生产 TEAM 入口继续禁用。</span></div>
    <section className="team-tie-hero"><div><span className="eyebrow">TEAM TIE · {tie.stage}</span><h1>{tie.home_team.display_name} <i>VS</i> {tie.away_team.display_name}</h1><p>{tie.format.display_name ?? '赛制信息等待后端返回'} · 盘次顺序由 rubbers[] 动态提供</p></div><div className="team-total-score"><small>当前总比分</small><b>{tie.home_score} : {tie.away_score}</b><span>{tie.target_wins === null ? '目标胜场待规则冻结' : `先达 ${tie.target_wins} 胜`}</span></div></section>
    {tie.status === 'FINISHED' && <p className="status-warn">团体对抗结束。剩余盘次的状态与可操作性仅由后端返回决定。</p>}
    <div className="team-fixtures" aria-label="Mock 场景切换">{Object.keys(teamTieMocks).map((name) => <Link key={name} className={`btn small ${name === key ? 'primary' : ''}`} to={`/team-tie?fixture=${name}`}>{name}</Link>)}</div>
    <TeamScorePanel tie={tie} onLineup={openLineup} onScore={openScore} />
    <Link className="btn" to="/">返回赛事首页</Link>
    {lineupRubber && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="team-lineup-title"><div className="modal team-modal"><button ref={lineupClose} className="modal-close" onClick={closeLineup} aria-label="关闭">×</button><h3 id="team-lineup-title">设置阵容 · 第 {lineupRubber.sequence} 盘</h3><p className="muted">选项及禁用原因来自 Mock Contract；真实校验将由后端负责。</p>{lineupRubber.lineup_options.map((option) => <label className="lineup-option" key={option.player_id}><input type="checkbox" disabled={!option.available} checked={selected.includes(option.player_id)} onChange={() => setSelected((current) => current.includes(option.player_id) ? current.filter((id) => id !== option.player_id) : [...current, option.player_id])} /><span>{option.name}</span><small>{option.available ? '可选择' : option.unavailable_reason}</small></label>)}<div className="modal-actions"><button className="btn" onClick={closeLineup}>取消</button><button className="btn primary" disabled={!lineupRubber.permissions.can_confirm_lineup} onClick={closeLineup}>确认（Mock）</button></div></div></div>}
    {scoreRubber && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="team-score-title"><div className="modal team-modal"><button ref={scoreClose} className="modal-close" onClick={closeScore} aria-label="关闭">×</button><h3 id="team-score-title">录入比分 · 第 {scoreRubber.sequence} 盘</h3><p className="muted">真实逐盘录分将在 A4 Runtime API 与规则冻结后接入；此处不提交比赛结果。</p><div className="team-score-shell"><input aria-label="主队比分" inputMode="numeric" placeholder="—" disabled /><b>:</b><input aria-label="客队比分" inputMode="numeric" placeholder="—" disabled /></div><div className="modal-actions"><button className="btn" onClick={closeScore}>关闭</button></div></div></div>}
  </div>
}
