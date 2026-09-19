import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Entry, GroupInfo, TeamGroupStandings, TeamStandingRow, TeamTie, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

type Filter = 'ALL' | 'WAITING' | 'PLAYING' | 'FINISHED'
type View = 'list' | 'matrix'
type TieSection = { key: string; title: string; items: TeamTie[] }
type MatrixGroup = {
  id: number
  title: string
  teams: Entry[]
  standings: Map<number, TeamStandingRow>
  ties: Map<string, TeamTie>
  provisional: boolean
  ambiguous: boolean
}

const filterLabels: Record<Filter, string> = {
  ALL: '全部', WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束',
}

const statusLabels: Record<TeamTie['status'], string> = {
  WAITING: '待开始', PLAYING: '进行中', FINISHED: '已结束',
}

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '无法加载团体对抗，请稍后重试'

const rankLabel = (standing?: TeamStandingRow) => {
  if (!standing) return '—'
  return standing.rank_start === standing.rank_end ? `${standing.rank_start}` : `${standing.rank_start}-${standing.rank_end}`
}

const pairKey = (leftId: number, rightId: number) => `${Math.min(leftId, rightId)}:${Math.max(leftId, rightId)}`

const orientedScore = (tie: TeamTie, rowTeamId: number) => (
  tie.entry_a_id === rowTeamId
    ? `${tie.team_a_score}:${tie.team_b_score}`
    : `${tie.team_b_score}:${tie.team_a_score}`
)

function compareTies(left: TeamTie, right: TeamTie): number {
  return left.round - right.round
    || (left.match_index ?? Number.MAX_SAFE_INTEGER) - (right.match_index ?? Number.MAX_SAFE_INTEGER)
    || left.id - right.id
}

function buildSections(items: TeamTie[], groupOf: Map<number, GroupInfo>): TieSection[] {
  const groupTies = new Map<number, TeamTie[]>()
  const ungrouped: TeamTie[] = []
  const knockout: TeamTie[] = []
  for (const tie of items) {
    if (tie.stage === 'KNOCKOUT') knockout.push(tie)
    else if (tie.group_id === null) ungrouped.push(tie)
    else groupTies.set(tie.group_id, [...(groupTies.get(tie.group_id) ?? []), tie])
  }
  const groupSections = [...groupTies.entries()]
    .sort(([left], [right]) => (groupOf.get(left)?.sort_order ?? Number.MAX_SAFE_INTEGER) - (groupOf.get(right)?.sort_order ?? Number.MAX_SAFE_INTEGER) || left - right)
    .map(([groupId, sectionItems]) => ({ key: `group-${groupId}`, title: groupOf.get(groupId)?.name ?? `小组 #${groupId}`, items: sectionItems.sort(compareTies) }))
  const result = [...groupSections]
  if (ungrouped.length) result.push({ key: 'ungrouped', title: '未分组对抗', items: ungrouped.sort(compareTies) })
  if (knockout.length) result.push({ key: 'knockout', title: '淘汰赛', items: knockout.sort(compareTies) })
  return result
}

function TeamMatrixCard({ group }: { group: MatrixGroup }) {
  return <section className="card team-matrix-card">
    <header className="team-matrix-card-header">
      <h2>{group.title}</h2>
      <div className="team-standings-badges">
        <span className={`team-tie-status ${group.provisional ? 'playing' : 'finished'}`}>
          {group.provisional ? '小组赛进行中' : '小组赛已完成'}
        </span>
        {group.ambiguous && <span className="team-tie-status waiting">并列未分</span>}
        <span className="team-matrix-count">{group.teams.length} 队</span>
      </div>
    </header>
    <div className="team-matrix-wrap">
      <table className="team-matrix-table">
        <thead>
          <tr>
            <th className="team-matrix-corner" scope="col"><span>队伍</span></th>
            {group.teams.map((team) => <th className="team-matrix-col-head" key={team.id} scope="col"><span>{team.display_name}</span></th>)}
            <th className="team-matrix-total-head" scope="col">积分</th>
            <th className="team-matrix-total-head" scope="col">名次</th>
          </tr>
        </thead>
        <tbody>
          {group.teams.map((rowTeam, rowIndex) => {
            const standing = group.standings.get(rowTeam.id)
            return <tr key={rowTeam.id} className={standing?.ambiguous ? 'is-ambiguous' : ''}>
              <th className="team-matrix-row-head" scope="row">
                <strong>{rowTeam.display_name}</strong>
                {rowTeam.status === 'WITHDRAWN' && <span className="withdrawn-badge">已退赛</span>}
              </th>
              {group.teams.map((columnTeam, columnIndex) => {
                if (rowTeam.id === columnTeam.id) return <td className="team-matrix-cell self" key={columnTeam.id} />
                if (rowIndex > columnIndex) return <td className="team-matrix-cell blank" key={columnTeam.id} />
                const tie = group.ties.get(pairKey(rowTeam.id, columnTeam.id))
                if (!tie) return <td className="team-matrix-cell blank" key={columnTeam.id}><span>—</span></td>
                const score = orientedScore(tie, rowTeam.id)
                return (
                  <td className={`team-matrix-cell ${tie.status.toLowerCase()}`} key={columnTeam.id}>
                    <Link
                      className="team-matrix-cell-link"
                      to={`/team-tie?tid=${tie.tournament_id}&tie=${tie.id}`}
                      aria-label={`${rowTeam.display_name} 对 ${columnTeam.display_name}，${statusLabels[tie.status]}，总比分 ${score}`}
                    >
                      {tie.status === 'WAITING' ? <span className="team-matrix-waiting">—</span> : <span className="team-matrix-score">{score}</span>}
                      {tie.status === 'PLAYING' && <i aria-hidden="true" />}
                    </Link>
                  </td>
                )
              })}
              <td className="team-matrix-total" data-label="积分">{standing?.match_points ?? '—'}</td>
              <td className="team-matrix-total rank" data-label="名次">{rankLabel(standing)}</td>
            </tr>
          })}
        </tbody>
      </table>
    </div>
  </section>
}

export default function TeamTiesPage() {
  const [params, setSearchParams] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const view: View = params.get('view') === 'matrix' ? 'matrix' : 'list'
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [teams, setTeams] = useState<Entry[]>([])
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [ties, setTies] = useState<TeamTie[]>([])
  const [standings, setStandings] = useState<TeamGroupStandings[]>([])
  const [filter, setFilter] = useState<Filter>('ALL')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const setView = (next: View) => {
    const nextParams = new URLSearchParams(params)
    if (next === 'matrix') nextParams.set('view', 'matrix')
    else nextParams.delete('view')
    setSearchParams(nextParams, { replace: true })
  }

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true)
    setError(null)
    try {
      const [nextTournament, nextTeams, grouping, nextTies, nextStandings] = await Promise.all([
        api.getTournament(tid), api.listTeams(tid), api.getGroups(tid), api.listTeamTies(tid), api.getTeamGroupStandings(tid),
      ])
      setTournament(nextTournament)
      setTeams(nextTeams)
      setGroups(grouping.groups)
      setTies(nextTies)
      setStandings(nextStandings)
    } catch (requestError) {
      setTournament(null)
      setTeams([])
      setGroups([])
      setTies([])
      setStandings([])
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
  const listSections = useMemo(() => buildSections(visible, groupOf), [groupOf, visible])
  const allSections = useMemo(() => buildSections(ties, groupOf), [groupOf, ties])
  const matrixGroups = useMemo<MatrixGroup[]>(() => {
    const teamsByGroup = new Map<number, Entry[]>()
    for (const team of teams) {
      if (team.entry_type !== 'TEAM' || team.group_id === null) continue
      teamsByGroup.set(team.group_id, [...(teamsByGroup.get(team.group_id) ?? []), team])
    }
    const tiesByGroup = new Map<number, TeamTie[]>()
    for (const tie of ties) {
      if (tie.group_id === null) continue
      tiesByGroup.set(tie.group_id, [...(tiesByGroup.get(tie.group_id) ?? []), tie])
    }
    const groupIds = [...new Set([...teamsByGroup.keys(), ...tiesByGroup.keys()])]
    const standingsById = new Map(standings.map((group) => [group.group_id, group]))
    return groupIds
      .sort((left, right) => (groupOf.get(left)?.sort_order ?? Number.MAX_SAFE_INTEGER) - (groupOf.get(right)?.sort_order ?? Number.MAX_SAFE_INTEGER) || left - right)
      .map((groupId) => {
        const groupTeams = (teamsByGroup.get(groupId) ?? []).sort((left, right) => left.sort_order - right.sort_order || left.id - right.id)
        const groupTies = tiesByGroup.get(groupId) ?? []
        const groupStandings = standingsById.get(groupId)
        return {
          id: groupId,
          title: groupOf.get(groupId)?.name ?? `小组 #${groupId}`,
          teams: groupTeams,
          standings: new Map((groupStandings?.standings ?? []).map((row) => [row.team_entry_id, row])),
          ties: new Map(groupTies.map((tie) => [pairKey(tie.entry_a_id, tie.entry_b_id), tie])),
          provisional: groupStandings?.provisional ?? false,
          ambiguous: groupStandings?.ambiguous ?? false,
        }
      })
      .filter((group) => group.teams.length > 1)
  }, [groupOf, standings, teams, ties])
  const otherSections = useMemo(
    () => allSections.filter((section) => section.key === 'ungrouped' || section.key === 'knockout'),
    [allSections],
  )

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
    <div className="team-ties-toolbar">
      <div className="team-ties-view-toggle" role="group" aria-label="对抗视图切换">
        <button type="button" className={view === 'list' ? 'active' : ''} aria-pressed={view === 'list'} onClick={() => setView('list')}>列表</button>
        <button type="button" className={view === 'matrix' ? 'active' : ''} aria-pressed={view === 'matrix'} onClick={() => setView('matrix')}>矩阵</button>
      </div>
      {view === 'list' && (
        <div className="team-ties-filters" aria-label="对抗状态筛选">
          {(Object.keys(filterLabels) as Filter[]).map((item) => <button key={item} className={filter === item ? 'active' : ''} aria-pressed={filter === item} onClick={() => setFilter(item)}>{filterLabels[item]} <span>{counts[item]}</span></button>)}
        </div>
      )}
    </div>
    {ties.length === 0 ? <section className="card team-ties-empty"><h2>尚无团体对抗</h2><p>名单和分组完成后，对抗由已批准的后端流程生成。本页不会创建或修改对抗。</p><Link className="btn" to={`/team-roster?tid=${tid}`}>返回队伍与名单</Link></section> : view === 'matrix' ? (
      <>
        {matrixGroups.length === 0 ? <section className="card team-ties-empty"><h2>尚无小组矩阵</h2><p>团队赛完成分组后，这里会显示小组交叉对阵矩阵。</p></section> : <div className="team-matrix-groups">{matrixGroups.map((group) => <TeamMatrixCard key={group.id} group={group} />)}</div>}
        {otherSections.length > 0 && <div className="team-ties-sections">{otherSections.map((section) => <section key={section.key} className="team-ties-section"><h2>{section.title}{' '}<span>{section.items.length} 场</span></h2><div className="team-ties-table-wrap"><table className="team-ties-table"><thead><tr><th>轮次</th><th>对阵</th><th>总比分</th><th>状态</th><th>操作</th></tr></thead><tbody>{section.items.map((tie) => <tr key={tie.id}><td data-label="轮次"><b>第 {tie.round} 轮</b>{tie.match_index !== null && <small>场次 {tie.match_index}</small>}</td><td data-label="对阵"><strong>{teamName(tie.entry_a_id)}</strong><span className="team-ties-versus">VS</span><strong>{teamName(tie.entry_b_id)}</strong></td><td data-label="总比分" className="team-ties-score">{tie.team_a_score} : {tie.team_b_score}</td><td data-label="状态"><span className={`team-tie-status ${tie.status.toLowerCase()}`}>{statusLabels[tie.status]}</span></td><td data-label="操作"><Link className="btn small" to={`/team-tie?tid=${tid}&tie=${tie.id}`}>进入对抗</Link></td></tr>)}</tbody></table></div></section>)}</div>}
      </>
    ) : listSections.length === 0 ? <section className="card team-ties-empty"><h2>没有符合筛选条件的对抗</h2><p>请切换状态筛选查看其他对抗。</p></section> : <div className="team-ties-sections">{listSections.map((section) => <section key={section.key} className="team-ties-section"><h2>{section.title}{' '}<span>{section.items.length} 场</span></h2><div className="team-ties-table-wrap"><table className="team-ties-table"><thead><tr><th>轮次</th><th>对阵</th><th>总比分</th><th>状态</th><th>操作</th></tr></thead><tbody>{section.items.map((tie) => <tr key={tie.id}><td data-label="轮次"><b>第 {tie.round} 轮</b>{tie.match_index !== null && <small>场次 {tie.match_index}</small>}</td><td data-label="对阵"><strong>{teamName(tie.entry_a_id)}</strong><span className="team-ties-versus">VS</span><strong>{teamName(tie.entry_b_id)}</strong></td><td data-label="总比分" className="team-ties-score">{tie.team_a_score} : {tie.team_b_score}</td><td data-label="状态"><span className={`team-tie-status ${tie.status.toLowerCase()}`}>{statusLabels[tie.status]}</span></td><td data-label="操作"><Link className="btn small" to={`/team-tie?tid=${tid}&tie=${tie.id}`}>进入对抗</Link></td></tr>)}</tbody></table></div></section>)}</div>}
  </div>
}
