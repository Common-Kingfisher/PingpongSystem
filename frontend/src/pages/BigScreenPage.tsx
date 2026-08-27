import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Dashboard, KnockoutTree, Player, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import KnockoutBracket from '../components/KnockoutBracket'

export default function BigScreenPage() {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  const tid = urlTid ? Number(urlTid) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [rankings, setRankings] = useState<RankingsResult | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, d, ps, r, k] = await Promise.all([
      api.getTournament(tid),
      api.getDashboard(tid),
      api.listPlayers(tid),
      api.getRankings(tid),
      api.getKnockout(tid),
    ])
    setTournament(t)
    setDash(d)
    setPlayers(ps)
    setRankings(r)
    setTree(k)
  }, [tid])

  // 初始加载：失败时展示错误
  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载大屏失败'),
      )
    }
  }, [tid, load])

  // 轻量轮询（约 2s）：单次失败不白屏、不设持久错误，下一轮自动恢复；卸载时清理
  useEffect(() => {
    if (tid === null) return
    let cancelled = false
    const interval = setInterval(() => {
      if (cancelled) return
      load().catch(() => {
        /* 忽略瞬时失败，保留上次数据 */
      })
    }, 2000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [tid, load])

  const nameOf = useCallback(
    (id: number | null) => players.find((p) => p.id === id)?.name ?? '待定',
    [players],
  )

  if (tid === null) {
    return (
      <div className="card">
        <h2>赛事大屏</h2>
        <p className="muted">
          请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。
        </p>
      </div>
    )
  }

  const stage = tournament?.stage ?? 'REGISTRATION'
  const stats = dash?.stats
  const progress = stats ? Math.round((stats.finished / Math.max(1, stats.total)) * 100) : 0
  const playing = dash?.tables.filter((t) => t.match) ?? []
  const idle = dash?.tables.filter((t) => !t.match) ?? []
  const upcoming = dash?.next_playable.slice(0, 8) ?? []
  const knockoutReady = (tree?.rounds.length ?? 0) > 0

  return (
    <div className="bigscreen">
      <div className="bigscreen-header">
        <h1>{tournament ? tournament.name : '赛事大屏'}</h1>
        <div className="bigscreen-stage">
          当前阶段：
          {stage === 'REGISTRATION' && '报名中'}
          {stage === 'GROUP_STAGE' && '小组赛'}
          {stage === 'KNOCKOUT' && '淘汰赛'}
          {stage === 'FINISHED' && '已结束'}
        </div>
        {stage === 'FINISHED' && tree?.champion && (
          <div className="bigscreen-champion">
            <span className="bigscreen-trophy">🏆</span> {tree.champion.name ?? '冠军'}
            {tree.runner_up && <span className="bigscreen-sub">亚军：{tree.runner_up.name ?? '—'}</span>}
          </div>
        )}
        {error && <p className="status-error">{error}</p>}
      </div>

      {stats && (
        <div className="bigscreen-progress">
          <div className="bigscreen-progress-bar">
            <div className="bigscreen-progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <span>
            比赛进度 {stats.finished} / {stats.total}（{progress}%）
          </span>
        </div>
      )}

      {(stage === 'GROUP_STAGE' || stage === 'KNOCKOUT') && (
        <div className="bigscreen-playing">
          <h2>正在进行</h2>
          {playing.length === 0 && <p className="muted">当前没有比赛在进行。</p>}
          <div className="bigscreen-tables">
            {playing.map((tb) => (
              <div className="bigscreen-table" key={tb.id}>
                <div className="bigscreen-table-name">{tb.name}</div>
                <div className="bigscreen-pair">
                  <div>{nameOf(tb.match!.player_a_id)}</div>
                  <div className="bigscreen-vs">VS</div>
                  <div>{nameOf(tb.match!.player_b_id)}</div>
                </div>
                <div className="muted">
                  {tb.match!.stage === 'GROUP' ? '小组赛' : '淘汰赛'}
                  {tb.match!.player_a_score !== null && (
                    <span> · {tb.match!.player_a_score} : {tb.match!.player_b_score}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {idle.length > 0 && (
        <div className="bigscreen-idle">
          {idle.map((tb) => (
            <span key={tb.id} className="bigscreen-idle-table">
              {tb.name} 空闲
            </span>
          ))}
        </div>
      )}

      {stage === 'GROUP_STAGE' && (
        <div className="bigscreen-cols">
          <div className="bigscreen-col">
            <h2>即将开始</h2>
            {upcoming.length === 0 && <p className="muted">暂无可进行的比赛。</p>}
            <ul className="bigscreen-upcoming">
              {upcoming.map((m) => (
                <li key={m.id}>
                  {nameOf(m.player_a_id)} VS {nameOf(m.player_b_id)}
                </li>
              ))}
            </ul>
          </div>
          <div className="bigscreen-col">
            <h2>小组排名（前两名）</h2>
            {(rankings?.rankings ?? []).map((g) => (
              <div key={g.group_id} className="bigscreen-group">
                <div className="bigscreen-group-name">{g.group_name}</div>
                {g.entries.slice(0, 2).map((e) => (
                  <div key={e.player_id}>
                    {e.rank}. {e.name}
                    {e.qualified && <span className="status-ok"> ✓</span>}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {knockoutReady && (
        <div className="bigscreen-knockout">
          <KnockoutBracket
            rounds={tree!.rounds}
            champion={tree!.champion}
            runnerUp={tree!.runner_up}
            large
          />
        </div>
      )}

      {!knockoutReady && stage === 'KNOCKOUT' && (
        <p className="muted">淘汰赛尚未生成。</p>
      )}
    </div>
  )
}
