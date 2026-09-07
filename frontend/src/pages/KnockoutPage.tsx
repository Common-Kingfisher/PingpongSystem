import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, KnockoutMatch, KnockoutTree, normalizePlacementMatches, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import KnockoutBracket from '../components/KnockoutBracket'
import ScoreSheet from '../components/ScoreSheet'

export default function KnockoutPage() {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  const tid = urlTid ? Number(urlTid) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [rankings, setRankings] = useState<RankingsResult | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState<KnockoutMatch | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, k, r] = await Promise.all([
      api.getTournament(tid),
      api.getKnockout(tid),
      api.getRankings(tid),
    ])
    setTournament(t)
    setTree(k)
    setRankings(r)
    setLoaded(true)
  }, [tid])

  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载淘汰赛失败'),
      )
    }
  }, [tid, load])

  const doGenerate = async () => {
    setError(null)
    setBusy(true)
    try {
      const k = await api.generateKnockout(tid as number)
      setTree(k)
      setTournament(k.tournament)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '生成淘汰赛失败')
    } finally {
      setBusy(false)
    }
  }

  const openScore = (m: KnockoutMatch) => {
    setModal(m)
  }

  const submitScore = async (payload: import('../api').ScorePayload) => {
    if (!modal) return
    setError(null)
    setBusy(true)
    try {
      await api.recordScore(modal.id, payload)
      setModal(null)
      await load() // 录分后立即刷新 → 胜者晋级下一轮
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '录入比分失败')
    } finally {
      setBusy(false)
    }
  }

  if (tid === null) {
    return (
      <div className="card">
        <h2>淘汰赛</h2>
        <p className="muted">
          请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。
        </p>
      </div>
    )
  }

  const knockoutReady = tree !== null && tree.rounds.length > 0

  if (!loaded && !error) {
    return (
      <div className="page">
        <div className="card">
          <h2>淘汰赛</h2>
          <p className="muted">正在加载赛事数据…</p>
        </div>
      </div>
    )
  }

  // 小组赛完成 = 已分组且每组所有比赛都已结束
  const groupsAllDone =
    (rankings?.rankings.length ?? 0) > 0 &&
    rankings!.rankings.every((g) => g.finished_matches === g.total_matches && g.total_matches > 0)

  // 尚未完成的小组赛场数（用于提示）
  const remainingGroupMatches =
    rankings?.rankings.reduce((acc, g) => acc + (g.total_matches - g.finished_matches), 0) ?? 0

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 淘汰赛
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        {tournament && (
          <div className="section-heading">
            <p className="muted">阶段 <span className="badge">{tournament.stage}</span> · {tournament.bronze_mode === 'BRONZE_MATCH' ? '设季军赛' : '并列季军'} · {tournament.placement_mode === 'COMPLETE' ? '开启完整名次排位' : '常规名次'}</p>
            <div className="button-row"><Link className="btn small" to={`/journey?tid=${tid}`}>冠军之路</Link><Link className="btn small" to={`/orderbook?tid=${tid}`}>打印秩序册</Link></div>
          </div>
        )}
        {error && <p className="status-error">{error}</p>}
      </div>

      {!knockoutReady && groupsAllDone && (
        <div className="card">
          <p className="status-ok">✅ 小组赛已全部完成，晋级名单已经确定，可以生成 8 强淘汰赛。</p>
          <div className="button-row">
            <button className="btn primary" onClick={doGenerate} disabled={busy}>
              {busy ? '处理中…' : '生成淘汰赛签表'}
            </button>
          </div>
        </div>
      )}

      {!knockoutReady && !groupsAllDone && (
        <div className="card">
          <p className="muted">淘汰赛尚不可生成</p>
          {remainingGroupMatches > 0 ? (
            <p className="muted">请先完成剩余 {remainingGroupMatches} 场小组赛。</p>
          ) : (
            <p className="muted">请先在「选手与分组」页完成分组并生成小组赛，再在「比赛控制台」录入比分。</p>
          )}
        </div>
      )}

      {knockoutReady && (
        <>
          <KnockoutBracket
            rounds={tree!.rounds}
            champion={tree!.champion}
            runnerUp={tree!.runner_up}
            onScore={openScore}
          />
          {(tree!.placement_matches ?? []).length > 0 && <section className="card placement-board">
            <div className="section-heading"><div><span className="eyebrow">PLACEMENT BRACKET</span><h3>季军与名次排位赛</h3></div><span className="muted">季军由半决赛负者直接对决，不按积分决定</span></div>
            <div className="placement-match-grid">{normalizePlacementMatches(tree!.placement_matches).map(({ range, match }) => <article key={match.id} className="placement-match-card">
              <span>{range[0] === 3 && range[1] === 4 ? '季军赛 · 三四名决胜' : range[0] === range[1] ? `第 ${range[0]} 名` : `${range[0]}–${range[1]} 名排位`}</span>
              <strong>{match.player_a?.name ?? '待定'} <i>VS</i> {match.player_b?.name ?? '待定'}</strong>
              {match.status === 'FINISHED' ? <small>{match.result_type !== 'NORMAL' ? 'W/O' : `${match.player_a_score}:${match.player_b_score}`} · 已结束</small> : match.player_a && match.player_b ? <button className="btn small primary" onClick={() => openScore(match)}>录入大比分</button> : <small>等待上一轮结果</small>}
            </article>)}</div>
          </section>}
          {(tree!.placements ?? []).length > 0 && <section className="card final-placements"><h3>最终名次</h3><div>{(tree!.placements ?? []).map((row, index) => <span key={index}><b>#{String(row.rank)}</b>{String((row.entry as { name?: string } | undefined)?.name ?? '待定')}<small>{String(row.label ?? '')}</small></span>)}</div></section>}
        </>
      )}

      {modal && tournament && <ScoreSheet
        match={modal}
        sideA={modal.player_a?.name ?? '待定'}
        sideB={modal.player_b?.name ?? '待定'}
        gamesToWin={tournament.games_to_win ?? 2}
        pointsToWin={tournament.points_to_win ?? 11}
        busy={busy}
        onClose={() => setModal(null)}
        onSave={submitScore}
      />}
    </div>
  )
}
