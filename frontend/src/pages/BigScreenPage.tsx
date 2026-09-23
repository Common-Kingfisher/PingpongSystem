import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Dashboard, Entry, KnockoutTree, Player, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import KnockoutBracket from '../components/KnockoutBracket'
import { getPublicCapabilities, getPublicMatchStageLabel, getPublicStageLabel, isRoundRobin } from '../publicFormat'

/**
 * 赛事大屏（Public `/public/t/:tid/live` 与管理端 `/bigscreen` 共用）。
 *
 * D 轨 Day4D 接线轮（PR #50 review）：
 *
 * - 先取 `getTournament(tid)` 拿到**后端权威的** `format_code`，再按
 *   `getPublicCapabilities` 决定要不要请求 `rankings` / `knockout`
 *   —— 这只是 UI 数据选择，不是复制后端规则；
 * - `GROUP_KNOCKOUT` / legacy(`null`)：行为与请求集合不变（小组出线区 + 签表 + 冠军）；
 * - `ROUND_ROBIN`：当前比赛 / 进度 / 球台 / 即将开始 / 赛事排名，
 *   **不**渲染签表与出线区，结束时展示最终赛事排名，不伪造冠军；
 * - `SINGLE_ELIMINATION`：当前比赛 / 进度 / 球台 / 签表 / 冠军，
 *   **不**渲染小组出线区；
 * - 冠军只来自后端 `KnockoutTree.champion`，前端不推断、不补造。
 */
export default function BigScreenPage({ tid: tidProp }: { tid?: number } = {}) {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  // tid 优先级：显式 prop（Public 路由的 path param）> ?tid= > localStorage（V0.2 兼容）
  const tid = tidProp ?? (urlTid ? Number(urlTid) : getActiveTournamentId())

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [entries, setEntries] = useState<Entry[]>([])
  const [rankings, setRankings] = useState<RankingsResult | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return

    // 通用数据：任何赛制都需要
    const [t, d, ps, es] = await Promise.all([
      api.getTournament(tid),
      api.getDashboard(tid),
      api.listPlayers(tid),
      api.listEntries(tid),
    ])
    setTournament(t)
    setDash(d)
    setPlayers(ps)
    setEntries(es)

    // 按赛制只请求“适用”的数据：循环赛没有签表，单淘汰没有循环赛排名
    const capabilities = getPublicCapabilities(t.format_code)
    const [r, k] = await Promise.all([
      capabilities.showRankings ? api.getRankings(tid) : Promise.resolve(null),
      capabilities.showBracket || capabilities.showChampion ? api.getKnockout(tid) : Promise.resolve(null),
    ])
    setRankings(r)
    setTree(k)
    setLoaded(true)
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
    (entryId: number | null, playerId: number | null = null) =>
      entries.find((entry) => entry.id === entryId)?.display_name ??
      players.find((player) => player.id === playerId)?.name ?? '待定',
    [entries, players],
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

  if (!loaded && !error) {
    return (
      <div className="bigscreen">
        <div className="bigscreen-header">
          <h1>赛事大屏</h1>
        </div>
        <p className="muted">正在加载赛事数据…</p>
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

  // 赛制只由后端 format_code 决定（见 publicFormat.ts）；legacy(null) 保持“全部可见 + 数据驱动”
  const capabilities = getPublicCapabilities(tournament?.format_code)
  const roundRobin = isRoundRobin(tournament?.format_code)

  return (
    <div className="bigscreen">
      <div className="bigscreen-header">
        <h1>{tournament ? tournament.name : '赛事大屏'}</h1>
        <div className="bigscreen-stage">
          当前阶段：{getPublicStageLabel(tournament?.format_code, tournament?.stage)}
        </div>
        {capabilities.showChampion && stage === 'FINISHED' && tree?.champion && (
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
                  <div>{nameOf(tb.match!.entry_a_id ?? null, tb.match!.player_a_id)}</div>
                  <div className="bigscreen-vs">VS</div>
                  <div>{nameOf(tb.match!.entry_b_id ?? null, tb.match!.player_b_id)}</div>
                </div>
                <div className="muted">
                  {/* 赛段文案按赛制映射：纯循环赛的 GROUP 比赛显示「循环赛」，
                      避免与顶部阶段徽标（循环赛）自相矛盾。后端 stage 枚举不变。 */}
                  {getPublicMatchStageLabel(tournament?.format_code, tb.match!.stage)}
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
                  {nameOf(m.entry_a_id ?? null, m.player_a_id)} VS {nameOf(m.entry_b_id ?? null, m.player_b_id)}
                </li>
              ))}
            </ul>
          </div>
          {/* 单淘汰没有循环赛排名（showRankings=false）→ 不渲染出线区；
              循环赛没有“出线”概念 → 标题用中性的「赛事排名」。 */}
          {capabilities.showRankings && (
            <div className="bigscreen-col">
              <h2>{roundRobin ? '赛事排名' : '小组排名（出线区）'}</h2>
              {(rankings?.rankings ?? []).map((g) => (
                <div key={g.group_id} className="bigscreen-group">
                  {!roundRobin && <div className="bigscreen-group-name">{g.group_name}</div>}
                  {g.entries.slice(0, roundRobin ? g.entries.length : g.qualify_count).map((e) => (
                    <div key={e.player_id}>
                      {e.rank}. {e.name}
                      {!roundRobin && e.qualified && <span className="status-ok"> ✓</span>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {capabilities.showBracket && knockoutReady && (
        <div className="bigscreen-knockout">
          <KnockoutBracket
            rounds={tree!.rounds}
            champion={tree!.champion}
            runnerUp={tree!.runner_up}
            large
          />
        </div>
      )}

      {/* 已结束、且本赛事没有淘汰赛签表（例如循环赛制：没有决赛，名次本身就是最终成绩）时，
          展示后端发布的赛事排名。这里不推断赛制、不计算名次、不补造冠军。
          单淘汰（showRankings=false）不走这里：它没有循环赛排名，只显示签表与冠军。
          有淘汰赛签表的赛事仍走上面的冠军 / 签表分支，行为不变。 */}
      {capabilities.showRankings && stage === 'FINISHED' && !knockoutReady && (rankings?.rankings.length ?? 0) > 0 && (
        <div className="bigscreen-cols">
          <div className="bigscreen-col">
            <h2>赛事排名</h2>
            {rankings!.rankings.map((g) => (
              <div key={g.group_id} className="bigscreen-group">
                {!roundRobin && <div className="bigscreen-group-name">{g.group_name}</div>}
                {g.entries.map((e) => (
                  <div key={e.player_id}>
                    {e.rank}. {e.name}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {capabilities.showBracket && !knockoutReady && stage === 'KNOCKOUT' && (
        <p className="muted">淘汰赛尚未生成。</p>
      )}
    </div>
  )
}
