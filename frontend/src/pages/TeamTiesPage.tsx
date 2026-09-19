import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Entry, GroupInfo, TeamTie, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

type Filter = 'ALL' | 'WAITING' | 'PLAYING' | 'FINISHED'

const filterLabels: Record<Filter, string> = {
  ALL: '全部', WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束',
}

const statusLabels: Record<TeamTie['status'], string> = {
  WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束',
}

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '无法加载团体对抗，请稍后重试'

function compareTies(left: TeamTie, right: TeamTie): number {
  return left.round - right.round
    || (left.match_index ?? Number.MAX_SAFE_INTEGER) - (right.match_index ?? Number.MAX_SAFE_INTEGER)
    || left.id - right.id
}

export default function TeamTiesPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [teams, setTeams] = useState<Entry[]>([])
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [ties, setTies] = useState<TeamTie[]>([])
  const [filter, setFilter] = useState<Filter>('ALL')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true)
    setError(null)
    try {
      const [nextTournament, nextTeams, grouping, nextTies] = await Promise.all([
        api.getTournament(tid), api.listTeams(tid), api.getGroups(tid), api.listTeamTies(tid),
      ])
      setTournament(nextTournament)
      setTeams(nextTeams)
      setGroups(grouping.groups)
      setTies(nextTies)
    } catch (requestError) {
      setTournament(null)
      setTeams([])
      setGroups([])
      setTies([])
      setError(messageOf(requestError))
    } finally {
      setLoading(false)
    }
  }, [tid])

  useEffect(() => { void load() }, [load])

  const teamNameOf = useMemo(() => new Map(teams.map((team) => [team.id, team.display_name])), [teams])
  const groupOf = useMemo(() => new Map(groups.map((group) => [group.id, group])), [groups])
  const counts = useMemo(() => ({
    ALL: ties.length,
    WAITING: ties.filter((tie) => tie.status === 'WAITING').length,
    PLAYING: ties.filter((tie) => tie.status === 'PLAYING').length,
    FINISHED: ties.filter((tie) => tie.status === 'FINISHED').length,
  }), [ties])
  const visible = useMemo(
    () => ties.filter((tie) => filter === 'ALL' || tie.status === filter),
    [filter, ties],
  )
  const sections = useMemo(() => {
    const groupTies = new Map<number, TeamTie[]>()
    const ungrouped: TeamTie[] = []
    const knockout: TeamTie[] = []
    for (const tie of visible) {
      if (tie.stage === 'KNOCKOUT') knockout.push(tie)
      else if (tie.group_id === null) ungrouped.push(tie)
      else groupTies.set(tie.group_id, [...(groupTies.get(tie.group_id) ?? []), tie])
    }
    const groupSections = [...groupTies.entries()]
      .sort(([left], [right]) => (groupOf.get(left)?.sort_order ?? Number.MAX_SAFE_INTEGER) - (groupOf.get(right)?.sort_order ?? Number.MAX_SAFE_INTEGER) || left - right)
      .map(([groupId, items]) => ({ key: `group-${groupId}`, title: groupOf.get(groupId)?.name ?? `小组 #${groupId}`, items: items.sort(compareTies) }))
    const result = [...groupSections]
    if (ungrouped.length) result.push({ key: 'ungrouped', title: '未分组对抗', items: ungrouped.sort(compareTies) })
    if (knockout.length) result.push({ key: 'knockout', title: '淘汰赛', items: knockout.sort(compareTies) })
    return result
  }, [groupOf, visible])

  if (tid === null || !Number.isInteger(tid)) return <div className="card"><h2>团体对抗</h2><p className="muted">请提供有效的 <code>tid</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p aria-live="polite">正在加载团体对抗…</p></div>
  if (!tournament) return <div className="card"><h2>团体对抗</h2><p className="status-error" role="alert">{error ?? '无法加载团体对抗'}</p><button className="btn" onClick={() => void load()}>重试</button></div>
  if (tournament.event_type !== 'TEAM') return <div className="card"><h2>团体对抗</h2><p className="status-error">当前赛事不是团体赛，不能查看团体对抗。</p><Link className="btn" to={`/?tid=${tid}`}>返回赛事首页</Link></div>

  const teamName = (entryId: number) => teamNameOf.get(entryId) ?? `队伍 #${entryId}`
  return <div className="page team-ties-page">
    <header className="team-ties-header">
      <div><span className="eyebrow">TEAM TIES</span><h1>{tournament.name} · 团体对抗</h1><p className="muted">对抗顺序、状态与比分均来自服务端；本页不推导赛制或胜负规则。</p></div>
      <Link className="btn" to={`/team-roster?tid=${tid}`}>返回队伍与名单</Link>
    </header>
    <div className="team-ties-filters" aria-label="对抗状态筛选">
      {(Object.keys(filterLabels) as Filter[]).map((item) => <button key={item} className={filter === item ? 'active' : ''} aria-pressed={filter === item} onClick={() => setFilter(item)}>{filterLabels[item]} <span>{counts[item]}</span></button>)}
    </div>
    {ties.length === 0 ? <section className="card team-ties-empty"><h2>尚无团体对抗</h2><p>名单和分组完成后，对抗由已批准的后端流程生成。本页不会创建或修改对抗。</p><Link className="btn" to={`/team-roster?tid=${tid}`}>返回队伍与名单</Link></section> : sections.length === 0 ? <section className="card team-ties-empty"><h2>没有符合筛选条件的对抗</h2><p>请切换状态筛选查看其他对抗。</p></section> : <div className="team-ties-sections">{sections.map((section) => <section key={section.key} className="team-ties-section"><h2>{section.title}{' '}<span>{section.items.length} 场</span></h2><div className="team-ties-table-wrap"><table className="team-ties-table"><thead><tr><th>轮次</th><th>对阵</th><th>总比分</th><th>状态</th><th>操作</th></tr></thead><tbody>{section.items.map((tie) => <tr key={tie.id}><td data-label="轮次"><b>第 {tie.round} 轮</b>{tie.match_index !== null && <small>场次 {tie.match_index}</small>}</td><td data-label="对阵"><strong>{teamName(tie.entry_a_id)}</strong><span className="team-ties-versus">VS</span><strong>{teamName(tie.entry_b_id)}</strong></td><td data-label="总比分" className="team-ties-score">{tie.team_a_score} : {tie.team_b_score}</td><td data-label="状态"><span className={`team-tie-status ${tie.status.toLowerCase()}`}>{statusLabels[tie.status]}</span></td><td data-label="操作"><Link className="btn small" to={`/team-tie?tid=${tid}&tie=${tie.id}`}>进入对抗</Link></td></tr>)}</tbody></table></div></section>)}</div>}
  </div>
}
