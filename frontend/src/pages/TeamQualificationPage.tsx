import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, TeamQualification, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '无法加载团体晋级状态，请稍后重试'

export default function TeamQualificationPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [qualification, setQualification] = useState<TeamQualification | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true)
    setError(null)
    try {
      const [nextTournament, nextQualification] = await Promise.all([api.getTournament(tid), api.getTeamQualification(tid)])
      setTournament(nextTournament)
      setQualification(nextQualification)
      const confirmed = nextQualification.confirmed.map((item) => item.team_entry_id)
      setSelected(new Set(confirmed.length ? confirmed : nextQualification.groups.flatMap((group) => group.auto_qualified_team_ids)))
    } catch (requestError) {
      setTournament(null)
      setQualification(null)
      setError(messageOf(requestError))
    } finally { setLoading(false) }
  }, [tid])

  useEffect(() => { void load() }, [load])

  const selectionComplete = useMemo(() => qualification?.groups.every((group) => (
    group.candidates.filter((candidate) => selected.has(candidate.team_entry_id)).length === group.qualify_count
  )) ?? false, [qualification, selected])

  const toggle = (teamId: number) => setSelected((current) => {
    const next = new Set(current)
    if (next.has(teamId)) next.delete(teamId)
    else next.add(teamId)
    return next
  })

  const confirm = async () => {
    if (tid === null || !qualification || !selectionComplete) return
    setSubmitting(true)
    setError(null)
    try {
      const next = await api.confirmTeamQualification(tid, [...selected])
      setQualification(next)
      setSelected(new Set(next.confirmed.map((item) => item.team_entry_id)))
    } catch (requestError) { setError(messageOf(requestError)) }
    finally { setSubmitting(false) }
  }

  if (tid === null || !Number.isInteger(tid)) return <div className="card"><h2>团体晋级确认</h2><p className="muted">请提供有效的 <code>tid</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p aria-live="polite">正在加载团体晋级状态…</p></div>
  if (!tournament || !qualification) return <div className="card"><h2>团体晋级确认</h2><p className="status-error" role="alert">{error ?? '无法加载团体晋级状态'}</p><button className="btn" onClick={() => void load()}>重试</button></div>
  if (tournament.event_type !== 'TEAM') return <div className="card"><h2>团体晋级确认</h2><p className="status-error">当前赛事不是团体赛。</p><Link className="btn" to={`/rankings?tid=${tid}`}>前往小组排名</Link></div>

  const confirmed = qualification.confirmed.length > 0
  const blocked = qualification.blocked_reasons.length > 0
  return <div className="page team-qualification-page">
    <header className="team-ties-header">
      <div><span className="eyebrow">TEAM QUALIFICATION</span><h1>{tournament.name} · 晋级确认</h1><p className="muted">排名、候选范围和跨线并列均由后端计算；本页只提交主裁选择的全量晋级名单。</p></div>
      <div className="button-row"><button className="btn" onClick={() => void load()} disabled={loading || submitting}>刷新</button><Link className="btn" to={`/team-rankings?tid=${tid}`}>返回团体排名</Link></div>
    </header>
    {error && <p className="status-error" role="alert">{error}</p>}
    {qualification.blocked_reasons.length > 0 && <section className="card team-qualification-notice"><h2>当前不能确认</h2><ul>{qualification.blocked_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}
    {qualification.requires_manual_resolution && <p className="status-warn">存在跨晋级线并列：请只从标为“需人工取舍”的候选中选择剩余席位。系统不会按队伍编号或展示顺序自动决定。</p>}
    <div className="team-qualification-groups">
      {qualification.groups.map((group) => <section className="card team-qualification-group" key={group.group_id}>
        <header><div><h2>{group.group_name}</h2><p className="muted">晋级名额：{group.qualify_count}；{group.provisional ? '小组赛尚未完成' : group.requires_manual_resolution ? `剩余人工席位：${group.boundary_slots_remaining}` : '名次已确定'}</p></div>{group.confirmed_team_ids.length > 0 && <span className="team-tie-status finished">已确认</span>}</header>
        {group.blocked_reasons.length > 0 && <ul className="team-qualification-reasons">{group.blocked_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
        <div className="team-qualification-candidates" role="group" aria-label={`${group.group_name} 晋级队伍`}>
          {group.candidates.map((candidate) => {
            const locked = candidate.auto_qualified
            const checked = selected.has(candidate.team_entry_id)
            return <label className={`team-qualification-candidate ${candidate.on_boundary_tie ? 'boundary' : ''}`} key={candidate.team_entry_id}>
              <input type="checkbox" checked={checked} disabled={locked || blocked || submitting} onChange={() => toggle(candidate.team_entry_id)} />
              <span><strong>{candidate.team_name}</strong><small>{candidate.auto_qualified ? '名次完全在晋级线内' : candidate.on_boundary_tie ? '需人工取舍' : '可晋级候选'}</small></span>
            </label>
          })}
        </div>
      </section>)}
    </div>
    <section className="card team-qualification-submit">
      <div><h2>{confirmed ? '已确认晋级名单' : '确认晋级名单'}</h2><p className="muted">确认会以当前选择全量替换已有结果；服务端会在写入时重新核验排名和并列状态。</p></div>
      <button className="btn primary" disabled={blocked || !selectionComplete || submitting} onClick={() => void confirm()}>{submitting ? '正在确认…' : confirmed ? '更新晋级名单' : '确认晋级名单'}</button>
    </section>
    {confirmed && <section className="card team-qualification-confirmed"><h2>已确认队伍</h2><ul>{qualification.confirmed.map((item) => <li key={item.team_entry_id}>{item.group_name ?? '未分组'} · <strong>{item.team_name}</strong></li>)}</ul><Link className="btn" to={`/team-knockout?tid=${tid}`}>前往团体淘汰签</Link></section>}
  </div>
}
