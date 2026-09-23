import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, KnockoutMatch, KnockoutTree, normalizePlacementMatches, PlacementMatch, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import KnockoutBracket from '../components/KnockoutBracket'
import PublicEmptyState from '../components/PublicEmptyState'
import { getPublicCapabilities, isSingleElimination } from '../publicFormat'
import ScoreSheet from '../components/ScoreSheet'

type PlacementItem = PlacementMatch

function placementRoundLabel(item: PlacementItem) {
  const [min, max] = item.range
  if (min === 3 && max === 4) return '季军赛'
  const size = (max ?? min ?? 0) - (min ?? 0) + 1
  const totalRounds = size > 1 ? Math.log2(size) : 1
  if (item.match.round === totalRounds) return `${min}/${(min ?? 0) + 1} 名决胜`
  return `第 ${item.match.round} 轮`
}

/**
 * 淘汰赛 / 签表页。
 *
 * D 轨 Day 2：新增可选 `readOnly`。Public 路由（`/public/t/:tid/bracket`）以只读方式复用本页，
 * 只屏蔽**写操作与管理入口**（录入大比分、生成淘汰赛签表、季军赛录分、指向管理页的链接），
 * 签表结构与晋级展示完全沿用后端结果，不复制任何淘汰赛推进算法。
 *
 * D 轨 Day 4D：
 *
 * - Public 只读视图的「返回」不再指向管理端 `/`，改为回到本赛事的公开实况页；
 * - 「这里什么都没有」时给出可理解的空态 + CTA，而不是一句只对小组+淘汰赛成立的
 *   “小组赛对阵尚未发布”；
 * - 仍然只渲染后端返回的 `KnockoutTree`：不自己算 BYE / 种子 / 下一轮对阵 / 胜者晋级。
 *
 * D 轨 Day4D 接线轮（PR #50 review）：
 *
 * - Public 端先取 `getTournament(tid)` 拿到**后端权威的** `format_code`：
 *   `ROUND_ROBIN` 根本没有淘汰阶段，直接显示只读「不适用」状态，
 *   并且**不发** `/knockout` 请求；
 * - `SINGLE_ELIMINATION`：只渲染后端签表；它没有小组，因此连 `/rankings` 也不请求，
 *   也就不会出现「请先完成小组赛 / 每组前 N 名」这类只对 GROUP_KNOCKOUT 成立的文案；
 * - `GROUP_KNOCKOUT` 与 legacy(`null`)：请求序列与既有主链保持一致，行为不退化。
 */
export default function KnockoutPage({
  tid: tidProp,
  readOnly = false,
}: { tid?: number; readOnly?: boolean } = {}) {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  // tid 优先级：显式 prop（Public 路由的 path param）> ?tid= > localStorage（V0.2 兼容）
  const tid = tidProp ?? (urlTid ? Number(urlTid) : getActiveTournamentId())

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [rankings, setRankings] = useState<RankingsResult | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 生成签表失败的原因单独保存：它是"上一次点击"的结果，一旦数据刷新成功就必须消失，
  // 否则会和刷新后的真实状态互相矛盾（例如小组赛已经打完，却还挂着"请先完成小组赛"）。
  const [bracketError, setBracketError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState<KnockoutMatch | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return

    // 管理端：请求序列与既有实现完全一致，不因赛制变化而改动
    if (!readOnly) {
      const [t, k, r] = await Promise.all([
        api.getTournament(tid),
        api.getKnockout(tid),
        api.getRankings(tid),
      ])
      setTournament(t)
      setTree(k)
      setRankings(r)
      setBracketError(null)
      setLoaded(true)
      return
    }

    // Public 只读：先拿权威 format_code，再决定请求哪些数据
    const t = await api.getTournament(tid)
    setTournament(t)
    const capabilities = getPublicCapabilities(t.format_code)

    if (!capabilities.showBracket) {
      // 不适用：本赛事没有淘汰阶段，不请求 /knockout，也不伪造空签表
      setTree(null)
      setRankings(null)
      setBracketError(null)
      setLoaded(true)
      return
    }

    if (!capabilities.showRankings) {
      // 单淘汰：签表要拉，但没有小组，因此不请求 /rankings（避免 GK 专属文案与无意义请求）
      const k = await api.getKnockout(tid)
      setTree(k)
      setRankings(null)
      setBracketError(null)
      setLoaded(true)
      return
    }

    const [k, r] = await Promise.all([api.getKnockout(tid), api.getRankings(tid)])
    setTree(k)
    setRankings(r)
    setBracketError(null)
    setLoaded(true)
  }, [tid, readOnly])

  useEffect(() => {
    if (tid !== null) {
      setError(null)
      setBracketError(null)
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载淘汰赛失败'),
      )
    }
  }, [tid, load])

  const doGenerate = async () => {
    setError(null)
    setBracketError(null)
    setBusy(true)
    try {
      const k = await api.generateKnockout(tid as number)
      setTree(k)
      setTournament(k.tournament)
      // 生成成功后重新拉取排名：晋级名单与签表必须来自同一次刷新，避免半新半旧。
      setRankings(await api.getRankings(tid as number))
    } catch (e) {
      setBracketError(e instanceof ApiError ? e.message : '生成淘汰赛失败')
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
    setBracketError(null)
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

  // Public 只读 + 本赛事没有淘汰阶段（ROUND_ROBIN）：这是「不适用」，不是「还没有数据」。
  // 不渲染任何小组赛 / 晋级名额文案，也不伪造空签表。
  const capabilities = getPublicCapabilities(tournament?.format_code)
  const bracketNotApplicable = readOnly && tournament !== null && !capabilities.showBracket
  // 单淘汰赛制没有小组：禁止出现「请先完成小组赛」「每组前 N 名晋级」这类 GK 专属语义。
  const singleElimination = readOnly && isSingleElimination(tournament?.format_code)

  if (bracketNotApplicable) {
    return (
      <div className="page">
        <div className="card">
          <h2>
            {tournament ? tournament.name : '赛事'} · 淘汰赛
            <Link className="btn small float-right" to={`/public/t/${tid}/live`}>
              ← 返回实况
            </Link>
          </h2>
        </div>
        <PublicEmptyState
          title="本赛事采用循环赛制，不设置淘汰赛签表。"
          actions={[{ label: '查看排名', to: `/public/t/${tid}/rankings` }]}
        >
          <p>请查看赛事排名了解当前名次。</p>
        </PublicEmptyState>
      </div>
    )
  }

  // 小组赛完成 = 已分组、每组都有比赛、且每组所有比赛都已结束
  // （rankings 只统计 GROUP 赛段的比赛，淘汰赛生成后这个判定依然成立）
  const groupsAllDone =
    (rankings?.rankings.length ?? 0) > 0 &&
    rankings!.rankings.every((g) => g.finished_matches === g.total_matches && g.total_matches > 0)

  // 尚未完成的小组赛场数（用于提示）
  const remainingGroupMatches =
    rankings?.rankings.reduce((acc, g) => acc + (g.total_matches - g.finished_matches), 0) ?? 0
  // 晋级人数决定签表规模文案（4 组 × 2 人 = “8 强”，不写死 8 强）
  const qualifierCount =
    rankings?.rankings.reduce(
      (acc, group) => acc + group.entries.filter((entry) => entry.qualified).length,
      0,
    ) ?? 0
  // 小组赛已完成、但还没生成签表 = 这次刷新里的"可以生成淘汰赛"状态
  const awaitingBracket = groupsAllDone && tree !== null && tree.rounds.length === 0
  // 晋级线并列且尚未人工裁决：此时生成会被后端拒绝，提前说清楚，不要等用户点了才报红。
  const hasAmbiguousQualification =
    rankings?.rankings.some((g) => g.ambiguous_qualification) ?? false
  // 晋级人数不足以生成签表：每个小组都必须有 ≥1 名晋级者，且总数至少 2 人
  //（与后端 domain/knockout.build_bracket 的"没有可晋级的选手 / 每组至少需要 1 名晋级者"
  // 同一口径；这里只说清楚原因，真正的校验仍在服务端）。
  const qualifyingCounts = (rankings?.rankings ?? []).map(
    (g) => g.entries.filter((e) => e.qualified).length,
  )
  const bracketUnavailable =
    qualifyingCounts.length === 0 ||
    qualifyingCounts.some((count) => count === 0) ||
    qualifierCount < 2
  // 赛制说明使用每位选手真实的出线人数（各组可单独配置），不写死"每组前 2"。
  const qualifyCounts = [...new Set((rankings?.rankings ?? []).map((g) => g.qualify_count))]
  const qualifyPerGroupLabel = qualifyCounts.length <= 1
    ? `每组前 ${qualifyCounts[0] ?? tournament?.qualify_per_group ?? 2} 名晋级`
    : '各组晋级人数不一致'
  const roundLabels = (tree?.rounds ?? []).map((round) => round.label)
  const placementBands = Object.values(
    normalizePlacementMatches(tree?.placement_matches ?? []).reduce<Record<string, { range: PlacementItem['range']; items: PlacementItem[] }>>(
      (bands, item) => {
        const key = `${item.range[0]}-${item.range[1]}`
        if (!bands[key]) bands[key] = { range: item.range, items: [] }
        bands[key].items.push(item)
        return bands
      },
      {},
    ),
  )

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 淘汰赛
          {/* Public 只读视图不得把“返回首页”指向管理端 `/`（管理员控制台入口）。 */}
          <Link
            className="btn small float-right"
            to={readOnly ? `/public/t/${tid}/live` : '/'}
          >
            {readOnly ? '← 返回实况' : '← 返回首页'}
          </Link>
        </h2>
        {tournament && (
          <div className="section-heading">
            <p className="muted">阶段 <span className="badge">{tournament.stage}</span> · {tournament.bronze_mode === 'BRONZE_MATCH' ? '设季军赛' : '并列季军'} · {tournament.placement_mode === 'COMPLETE' ? '开启完整名次排位' : '常规名次'}</p>
            {!readOnly && <div className="button-row"><Link className="btn small" to={`/journey?tid=${tid}`}>冠军之路</Link><Link className="btn small" to={`/orderbook?tid=${tid}`}>打印秩序册</Link></div>}
          </div>
        )}
        {error && <p className="status-error">{error}</p>}
        {bracketError && <p className="status-error">{bracketError}</p>}
        {awaitingBracket && (
          <p className="muted">
            当前赛制：{qualifyPerGroupLabel}
            {qualifierCount > 0 ? `，共 ${qualifierCount} 人进入淘汰赛` : ''}
            {roundLabels.length > 0 ? `（${roundLabels.join(' / ')}）` : ''}。
          </p>
        )}
      </div>

      {/* 状态 C：签表已生成 → 只展示现有 Bracket，不再显示"生成淘汰赛"入口 */}
      {knockoutReady && (
        <>
          <KnockoutBracket
            rounds={tree!.rounds}
            champion={tree!.champion}
            runnerUp={tree!.runner_up}
            onScore={readOnly ? undefined : openScore}
          />
          {tree!.placement_matches.length > 0 && <section className="card placement-board">
            <div className="section-heading"><div><span className="eyebrow">PLACEMENT BRACKET</span><h3>季军与完整名次排位</h3></div><span className="muted">每个名次区间独立比赛，负者不会返回冠军主签</span></div>
            <div className="placement-bands">{placementBands.map(({ range, items }) => <section key={`${range[0]}-${range[1]}`} className="placement-band">
              <h4>{range[0] === 3 && range[1] === 4 ? '三四名决胜' : `${range[0]}–${range[1]} 名排位`}</h4>
              <div className="placement-match-grid">{items.map((item) => {
                const { match } = item
                return <article key={match.id} className="placement-match-card">
                  <span>{placementRoundLabel(item)}</span>
                  <strong>{match.player_a?.name ?? '待定'} <i>VS</i> {match.player_b?.name ?? '待定'}</strong>
                  {match.status === 'FINISHED' ? <small>{match.result_type !== 'NORMAL' ? 'W/O' : `${match.player_a_score}:${match.player_b_score}`} · 已结束</small> : match.player_a && match.player_b ? (readOnly ? <small>待录入比分</small> : <button className="btn small primary" onClick={() => openScore(match)}>录入大比分</button>) : <small>等待上一轮结果</small>}
                </article>
              })}</div>
            </section>)}</div>
          </section>}
          {tree!.placements.length > 0 && <section className="card final-placements"><h3>最终名次</h3><div>{tree!.placements.map((row, index) => <span key={index}><b>#{String(row.rank)}</b>{String((row.entry as { name?: string } | undefined)?.name ?? '待定')}<small>{String(row.label ?? '')}</small></span>)}</div></section>}
        </>
      )}

      {/* 状态 B：小组赛已全部结束、签表尚未生成 → 管理端显示"可以生成"；
          Public 只读视图只说明进度，不提供生成入口 */}
      {awaitingBracket && !bracketUnavailable && !readOnly && (
        <div className="card">
          <p className="status-ok">✅ 小组赛已全部完成。晋级名单已经确定，可以生成淘汰赛。</p>
          {hasAmbiguousQualification && (
            <p className="status-warn">
              仍有小组存在无法判定的并列晋级：请先在
              <Link to={`/rankings?tid=${tid}`}> 小组排名 </Link>
              页完成人工裁决，否则生成会被拒绝。
            </p>
          )}
          <div className="button-row">
            <button className="btn primary" onClick={doGenerate} disabled={busy}>
              {busy ? '处理中…' : '生成淘汰赛签表'}
            </button>
          </div>
        </div>
      )}

      {awaitingBracket && !bracketUnavailable && readOnly && (
        <div className="card">
          <p className="status-ok">✅ 小组赛已全部完成，晋级名单已确定。</p>
          <p className="muted">淘汰赛签表正在生成或等待裁判组发布，发布后本页会自动显示。</p>
        </div>
      )}

      {/* 状态 B 的例外：小组赛结束但晋级人数不足以生成签表（说清原因，而不是只报后端错误） */}
      {awaitingBracket && bracketUnavailable && (
        <div className="card">
          <p className="status-ok">✅ 小组赛已全部完成。</p>
          <p className="status-warn">
            但当前晋级人数不足以生成淘汰赛签表（每个小组都需要至少 1 名晋级者、总数至少 2 人）。
            {!readOnly && (
              <>
                请到<Link to={`/rankings?tid=${tid}`}> 小组排名 </Link>页确认各组出线人数后再生成。
              </>
            )}
          </p>
        </div>
      )}

      {/* 状态 A：还没有可展示的签表（小组赛未完成，或本赛事压根没有小组） */}
      {!knockoutReady && !groupsAllDone && (
        singleElimination ? (
          /* 单淘汰：没有小组，因此**不**说“小组赛尚未完成 / 每组前 N 名”，
             也不给“查看排名”这种指向不适用的 CTA（SE 没有循环赛排名）。 */
          <PublicEmptyState title="淘汰赛签表尚未发布">
            <p>本赛事采用单淘汰赛制，签表由裁判组生成后本页会自动显示。</p>
          </PublicEmptyState>
        ) : readOnly && remainingGroupMatches === 0 ? (
          /* Public 只读空态：此时本页一个字节的内容都没有。
             旧文案只说“小组赛对阵尚未发布”，而 V0.3 的循环赛 / 单淘汰赛事根本没有小组 ——
             这里刻意不推断赛制，只说明“本页暂无签表”，并给出仍然可用的替代视图。
             注意：不显示任何“生成签表”类入口，也不调用任何写接口。 */
          <PublicEmptyState
            title="暂无淘汰赛签表"
            hint="本赛事目前没有可展示的淘汰赛签表。"
            actions={[{ label: '查看排名', to: `/public/t/${tid}/rankings` }]}
          >
            <p>
              如果本赛事采用循环赛等不设淘汰赛的赛制，请以赛事排名为准；
              签表由裁判组发布后本页会自动显示。
            </p>
          </PublicEmptyState>
        ) : (
          <div className="card">
            <p className="muted">小组赛尚未完成</p>
            {remainingGroupMatches > 0 ? (
              readOnly ? (
                <p className="muted">
                  剩余 {remainingGroupMatches} 场比赛。全部结束后即进入淘汰赛阶段。
                </p>
              ) : (
                <p className="muted">
                  剩余 {remainingGroupMatches} 场比赛。请先在
                  <Link to={`/console?tid=${tid}`}> 比赛控制台 </Link>
                  录入比分，完成后即可生成淘汰赛。
                </p>
              )
            ) : (
              <p className="muted">
                请先在<Link to={`/players?tid=${tid}`}> 选手与分组 </Link>
                页完成分组并生成小组赛，再在<Link to={`/console?tid=${tid}`}> 比赛控制台 </Link>录入比分。
              </p>
            )}
          </div>
        )
      )}

      {modal && tournament && !readOnly && <ScoreSheet
        match={modal}
        sideA={modal.player_a?.name ?? '待定'}
        sideB={modal.player_b?.name ?? '待定'}
        gamesToWin={tournament.games_to_win}
        pointsToWin={tournament.points_to_win}
        busy={busy}
        auditMode="record"
        onClose={() => setModal(null)}
        onSave={submitScore}
      />}
    </div>
  )
}
