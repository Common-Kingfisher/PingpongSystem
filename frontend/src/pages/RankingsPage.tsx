import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, GroupRanking, Match, RankingsResult, ScorePayload, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import PublicEmptyState from '../components/PublicEmptyState'
import { getPublicCapabilities, getRankingsTitle } from '../publicFormat'
import ScoreSheet from '../components/ScoreSheet'

/**
 * 排名页。
 *
 * D 轨 Day 2：新增可选 `readOnly`。Public 路由（`/public/t/:tid/rankings`）以只读方式复用本页，
 * 只屏蔽**写操作控件**（Demo 模拟完成、补录小分、人工裁定 / 撤销裁定），
 * 排名展示完全沿用后端结果，不复制任何排名算法。
 *
 * D 轨 Day 4D：
 *
 * - Public 视图下标题由 `getRankingsTitle(format_code)` 给出：
 *   `GROUP_KNOCKOUT` → 小组排名；`ROUND_ROBIN` / `null`(legacy) → 赛事排名。
 *   管理端（非 readOnly）保持「小组排名」不变；
 * - 后端没有返回任何排名行时给出**可理解的空态 + CTA**，而不是一片空白；
 * - 仍然**不**在前端计算任何排名：本页只渲染 `RankingsResult` 里后端已排序的行。
 *
 * D 轨 Day4D 接线轮（PR #50 review）：
 *
 * - Public 端先取 `getTournament(tid)` 拿到**后端权威的** `format_code`，
 *   再决定是否请求排名数据：`SINGLE_ELIMINATION` 下根本没有循环赛排名，
 *   因此**不发** `/rankings` 与 GROUP 完赛查询，直接显示只读「不适用」状态；
 * - 赛制判断只来自 `getPublicCapabilities`，不看 stage、不看有没有小组，
 *   也不复制任何排名 / 晋级算法；
 * - 管理端（`readOnly=false`）行为与请求序列完全不变。
 */
export default function RankingsPage({
  tid: tidProp,
  readOnly = false,
}: { tid?: number; readOnly?: boolean } = {}) {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  // tid 优先级：显式 prop（Public 路由的 path param）> ?tid= > localStorage（V0.2 兼容）
  const tid = tidProp ?? (tidParam ? Number(tidParam) : getActiveTournamentId())

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [rankings, setRankings] = useState<RankingsResult>({ rankings: [] })
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [matches, setMatches] = useState<Match[]>([])
  const [detailMatch, setDetailMatch] = useState<Match | null>(null)
  const [decisionGroup, setDecisionGroup] = useState<GroupRanking | null>(null)
  const [decisionSelected, setDecisionSelected] = useState<number[]>([])
  const [decisionReason, setDecisionReason] = useState('')
  const [operatorName, setOperatorName] = useState(() => localStorage.getItem('pingpong_referee_name') ?? '')

  const load = useCallback(async () => {
    if (tid === null) return

    // 管理端：请求序列与既有实现完全一致（先并行拉全部），不因赛制变化而改动
    if (!readOnly) {
      const [t, r, ms] = await Promise.all([
        api.getTournament(tid),
        api.getRankings(tid),
        api.listMatches(tid, { stage: 'GROUP', status: 'FINISHED' }),
      ])
      setTournament(t)
      setRankings(r)
      setMatches(ms)
      setLoaded(true)
      return
    }

    // Public 只读：先用赛事本身拿到权威 format_code，再决定要不要请求排名数据
    const t = await api.getTournament(tid)
    setTournament(t)
    if (!getPublicCapabilities(t.format_code).showRankings) {
      // 不适用：不请求不适用的 group ranking / GROUP 完赛数据（避免无意义的 200 与误导性空表）
      setRankings({ rankings: [] })
      setMatches([])
      setLoaded(true)
      return
    }
    const [r, ms] = await Promise.all([
      api.getRankings(tid),
      api.listMatches(tid, { stage: 'GROUP', status: 'FINISHED' }),
    ])
    setRankings(r)
    setMatches(ms)
    setLoaded(true)
  }, [tid, readOnly])

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
      await api.reviseScore(detailMatch.id, payload as import('../api').ScoreRevisionPayload)
      setDetailMatch(null)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '保存小分失败')
    } finally {
      setBusy(false)
    }
  }

  const openDecision = (group: GroupRanking) => {
    setDecisionGroup(group)
    setDecisionSelected([])
    setDecisionReason('')
  }

  const toggleDecisionEntry = (entryId: number) => {
    setDecisionSelected((current) => current.includes(entryId)
      ? current.filter((id) => id !== entryId)
      : current.length < (decisionGroup?.manual_slots_remaining ?? 0)
        ? [...current, entryId]
        : current)
  }

  const saveDecision = async () => {
    if (!decisionGroup || tid === null) return
    setBusy(true)
    setError(null)
    try {
      await api.createQualificationDecision(tid, decisionGroup.group_id, {
        selected_entry_ids: decisionSelected,
        reason: decisionReason.trim(),
        operator_name: operatorName.trim(),
      })
      localStorage.setItem('pingpong_referee_name', operatorName.trim())
      setDecisionGroup(null)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '保存人工裁定失败')
    } finally {
      setBusy(false)
    }
  }

  const revokeDecision = async (group: GroupRanking) => {
    if (tid === null || !group.qualification_decision) return
    const reason = window.prompt('请输入撤销人工裁定的原因：')
    if (!reason) return
    const operator = operatorName.trim() || window.prompt('请输入当前主裁判姓名：')?.trim()
    if (!operator) return
    setBusy(true)
    setError(null)
    try {
      await api.revokeQualificationDecision(tid, group.group_id, {
        reason,
        operator_name: operator,
      })
      setOperatorName(operator)
      localStorage.setItem('pingpong_referee_name', operator)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '撤销人工裁定失败')
    } finally {
      setBusy(false)
    }
  }

  // Public 只读视图：标题与是否展示排名都由后端权威的 format_code 决定（见 publicFormat.ts）。
  // 管理端保持「小组排名」，不改动 C 轨既有界面。
  const capabilities = getPublicCapabilities(tournament?.format_code)
  const pageTitle = readOnly ? getRankingsTitle(tournament?.format_code) : '小组排名'
  // 单淘汰赛制没有循环赛排名：这是「不适用」，不是「还没有数据」。
  const rankingsNotApplicable = readOnly && tournament !== null && !capabilities.showRankings

  if (tid === null) {
    return (
      <div className="card">
        <h2>{pageTitle}</h2>
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
          <h2>{pageTitle}</h2>
          <p className="muted">正在加载赛事数据…</p>
        </div>
      </div>
    )
  }

  if (rankingsNotApplicable) {
    return (
      <div className="page">
        <div className="card">
          <h2>
            {tournament ? tournament.name : '赛事'} · {pageTitle}
            <Link className="btn small float-right" to={`/public/t/${tid}/live`}>
              ← 返回实况
            </Link>
          </h2>
        </div>
        {/* 明确说明「本赛事不设循环赛排名」，而不是显示空白小组或伪造排名。
            文案只陈述后端契约事实，不推断任何比赛结果。 */}
        <PublicEmptyState
          title="本赛事采用单淘汰赛制，不设置循环赛排名。"
          actions={[{ label: '查看签表', to: `/public/t/${tid}/bracket` }]}
        >
          <p>请查看淘汰赛签表了解晋级情况。</p>
        </PublicEmptyState>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · {pageTitle}
          {/* Public 只读视图绝不能把“返回首页”指向管理端 `/`：那是管理员控制台入口。
              这里改为回到本赛事的公开实况页（保持 path param，不退回 ?tid=/localStorage）。 */}
          <Link
            className="btn small float-right"
            to={readOnly ? `/public/t/${tid}/live` : '/'}
          >
            {readOnly ? '← 返回实况' : '← 返回首页'}
          </Link>
        </h2>
        {tournament && (
          <p className="muted">
            各组出线人数可独立设置 · 排序：胜场 &gt; 净胜局 &gt; 积分；仍并列时按相互比赛与乒联小分比率判定
            {' '}· <span className={`badge mode-badge ${tournament.operation_mode === 'LIVE' ? 'live' : 'demo'}`}>
              {tournament.operation_mode === 'LIVE' ? '正式赛事' : '演示赛事'}
            </span>
          </p>
        )}
        {error && <p className="status-error">{error}</p>}
        {!readOnly && tournament?.operation_mode === 'DEMO' && tournament.stage === 'GROUP_STAGE' &&
          rankings.rankings.some((g) => g.finished_matches < g.total_matches) && (
            <div className="button-row">
              <button className="btn" onClick={confirmDemoFinish} disabled={busy}>
                <span className="demo-tag">Demo</span> 模拟完成剩余小组赛
              </button>
            </div>
          )}
      </div>

      {/* Public 只读空态：后端没有返回任何排名行时不要留一片空白。
          文案对三种赛制都成立（不推断赛制、不伪造排名、不调用任何写接口）。 */}
      {readOnly && loaded && rankings.rankings.length === 0 && (
        <PublicEmptyState
          title="暂无赛事排名"
          hint="本赛事目前还没有可发布的排名数据。"
          actions={[{ label: '查看签表', to: `/public/t/${tid}/bracket` }]}
        >
          <p>
            如果本赛事采用单淘汰等不设循环赛排名的赛制，本页不会显示排名；
            请打开签表查看对阵与晋级情况。
          </p>
        </PublicEmptyState>
      )}

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
          {g.needs_point_scores && !readOnly && <div className="ranking-tiebreak">
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
          {/* Public 只读视图：不提供补小分入口，但必须让观众知道“排名尚未最终确定”的原因 */}
          {g.needs_point_scores && readOnly && (
            <div className="ranking-tiebreak">
              <div>
                <strong>出线席位仍同分</strong>
                <p>该组需要在相关场次补齐逐局小分后才能最终确定排名与晋级名单，请等待裁判组处理。</p>
              </div>
            </div>
          )}
          {g.ambiguous_qualification && !g.needs_point_scores && !readOnly && (
            <div className="ranking-decision-callout">
              <div><strong>晋级线仍无法区分</strong><p>系统不会擅自选择。请主裁判从并列参赛位中指定 {g.manual_slots_remaining} 个晋级名额，并记录依据。</p></div>
              <button className="btn primary" onClick={() => openDecision(g)} disabled={busy}>主裁判人工裁定</button>
            </div>
          )}
          {g.ambiguous_qualification && !g.needs_point_scores && readOnly && (
            <div className="ranking-decision-callout">
              <div>
                <strong>晋级线尚待裁定</strong>
                <p>该组存在无法自动区分的并列，需由主裁判裁定 {g.manual_slots_remaining} 个晋级名额，结果确定后本页会自动更新。</p>
              </div>
            </div>
          )}
          {g.manually_resolved && g.qualification_decision && (
            <div className="ranking-decision-record">
              <div><strong>已由主裁判完成人工裁定</strong><p>{g.qualification_decision.operator_name} · {g.qualification_decision.created_at} · {g.qualification_decision.reason}</p></div>
              {!readOnly && <button className="btn small" onClick={() => revokeDecision(g)} disabled={busy}>撤销裁定</button>}
            </div>
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
                  <td>{e.name} {e.entry_status === 'WITHDRAWN' && <span className="withdrawn-badge">已退赛</span>}</td>
                  <td>{e.wins}</td>
                  <td>{e.losses}</td>
                  <td>{e.games_won - e.games_lost}</td>
                  <td>{e.match_points}</td>
                  <td>{e.points_won || e.points_lost ? `${e.points_won}:${e.points_lost}` : '按需补录'}</td>
                  <td>
                    {e.entry_status === 'WITHDRAWN' ? (
                      <span className="muted">不参与晋级</span>
                    ) : e.qualified ? (
                      <span className="status-ok">✅ {g.qualification_decision?.selected_entry_ids.includes(e.player_id) ? '裁定晋级' : '晋级'}</span>
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
      {detailMatch && tournament && !readOnly && <ScoreSheet
        match={detailMatch}
        sideA={sideName(detailMatch, 'a')}
        sideB={sideName(detailMatch, 'b')}
        gamesToWin={tournament.games_to_win}
        pointsToWin={tournament.points_to_win}
        busy={busy}
        detailMode
        auditMode="revise"
        onClose={() => setDetailMatch(null)}
        onSave={savePointScores}
      />}
      {decisionGroup && !readOnly && (
        <div className="modal-overlay" onClick={() => setDecisionGroup(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>{decisionGroup.group_name} · 人工指定晋级</h3>
            <p className="status-warn">仅解决当前晋级线并列。相关比赛成绩或出线人数变化后，本裁定会自动失效。</p>
            <p>请选择 <strong>{decisionGroup.manual_slots_remaining}</strong> 个参赛位：</p>
            <div className="decision-candidate-list">
              {decisionGroup.entries
                .filter((entry) => decisionGroup.manual_candidate_entry_ids.includes(entry.player_id))
                .map((entry) => (
                  <label key={entry.player_id}>
                    <input
                      type="checkbox"
                      checked={decisionSelected.includes(entry.player_id)}
                      onChange={() => toggleDecisionEntry(entry.player_id)}
                    />
                    <span>{entry.name}</span><small>并列第 {entry.rank} 名</small>
                  </label>
                ))}
            </div>
            <label>裁定理由
              <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="必填：如现场抽签、组委会确认或赛事规程条款" />
            </label>
            <label>操作者（主裁判）
              <input value={operatorName} onChange={(event) => setOperatorName(event.target.value)} placeholder="必填：姓名" />
            </label>
            <div className="modal-actions">
              <button className="btn" onClick={() => setDecisionGroup(null)}>取消</button>
              <button
                className="btn primary"
                onClick={saveDecision}
                disabled={busy || decisionSelected.length !== decisionGroup.manual_slots_remaining || decisionReason.trim().length < 2 || !operatorName.trim()}
              >确认并记录裁定</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
