import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Match, RankingsResult, ScorePayload, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import ScoreSheet from '../components/ScoreSheet'

export default function RankingsPage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [rankings, setRankings] = useState<RankingsResult>({ rankings: [] })
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [matches, setMatches] = useState<Match[]>([])
  const [detailMatch, setDetailMatch] = useState<Match | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, r, ms] = await Promise.all([
      api.getTournament(tid),
      api.getRankings(tid),
      api.listMatches(tid, { stage: 'GROUP', status: 'FINISHED' }),
    ])
    setTournament(t)
    setRankings(r)
    setMatches(ms)
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

  const entryName = (id: number | null) => {
    if (id === null) return '待定'
    for (const group of rankings.rankings) {
      const entry = group.entries.find((item) => item.player_id === id)
      if (entry) return entry.name
    }
    return `#${id}`
  }

  const sideName = (match: Match, side: 'a' | 'b') =>
    (side === 'a' ? match.entry_a_name : match.entry_b_name)
    ?? entryName(side === 'a' ? match.player_a_id : match.player_b_id)

  const savePointScores = async (payload: ScorePayload) => {
    if (!detailMatch) return
    setBusy(true)
    setError(null)
    try {
      await api.reviseScore(detailMatch.id, payload)
      setDetailMatch(null)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '保存小分失败')
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
            各组出线人数可独立设置 · 排序：胜场 &gt; 净胜局 &gt; 积分；仍并列时按相互比赛与乒联小分比率判定
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
              · 前 {g.qualify_count} 名出线 · 已完成 {g.finished_matches}/{g.total_matches} 场
            </span>
            {g.finished_matches === g.total_matches && g.total_matches > 0 && (
              <span className="badge" style={{ marginLeft: 8 }}>
                小组赛完成
              </span>
            )}
          </h3>
          {g.needs_point_scores && <div className="ranking-tiebreak">
            <div><strong>出线席位仍同分，需要补录小分</strong><p>只补录下列相关场次的逐局比分。录齐后系统按相互比赛的得失分比率重新排名。</p></div>
            <div className="tiebreak-match-list">
              {g.point_score_match_ids.map((id) => {
                const match = matches.find((item) => item.id === id)
                if (!match) return null
                return <button className="btn small" key={id} onClick={() => setDetailMatch(match)}>
                  #{id} {sideName(match, 'a')} {match.player_a_score}:{match.player_b_score} {sideName(match, 'b')} · 补小分
                </button>
              })}
            </div>
          </div>}
          {g.ambiguous_qualification && !g.needs_point_scores && (
            <p className="status-error">⚠️ 已应用直接交锋和小分比率后仍无法区分，请由裁判长人工裁决。</p>
          )}
          <table className="data-table">
            <thead>
              <tr>
                <th>名次</th>
                <th>姓名</th>
                <th>胜</th>
                <th>负</th>
                <th>净胜局</th>
                <th>积分</th>
                <th>小分</th>
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
                  <td>{e.match_points}</td>
                  <td>{e.points_won || e.points_lost ? `${e.points_won}:${e.points_lost}` : '按需补录'}</td>
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
      {detailMatch && tournament && <ScoreSheet
        match={detailMatch}
        sideA={sideName(detailMatch, 'a')}
        sideB={sideName(detailMatch, 'b')}
        gamesToWin={tournament.games_to_win}
        pointsToWin={tournament.points_to_win}
        busy={busy}
        detailMode
        onClose={() => setDetailMatch(null)}
        onSave={savePointScores}
      />}
    </div>
  )
}
