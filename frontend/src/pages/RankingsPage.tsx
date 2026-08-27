import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

export default function RankingsPage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [rankings, setRankings] = useState<RankingsResult>({ rankings: [] })
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, r] = await Promise.all([api.getTournament(tid), api.getRankings(tid)])
    setTournament(t)
    setRankings(r)
    setLoaded(true)
  }, [tid])

  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载排名失败'),
      )
    }
  }, [tid, load])

  const confirmDemoFinish = async () => {
    if (
      !window.confirm(
        'Demo 模式\n\n将自动生成所有未完成小组赛的比赛结果（随机比分）。\n此功能仅用于快速演示。',
      )
    )
      return
    setError(null)
    setBusy(true)
    try {
      await api.finishGroupStage(tid as number)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '模拟失败')
    } finally {
      setBusy(false)
    }
  }

  if (tid === null) {
    return (
      <div className="card">
        <h2>小组排名</h2>
        <p className="muted">
          请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。
        </p>
      </div>
    )
  }

  if (!loaded && !error) {
    return (
      <div className="page">
        <div className="card">
          <h2>小组排名</h2>
          <p className="muted">正在加载赛事数据…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 小组排名
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        {tournament && (
          <p className="muted">
            每组晋级 {tournament.qualify_per_group} 人 · Demo 排名规则：胜场 &gt; 净胜局
          </p>
        )}
        {error && <p className="status-error">{error}</p>}
        {tournament?.stage === 'GROUP_STAGE' &&
          rankings.rankings.some((g) => g.finished_matches < g.total_matches) && (
            <div className="button-row">
              <button className="btn" onClick={confirmDemoFinish} disabled={busy}>
                <span className="demo-tag">Demo</span> 模拟完成剩余小组赛
              </button>
            </div>
          )}
      </div>

      {rankings.rankings.map((g) => (
        <div className="card" key={g.group_id}>
          <h3>
            {g.group_name}
            <span className="muted">
              {' '}
              · 已完成 {g.finished_matches}/{g.total_matches} 场
            </span>
            {g.finished_matches === g.total_matches && g.total_matches > 0 && (
              <span className="badge" style={{ marginLeft: 8 }}>
                小组赛完成
              </span>
            )}
          </h3>
          {g.ambiguous_qualification && (
            <p className="status-error">
              ⚠️ 晋级线附近存在无法判定的并列（循环胜负），请人工裁决后再继续。
            </p>
          )}
          <table className="data-table">
            <thead>
              <tr>
                <th>名次</th>
                <th>姓名</th>
                <th>胜</th>
                <th>负</th>
                <th>净胜局</th>
                <th>是否晋级</th>
              </tr>
            </thead>
            <tbody>
              {g.entries.map((e) => (
                <tr key={e.player_id}>
                  <td>
                    {e.rank}
                    {e.tied && <span title="并列，未分先后"> *</span>}
                  </td>
                  <td>{e.name}</td>
                  <td>{e.wins}</td>
                  <td>{e.losses}</td>
                  <td>{e.games_won - e.games_lost}</td>
                  <td>
                    {e.qualified ? (
                      <span className="status-ok">✅ 晋级</span>
                    ) : g.finished_matches === g.total_matches && g.total_matches > 0 ? (
                      '—'
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
