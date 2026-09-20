import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, TeamQualification, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '无法加载晋级确认，请稍后重试'

export default function TeamQualificationPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [qualification, setQualification] = useState<TeamQualification | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [boundarySelections, setBoundarySelections] = useState<Set<number>>(new Set())

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true); setError(null)
    try {
      const [nextTournament, nextQualification] = await Promise.all([api.getTournament(tid), api.getTeamQualification(tid)])
      setTournament(nextTournament); setQualification(nextQualification)
      setBoundarySelections(new Set(nextQualification.confirmed.map((team) => team.team_entry_id)))
    } catch (requestError) { setTournament(null); setQualification(null); setError(messageOf(requestError)) }
    finally { setLoading(false) }
  }, [tid])
  useEffect(() => { void load() }, [load])

  const confirm = async () => {
    if (tid === null || !qualification || qualification.blocked_reasons.length > 0) return
    setBusy(true); setError(null)
    try {
      const ids = qualification.groups.flatMap((group) => group.candidates
        .filter((candidate) => candidate.auto_qualified || (candidate.on_boundary_tie && boundarySelections.has(candidate.team_entry_id)))
        .map((candidate) => candidate.team_entry_id))
      setQualification(await api.confirmTeamQualification(tid, ids))
    } catch (requestError) { setError(messageOf(requestError)) }
    finally { setBusy(false) }
  }

  if (tid === null || !Number.isInteger(tid)) return <div className="card"><h2>团体晋级确认</h2><p>请提供有效的 <code>tid</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p aria-live="polite">正在加载团体晋级状态…</p></div>
  if (!tournament || !qualification) return <div className="card"><h2>团体晋级确认</h2><p className="status-error" role="alert">{error ?? '无法加载晋级确认'}</p><button className="btn" onClick={() => void load()}>重试</button></div>
  if (tournament.event_type !== 'TEAM') return <div className="card"><h2>团体晋级确认</h2><p className="status-error">当前赛事不是团体赛。</p><Link className="btn" to={`/?tid=${tid}`}>返回赛事首页</Link></div>

  const manualSelectionComplete = qualification.groups.every((group) => group.boundary_tied_team_ids.length === 0 || group.boundary_tied_team_ids.filter((id) => boundarySelections.has(id)).length === group.boundary_slots_remaining)
  const canSubmit = qualification.blocked_reasons.length === 0 && (qualification.can_confirm || manualSelectionComplete)

  return <div className="page">
    <header className="team-ties-header"><div><span className="eyebrow">TEAM QUALIFICATION</span><h1>{tournament.name} · 晋级确认</h1><p className="muted">候选、并列与可确认状态全部来自后端；本页不会自行判定排名或出线。</p></div><Link className="btn" to={`/team-rankings?tid=${tid}`}>返回团体排名</Link></header>
    {error && <p className="status-error" role="alert">{error}</p>}
    {qualification.blocked_reasons.length > 0 && <section className="card"><h2>暂不能确认晋级</h2><ul>{qualification.blocked_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul><Link className="btn" to={`/team-ties?tid=${tid}`}>查看团体对抗</Link></section>}
    {qualification.groups.map((group) => <section className="card" key={group.group_id}><h2>{group.group_name} · 前 {group.qualify_count} 名</h2><ul>{group.candidates.map((candidate) => candidate.on_boundary_tie ? <li key={candidate.team_entry_id}><label><input type="checkbox" disabled={busy || qualification.blocked_reasons.length > 0 || (!boundarySelections.has(candidate.team_entry_id) && group.boundary_tied_team_ids.filter((id) => boundarySelections.has(id)).length >= group.boundary_slots_remaining)} checked={boundarySelections.has(candidate.team_entry_id)} onChange={() => setBoundarySelections((current) => { const next = new Set(current); next.has(candidate.team_entry_id) ? next.delete(candidate.team_entry_id) : next.add(candidate.team_entry_id); return next })} /> {candidate.team_name}</label> · 晋级线并列，需人工选择</li> : <li key={candidate.team_entry_id}>{candidate.team_name} · {candidate.auto_qualified ? '可自动确认' : '不在晋级名额内'}</li>)}</ul>{group.boundary_tied_team_ids.length > 0 && <p className="muted">请从并列队伍中选择 {group.boundary_slots_remaining} 支。系统不提供推荐，最终合法性由后端校验。</p>}</section>)}
    {qualification.confirmed.length > 0 && <section className="card"><h2>已确认晋级</h2><ul>{qualification.confirmed.map((team) => <li key={team.team_entry_id}>{team.group_name ?? '未分组'} · {team.team_name}</li>)}</ul><Link className="btn primary" to={`/team-knockout?tid=${tid}`}>进入团体淘汰赛</Link></section>}
    <div className="button-row"><button className="btn" disabled={busy} onClick={() => void load()}>刷新</button><button className="btn primary" disabled={busy || !canSubmit} title={canSubmit ? undefined : qualification.blocked_reasons.join('；') || '请先完成晋级线并列队伍的人工选择'} onClick={() => void confirm()}>{qualification.requires_manual_resolution ? '确认选择的晋级名单' : '确认后端可自动判定的晋级名单'}</button></div>
  </div>
}
