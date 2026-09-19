import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import TeamScorePanel from '../components/team/TeamScorePanel'
import type { TeamRubberView, TeamTieView } from '../team/types'

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '团体对抗操作失败'
const tieStatusLabel: Record<TeamTieView['status'], string> = { WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束' }

// 后端在赛前名单变更后会保留旧阵容 id 以报告 lineup_valid=false，但候选列表只含当前队员。
// 打开编辑弹窗时必须丢弃不再可选的旧 id，否则用户无法通过 UI 修复阵容。
function retainCurrentPlayerIds(
  selectedIds: number[],
  options: TeamRubberView['lineup_options']['home'],
): number[] {
  const currentIds = new Set(options.filter((option) => option.available).map((option) => option.player_id))
  return selectedIds.filter((playerId) => currentIds.has(playerId))
}

export default function TeamTiePage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const rawTie = params.get('tie')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const tieId = rawTie ? Number(rawTie) : null
  const [tie, setTie] = useState<TeamTieView | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lineupRubber, setLineupRubber] = useState<TeamRubberView | null>(null)
  const [scoreRubber, setScoreRubber] = useState<TeamRubberView | null>(null)
  const [homeIds, setHomeIds] = useState<number[]>([])
  const [awayIds, setAwayIds] = useState<number[]>([])
  const [homeScore, setHomeScore] = useState('')
  const [awayScore, setAwayScore] = useState('')
  const restoreFocus = useRef<HTMLButtonElement | null>(null)
  const lineupClose = useRef<HTMLButtonElement | null>(null)
  const scoreClose = useRef<HTMLButtonElement | null>(null)
  const modalRoot = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid) || tieId === null || !Number.isInteger(tieId)) return
    setLoading(true)
    setError(null)
    try { setTie(await api.getTeamTie(tid, tieId)) } catch (requestError) { setTie(null); setError(messageOf(requestError)) } finally { setLoading(false) }
  }, [tid, tieId])

  useEffect(() => { void load() }, [load])
  const returnFocus = () => requestAnimationFrame(() => restoreFocus.current?.focus())
  const closeLineup = () => { setLineupRubber(null); returnFocus() }
  const closeScore = () => { setScoreRubber(null); returnFocus() }
  const dialogOpen = Boolean(lineupRubber || scoreRubber)
  useEffect(() => {
    if (!dialogOpen) return
    const app = document.querySelector<HTMLElement>('.app')
    if (!app) return
    app.inert = true
    return () => { app.inert = false }
  }, [dialogOpen])
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (!dialogOpen) return
      if (event.key === 'Escape') {
        event.preventDefault()
        if (lineupRubber) closeLineup()
        if (scoreRubber) closeScore()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = modalRoot.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), [href]')
      if (!focusable?.length) return
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', closeOnEscape)
    if (lineupRubber) lineupClose.current?.focus()
    if (scoreRubber) scoreClose.current?.focus()
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [dialogOpen, lineupRubber, scoreRubber])

  const openLineup = (rubber: TeamRubberView, trigger: HTMLButtonElement) => {
    restoreFocus.current = trigger
    setHomeIds(retainCurrentPlayerIds(rubber.home_player_ids, rubber.lineup_options.home))
    setAwayIds(retainCurrentPlayerIds(rubber.away_player_ids, rubber.lineup_options.away))
    setLineupRubber(rubber)
  }
  const openScore = (rubber: TeamRubberView, trigger: HTMLButtonElement) => {
    restoreFocus.current = trigger
    setHomeScore(rubber.home_score?.toString() ?? '')
    setAwayScore(rubber.away_score?.toString() ?? '')
    setScoreRubber(rubber)
  }
  const startRubber = (rubber: TeamRubberView, trigger: HTMLButtonElement) => {
    if (!window.confirm(`确定开始第 ${rubber.sequence} 盘吗？开始后将按已确认阵容和服务端规则进行。`)) {
      trigger.focus()
      return
    }
    void run(() => api.startTeamRubber(tid!, tie!.id, rubber.id))
  }
  const run = async (work: () => Promise<TeamTieView>, done?: () => void) => {
    setBusy(true); setError(null)
    try { setTie(await work()); done?.() } catch (requestError) { setError(messageOf(requestError)) } finally { setBusy(false) }
  }
  const toggle = (id: number, values: number[], setValues: (next: number[]) => void) =>
    setValues(values.includes(id) ? values.filter((value) => value !== id) : [...values, id])

  if (tid === null || !Number.isInteger(tid) || tieId === null || !Number.isInteger(tieId)) return <div className="card"><h2>团体对抗</h2><p className="muted">请从团体赛流程进入，或提供有效的 <code>tid</code> 与 <code>tie</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p className="muted">正在加载团体对抗运行态…</p></div>
  if (!tie) return <div className="card"><h2>团体对抗</h2><p className="status-error">{error ?? '未找到团体对抗'}</p><button className="btn" onClick={() => void load()}>重试</button></div>

  return <div className="page team-tie-page">
    <div className="team-mock-banner"><strong>运行态接口已连接</strong><span>盘次、阵容候选、权限、总比分与结束状态均由后端返回；生产赛事入口仍等待正式赛制登记。</span></div>
    <section className="team-tie-hero"><div><span className="eyebrow">TEAM TIE · {tie.stage}</span><h1>{tie.home_team.display_name} <i>VS</i> {tie.away_team.display_name}</h1><p>{tie.format.display_name ?? '赛制信息暂未登记'} · {tieStatusLabel[tie.status]} · 盘次顺序由服务端返回</p></div><div className="team-total-score"><small>当前总比分</small><b>{tie.home_score} : {tie.away_score}</b><span>{tie.target_wins == null ? '目标胜场暂不可用' : `先达 ${tie.target_wins} 胜`}</span></div></section>
    {error && <p className="status-error">{error}</p>}
    {tie.status === 'FINISHED' && <p className="status-warn">团体对抗结束。未进行盘次已按后端状态锁定。</p>}
    <TeamScorePanel tie={tie} busy={busy} onLineup={openLineup} onStart={startRubber} onScore={openScore} />
    <div className="button-row"><button className="btn" disabled={busy} onClick={() => void load()}>刷新</button><Link className="btn" to={`/team-ties?tid=${tid}`}>返回对抗列表</Link></div>
    {lineupRubber && createPortal(<div ref={modalRoot} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="team-lineup-title"><div className="modal team-modal"><button ref={lineupClose} className="modal-close" onClick={closeLineup} aria-label="关闭">×</button><h3 id="team-lineup-title">设置阵容 · 第 {lineupRubber.sequence} 盘</h3><p className="muted">候选范围与不可选原因均来自后端；提交后会以服务端返回的完整对抗状态替换页面。</p>{error && <p className="status-error" role="alert">{error}</p>}{(['home', 'away'] as const).map((side) => <div key={side}><h4>{side === 'home' ? tie.home_team.display_name : tie.away_team.display_name}</h4>{lineupRubber.lineup_options[side].map((option) => { const selected = side === 'home' ? homeIds : awayIds; const setSelected = side === 'home' ? setHomeIds : setAwayIds; return <label className="lineup-option" key={option.player_id}><input type="checkbox" disabled={!option.available || busy} checked={selected.includes(option.player_id)} onChange={() => toggle(option.player_id, selected, setSelected)} /><span>{option.name}</span><small>{option.available ? '可选择' : option.unavailable_reason}</small></label> })}</div>)}<div className="modal-actions"><button className="btn" onClick={closeLineup}>取消</button><button className="btn primary" disabled={busy || !lineupRubber.permissions.can_confirm_lineup} onClick={() => void run(() => api.setTeamLineup(tid, tie.id, lineupRubber.id, { home_player_ids: homeIds, away_player_ids: awayIds }), closeLineup)}>确认阵容</button></div></div></div>, document.body)}
    {scoreRubber && createPortal(<div ref={modalRoot} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="team-score-title"><div className="modal team-modal"><button ref={scoreClose} className="modal-close" onClick={closeScore} aria-label="关闭">×</button><h3 id="team-score-title">录入比分 · 第 {scoreRubber.sequence} 盘</h3><p className="muted">请输入本盘大比分。合法性由后端根据赛事局制校验。</p>{error && <p className="status-error" role="alert">{error}</p>}<div className="team-score-shell"><input aria-label="主队比分" inputMode="numeric" type="number" min="0" value={homeScore} onChange={(event) => setHomeScore(event.target.value)} disabled={busy} /><b>:</b><input aria-label="客队比分" inputMode="numeric" type="number" min="0" value={awayScore} onChange={(event) => setAwayScore(event.target.value)} disabled={busy} /></div><div className="modal-actions"><button className="btn" onClick={closeScore}>取消</button><button className="btn primary" disabled={busy || homeScore === '' || awayScore === ''} onClick={() => void run(() => api.recordTeamRubberScore(tid, tie.id, scoreRubber.id, { home_score: Number(homeScore), away_score: Number(awayScore) }), closeScore)}>提交比分</button></div></div></div>, document.body)}
  </div>
}
