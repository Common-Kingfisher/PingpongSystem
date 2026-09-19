import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, TeamGroupStandings, TeamStandingRow, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const positionStateLabels: Record<TeamStandingRow['qualification_position_state'], string> = {
  RESOLVED: '晋级线内',
  UNDECIDED: '待定',
  ELIGIBLE_ONLY: '晋级线外',
  UNKNOWN: '待定',
}

const positionStateClasses: Record<TeamStandingRow['qualification_position_state'], string> = {
  RESOLVED: 'resolved',
  UNDECIDED: 'undecided',
  ELIGIBLE_ONLY: 'ineligible',
  UNKNOWN: 'undecided',
}

function qualificationStateLabel(row: TeamStandingRow): string {
  if (row.qualification_position_state === 'ELIGIBLE_ONLY' && !row.eligible_for_qualification) {
    return '不可晋级'
  }
  return positionStateLabels[row.qualification_position_state]
}

const messageOf = (error: unknown) =>
  error instanceof ApiError ? error.message : '无法加载团体排名，请稍后重试'

function rankLabel(row: TeamStandingRow): string {
  return row.rank_start === row.rank_end ? `${row.rank_start}` : `${row.rank_start}-${row.rank_end}`
}

function GroupCard({ group }: { group: TeamGroupStandings }) {
  return (
    <section className="card team-standings-card">
      <header className="team-standings-card-header">
        <h2>{group.group_name}</h2>
        <div className="team-standings-badges">
          <span className={`team-tie-status ${group.provisional ? 'playing' : 'finished'}`}>
            {group.provisional ? '进行中 · 排名非最终' : '小组赛已完成'}
          </span>
          {group.ambiguous && (
            <span className="team-tie-status waiting">并列未分 · 区间名次</span>
          )}
          <span className="team-standings-line">晋级线：前 {group.qualify_count} 名</span>
        </div>
      </header>
      {group.ambiguous && (
        <p className="team-standings-note">
          并列队伍按规则仍不可区分，共享同一名次区间；系统不会擅自打破并列，人工裁定属于后续批次功能。
        </p>
      )}
      <div className="team-ties-table-wrap">
        <table className="team-ties-table team-standings-table">
          <thead>
            <tr>
              <th>名次</th>
              <th>队伍</th>
              <th>赛</th>
              <th>胜</th>
              <th>负</th>
              <th>积分</th>
              <th>盘 W/L</th>
              <th>局 W/L</th>
              <th>晋级位置</th>
            </tr>
          </thead>
          <tbody>
            {group.standings.map((row) => (
              <tr key={row.team_entry_id} className={row.ambiguous ? 'is-ambiguous' : ''}>
                <td data-label="名次">
                  <b>{rankLabel(row)}</b>
                  {row.ambiguous && <small>并列</small>}
                </td>
                <td data-label="队伍">
                  <strong>{row.team_name}</strong>
                  {row.status === 'WITHDRAWN' && <span className="withdrawn-badge">已退赛</span>}
                </td>
                <td data-label="赛">{row.ties_played}</td>
                <td data-label="胜">{row.ties_won}</td>
                <td data-label="负">{row.ties_lost}</td>
                <td data-label="积分" className="team-standings-points">{row.match_points}</td>
                <td data-label="盘 W/L">{row.rubber_wins}:{row.rubber_losses}</td>
                <td data-label="局 W/L">{row.games_won}:{row.games_lost}</td>
                <td data-label="晋级位置">
                  <span className={`team-standing-state ${positionStateClasses[row.qualification_position_state]}`}>
                    {qualificationStateLabel(row)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default function TeamRankingsPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [standings, setStandings] = useState<TeamGroupStandings[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true)
    setError(null)
    try {
      const [nextTournament, nextStandings] = await Promise.all([
        api.getTournament(tid),
        api.getTeamGroupStandings(tid),
      ])
      setTournament(nextTournament)
      setStandings(nextStandings)
    } catch (requestError) {
      setTournament(null)
      setStandings([])
      setError(messageOf(requestError))
    } finally {
      setLoading(false)
    }
  }, [tid])

  useEffect(() => { void load() }, [load])

  if (tid === null || !Number.isInteger(tid)) {
    return (
      <div className="card">
        <h2>团体排名</h2>
        <p className="muted">请提供有效的 <code>tid</code> 参数。</p>
        <Link className="btn" to="/">返回赛事首页</Link>
      </div>
    )
  }
  if (loading) return <div className="card"><p aria-live="polite">正在加载团体排名…</p></div>
  if (!tournament) {
    return (
      <div className="card">
        <h2>团体排名</h2>
        <p className="status-error" role="alert">{error ?? '无法加载团体排名'}</p>
        <button className="btn" onClick={() => void load()}>重试</button>
      </div>
    )
  }
  if (tournament.event_type !== 'TEAM') {
    return (
      <div className="card">
        <h2>团体排名</h2>
        <p className="status-error">当前赛事不是团体赛。个人赛的小组排名请前往「小组排名」。</p>
        <Link className="btn" to={`/rankings?tid=${tid}`}>前往小组排名</Link>
      </div>
    )
  }

  return (
    <div className="page team-standings-page">
      <header className="team-ties-header">
        <div>
          <span className="eyebrow">TEAM STANDINGS</span>
          <h1>{tournament.name} · 团体排名</h1>
          <p className="muted">
            只读事实排名：胜方 2 分、负方 1 分；并列队伍先按子集内积分重算，再依次比较盘 W/L 比率与局 W/L 比率。
          </p>
        </div>
        <div className="team-standings-header-actions">
          <button className="btn" onClick={() => void load()} disabled={loading}>刷新</button>
          <Link className="btn" to={`/team-ties?tid=${tid}`}>返回团体对抗</Link>
        </div>
      </header>
      {standings.length === 0 ? (
        <section className="card team-ties-empty">
          <h2>尚无小组排名</h2>
          <p>名单和分组完成后，团体小组排名会在这里自动出现。排名由后端从真实对抗事实重算，本页不做任何本地推导。</p>
          <Link className="btn" to={`/team-roster?tid=${tid}`}>前往队伍与名单</Link>
        </section>
      ) : (
        <div className="team-standings-groups">
          {standings.map((group) => <GroupCard key={group.group_id} group={group} />)}
        </div>
      )}
      {standings.length > 0 && (
        <p className="team-standings-footnote muted">
          仍不可区分的并列队伍共享名次区间（如第 2-4 名）；盘/局统计只计入已完成对抗中已完成且未跳过的单盘。
        </p>
      )}
    </div>
  )
}
