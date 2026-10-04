import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Dashboard, Match, Player, ScheduleEstimateMatch, ScoreAudit, TableWithMatch, Tournament } from '../api'
import { getActiveTournamentId, parseTournamentId } from '../activeTournament'
import ScoreSheet from '../components/ScoreSheet'
import LiveTableCard from '../components/LiveTableCard'
import QueueEstimate from '../components/field/QueueEstimate'
import { matchSidesReady, matchStageLabel } from '../mobileScore'
import { tournamentStageLabel } from '../format'
import {
  CONSOLE_POLL_INTERVAL_MS,
  assignDisabledReason,
  canAssignMatches,
  canScheduleBatch,
  completionNotice,
  recommendedMatchForTable,
  sortTablesByNumber,
} from '../fieldOps'

export interface ConsoleFeedback {
  tone: 'success' | 'warning' | 'danger'
  title: string
  message: string
}

/** 只分层展示 transport / HTTP 结果；业务文案仍以服务端 message 为权威。 */
export function consoleErrorFeedback(error: unknown, fallback = '操作失败'): ConsoleFeedback {
  if (!(error instanceof ApiError)) {
    return { tone: 'danger', title: '操作未完成', message: fallback }
  }
  if (error.status === 409) {
    return { tone: 'warning', title: '比赛状态已变化', message: error.message }
  }
  if (error.status === 422) {
    return { tone: 'warning', title: '提交内容未通过校验', message: error.message }
  }
  if (error.status === 401 || error.status === 403) {
    return { tone: 'danger', title: '当前账号不能执行此操作', message: error.message }
  }
  if (error.status >= 500) {
    return { tone: 'danger', title: '服务暂时不可用', message: error.message }
  }
  return { tone: 'danger', title: '操作未完成', message: error.message }
}

/**
 * 现场状态快照。
 *
 * 团体赛（TEAM）不进入普通 Match Console：此时只保留 `tournament`，
 * 其余字段为空且不会发起 Dashboard 请求（见第 11 节 TEAM 硬边界）。
 */
interface ConsoleSnapshot {
  tournament: Tournament
  dashboard: Dashboard | null
  players: Player[]
  finished: Match[]
  waiting: Match[]
  groupNames: Record<number, string>
  estimates: Map<number, ScheduleEstimateMatch>
}

export default function ConsolePage() {
  const [params] = useSearchParams()
  const tid = parseTournamentId(params.get('tid')) ?? getActiveTournamentId()

  const [snapshot, setSnapshot] = useState<ConsoleSnapshot | null>(null)
  const [initialError, setInitialError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [stale, setStale] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null)
  const snapshotRef = useRef<ConsoleSnapshot | null>(null)

  /**
   * C-D5 review rework（PR #66 Warning 1）：每一次 refresh 必须绑定到"发起它的那一次 tid"。
   *
   * `refresh` 是 `useCallback([tid])`，tid 变化时会生成新闭包，但**旧闭包发起的在途请求
   * 不受影响**：它解析后仍会无条件 `setSnapshot` / `setLastSyncedAt`。于是
   * `/console?tid=1` → 切到 `?tid=2` → 旧响应回来时，新赛事的 URL 下会短暂显示旧赛事的
   * 比赛进度、球台与比分 —— 现场页面显示错误数据会直接诱发误操作，且 5 秒轮询让
   * "任意时刻都有在途请求"成为常态，暴露面远大于旧版（旧版没有轮询）。
   *
   * 守卫由两个 ref 组成：
   * - `activeTidRef`：当前真正生效的赛事 id（tid 变化时更新）；
   * - `requestGenerationRef`：请求代次，tid 每变化一次自增，用于识别"同一 tid 的上一代请求"。
   *
   * 任何异步返回在提交状态前都要重新确认自己仍属于当前 tid 与当前代次，否则整段丢弃 ——
   * 包括 `catch` 与 `finally`，它们同样不得改动新赛事的状态。
   */
  const activeTidRef = useRef<number | null>(tid)
  const requestGenerationRef = useRef(0)

  /**
   * 在途请求去重必须按 `(tid, generation)` 记账，不能用全局 boolean：
   * 旧赛事的请求还在途时，新赛事的第一次 refresh 不能被它挡掉（否则新赛事会空转一轮）。
   */
  const requestInFlightRef = useRef<{ tid: number; generation: number } | null>(null)

  const [feedback, setFeedback] = useState<ConsoleFeedback | null>(null)
  const [busy, setBusy] = useState(false)
  const [scoringMatch, setScoringMatch] = useState<Match | null>(null)
  const [scoreMode, setScoreMode] = useState<'record' | 'revise'>('record')
  const [scoreDetailMode, setScoreDetailMode] = useState(false)
  const [scoreSubmitError, setScoreSubmitError] = useState<ConsoleFeedback | null>(null)
  const [auditMatch, setAuditMatch] = useState<Match | null>(null)
  const [audits, setAudits] = useState<ScoreAudit[]>([])
  const [assignTarget, setAssignTarget] = useState<TableWithMatch | null>(null)

  const refresh = useCallback(async () => {
    if (tid === null) return
    const requestTid = tid
    const generation = requestGenerationRef.current
    /** 本次请求是否仍代表"当前生效的赛事与代次"。 */
    const isCurrent = () =>
      activeTidRef.current === requestTid && requestGenerationRef.current === generation

    // 只有完全相同的 (tid, generation) 才去重；旧赛事的在途请求不阻塞新赛事的首次刷新。
    const inFlight = requestInFlightRef.current
    if (inFlight !== null && inFlight.tid === requestTid && inFlight.generation === generation) return
    requestInFlightRef.current = { tid: requestTid, generation }

    try {
      // 先取赛事本身：团体赛有独立链路，不能走个人赛 Match Console（第 11 节硬边界）。
      const tournament = await api.getTournament(requestTid)
      if (!isCurrent()) return
      if (tournament.event_type === 'TEAM') {
        const next: ConsoleSnapshot = {
          tournament,
          dashboard: null,
          players: [],
          finished: [],
          waiting: [],
          groupNames: {},
          estimates: new Map(),
        }
        snapshotRef.current = next
        setSnapshot(next)
      } else {
        const [dashboard, players, finished, waiting, groups, estimates] = await Promise.all([
          api.getDashboard(requestTid),
          api.listPlayers(requestTid),
          api.listMatches(requestTid, { status: 'FINISHED' }),
          api.listMatches(requestTid, { status: 'WAITING' }),
          api.getGroups(requestTid),
          api.getScheduleEstimates(requestTid).catch(() => null),
        ])
        if (!isCurrent()) return
        const groupNames: Record<number, string> = {}
        for (const group of groups.groups) groupNames[group.id] = group.name
        const next: ConsoleSnapshot = {
          tournament,
          dashboard,
          players,
          finished,
          waiting,
          groupNames,
          estimates: new Map((estimates?.matches ?? []).map((item) => [item.match_id, item])),
        }
        snapshotRef.current = next
        setSnapshot(next)
      }
      setInitialError(null)
      setStale(false)
      setLastSyncedAt(new Date())
    } catch (reason) {
      // 旧 tid / 旧代次的失败不得污染新赛事：既不能把新赛事标成 stale，也不能写它的错误文案。
      if (!isCurrent()) return
      // 已有成功快照时保留它，只标记 stale；不得把比赛列表清空、球台变空、比分变 0。
      if (snapshotRef.current) setStale(true)
      else setInitialError(reason instanceof ApiError ? reason.message : '加载控制台失败')
    } finally {
      // 只清除"本次请求自己"的记账：不能覆盖新赛事已经建立的在途状态。
      const current = requestInFlightRef.current
      if (current !== null && current.tid === requestTid && current.generation === generation) {
        requestInFlightRef.current = null
      }
      if (isCurrent()) setLoading(false)
    }
  }, [tid])

  useEffect(() => {
    // tid 变化的边界：先让旧代次的在途请求失效，再重置快照并启动本代次的请求。
    // 顺序很重要 —— 代次必须在本代次 refresh 之前自增，否则新请求会拿到旧代次号。
    activeTidRef.current = tid
    requestGenerationRef.current += 1
    requestInFlightRef.current = null

    snapshotRef.current = null
    setSnapshot(null)
    setInitialError(null)
    setStale(false)
    setLastSyncedAt(null)
    setLoading(true)

    let timer: ReturnType<typeof setInterval> | null = null
    const stopPolling = () => {
      if (timer !== null) clearInterval(timer)
      timer = null
    }
    const startPolling = () => {
      stopPolling()
      if (!document.hidden) timer = setInterval(() => { void refresh() }, CONSOLE_POLL_INTERVAL_MS)
    }
    const onVisibilityChange = () => {
      if (document.hidden) {
        stopPolling()
        return
      }
      void refresh()
      startPolling()
    }

    void refresh()
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [refresh])

  const fail = (e: unknown) => setFeedback(consoleErrorFeedback(e))

  const openScoreSheet = (match: Match, mode: 'record' | 'revise', detailMode = false) => {
    setFeedback(null)
    setScoreSubmitError(null)
    setScoreDetailMode(detailMode)
    setScoreMode(mode)
    setScoringMatch(match)
  }

  const saveScoreSheet = async (payload: import('../api').ScorePayload) => {
    if (!scoringMatch) return
    setBusy(true)
    setScoreSubmitError(null)
    const wasRevision = scoreMode === 'revise'
    const wasDetailRevision = wasRevision && scoreDetailMode
    try {
      if (wasRevision) await api.reviseScore(scoringMatch.id, payload as import('../api').ScoreRevisionPayload)
      else await api.recordScore(scoringMatch.id, payload)
      setScoringMatch(null)
      setFeedback({
        tone: 'success',
        title: wasDetailRevision ? '逐局小分已更新' : wasRevision ? '比赛结果已修改' : '比赛结果已记录',
        message: wasRevision ? '修改已写入操作记录，比赛列表正在刷新。' : '比分已保存，比赛列表正在刷新。',
      })
      await refresh()
    } catch (e) {
      setScoreSubmitError(consoleErrorFeedback(e, wasRevision ? '修改比分失败' : '录入比分失败'))
    } finally {
      setBusy(false)
    }
  }

  const showAudits = async (match: Match) => {
    setFeedback(null)
    try {
      setAudits(await api.listScoreAudits(match.id))
      setAuditMatch(match)
    } catch (e) {
      fail(e)
    }
  }

  const release = async (m: Match) => {
    setFeedback(null)
    setBusy(true)
    try {
      await api.releaseMatch(m.id)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  /** 主裁从后端合法 `next_playable` 中选定一场，再安排到球台。前端不挑比赛。 */
  const assignMatchToTable = async (matchId: number) => {
    if (!assignTarget) return
    const tableId = assignTarget.id
    setAssignTarget(null)
    setFeedback(null)
    setBusy(true)
    try {
      await api.assignTable(matchId, tableId)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const scheduleBatch = async () => {
    setFeedback(null)
    setBusy(true)
    try {
      const result = await api.scheduleNext(tid as number)
      if (result.assigned === 0) {
        setFeedback({ tone: 'warning', title: '没有可安排的比赛', message: '当前没有满足条件的比赛（可能双方未就绪，或选手正在其他场次）。' })
      }
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const confirmDemoFinish = async () => {
    if (
      !window.confirm(
        'Demo 模式\n\n将自动生成所有未完成小组赛的比赛结果（随机比分）。\n此功能仅用于快速演示。',
      )
    )
      return
    setFeedback(null)
    setBusy(true)
    try {
      await api.finishGroupStage(tid as number)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  if (tid === null) {
    return (
      <div className="card">
        <h2>比赛控制台</h2>
        <p className="muted">
          请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。
        </p>
      </div>
    )
  }

  // 首次加载：正常 loading；核心数据失败时给出明确错误 + 重试，不白屏、不无限 loading。
  if (loading && !snapshot) {
    return <div className="card"><h2>比赛控制台</h2><p className="muted">正在加载赛事数据…</p></div>
  }

  if (!snapshot) {
    return (
      <div className="card" role="alert">
        <h2>比赛控制台</h2>
        <p className="status-error">现场数据加载失败：{initialError || '暂时无法读取现场状态。'}</p>
        <div className="button-row">
          <button className="btn primary" onClick={() => { setLoading(true); void refresh() }} type="button">重试</button>
          <Link className="btn" to="/">返回赛事首页</Link>
        </div>
      </div>
    )
  }

  const { tournament, dashboard, players, finished, waiting, groupNames, estimates } = snapshot

  // 团体赛：保持独立链路，不用个人赛 Console 管理团体赛（第 11 节硬边界）。
  if (tournament.event_type === 'TEAM') {
    return (
      <div className="page">
        <div className="card">
          <h2>{tournament.name} · 比赛控制台</h2>
          <p className="muted">
            团体赛使用独立的队伍、对抗与单盘链路，不使用个人赛 Match 比赛控制台。
          </p>
          <div className="admin-action-links">
            <Link to={`/team-ties?tid=${tid}`}>进入团体对抗</Link>
            <Link to={`/team-rankings?tid=${tid}`}>查看团体排名</Link>
            <Link to={`/team-qualification?tid=${tid}`}>晋级确认</Link>
          </div>
        </div>
      </div>
    )
  }

  const nameOf = (id: number | null) => {
    if (id === null) return '待定'
    return players.find((p) => p.id === id)?.name ?? `#${id}`
  }
  const sideName = (match: Match, side: 'a' | 'b') =>
    (side === 'a' ? match.entry_a_name : match.entry_b_name)
    ?? nameOf(side === 'a' ? match.player_a_id : match.player_b_id)

  const stageLabel = (match: Match) =>
    matchStageLabel(match, match.group_id === null ? null : groupNames[match.group_id])

  const formatTime = (value: string | null | undefined) => value
    ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('zh-CN', { hour12: false })
    : '—'

  const auditScore = (snapshotRecord: Record<string, unknown>) => {
    const type = snapshotRecord.result_type
    if (type && type !== 'NORMAL') return '弃权判负'
    const a = snapshotRecord.player_a_score
    const b = snapshotRecord.player_b_score
    return a === null || b === null ? '未录入' : `${a} : ${b}`
  }

  const tables = sortTablesByNumber(dashboard?.tables ?? [])
  const notice = completionNotice(dashboard, tid)
  const assignable = canAssignMatches(dashboard)
  const disabledReason = assignable ? undefined : assignDisabledReason(dashboard)
  const showBatch = canScheduleBatch(dashboard)
  const stats = dashboard?.stats
  const demoAvailable =
    tournament.operation_mode === 'DEMO'
    && tournament.stage === 'GROUP_STAGE'
    && stats !== undefined
    && (stats.waiting > 0 || stats.playing > 0)

  // 待进行比赛按后端返回的组顺序分组展示（不重排优先级）。
  const waitingByGroup: Record<number, Match[]> = {}
  const knockoutWaiting: Match[] = []
  for (const match of waiting) {
    if (match.stage === 'GROUP' && match.group_id !== null) (waitingByGroup[match.group_id] ??= []).push(match)
    else if (match.stage === 'KNOCKOUT') knockoutWaiting.push(match)
  }
  const displayWaiting: { label: string; matches: Match[] }[] = Object.keys(waitingByGroup)
    .map(Number)
    .sort((a, b) => a - b)
    .map((gid) => ({ label: groupNames[gid] ?? `组${gid}`, matches: waitingByGroup[gid] }))
  if (knockoutWaiting.length > 0) displayWaiting.push({ label: '淘汰赛', matches: knockoutWaiting })

  return (
    <div className="page">
      {feedback && (
        <div className={`console-feedback is-${feedback.tone}`} role={feedback.tone === 'danger' ? 'alert' : 'status'}>
          <div><strong>{feedback.title}</strong><span>{feedback.message}</span></div>
          <button type="button" onClick={() => setFeedback(null)} aria-label="关闭操作提示">×</button>
        </div>
      )}

      <div className="card">
        <h2 className="console-title">
          <span className="console-title-text">{tournament.name} · 比赛控制台</span>
          <Link className="btn small float-right" to="/">← 返回首页</Link>
        </h2>
        <p className="muted">
          阶段 <span className="badge">{tournamentStageLabel(tournament.stage, tournament.format_code)}</span>{' '}
          <span className={`badge mode-badge ${tournament.operation_mode === 'LIVE' ? 'live' : 'demo'}`}>
            {tournament.operation_mode === 'LIVE' ? '正式赛事' : '演示赛事'}
          </span>{' '}
          <span className="badge">{tournament.table_count} 张球台</span>
        </p>

        <div className={`console-sync${stale ? ' is-stale' : ''}`} role={stale ? 'alert' : 'status'}>
          <span>{stale ? '实时数据暂时无法更新，当前显示可能不是最新状态。' : '现场状态每 5 秒自动同步。'}</span>
          <small>最近同步：{lastSyncedAt ? lastSyncedAt.toLocaleTimeString('zh-CN', { hour12: false }) : '尚未同步'}</small>
        </div>

        {stats && (
          <p className="muted">
            比赛进度 {stats.finished} / {stats.total} · 正在进行 {stats.playing} · 等待 {stats.waiting} · 球台 {tables.length}
          </p>
        )}
        {stats && (
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${stats.total > 0 ? Math.round((stats.finished / stats.total) * 100) : 0}%` }}
            />
          </div>
        )}

        <div className="console-actions">
          {showBatch && (
            <button className="btn primary" onClick={scheduleBatch} disabled={busy}>自动安排下一批比赛</button>
          )}
          <button className="btn" onClick={() => void refresh()} disabled={busy}>刷新</button>
          <details className="console-more">
            <summary className="btn">更多</summary>
            <div className="console-more-menu">
              <Link to={`/schedule?tid=${tid}`}>实时赛程</Link>
              <Link to={`/orderbook?tid=${tid}`}>打印快照</Link>
              <Link to={`/rankings?tid=${tid}`}>排名</Link>
              <Link to={`/knockout?tid=${tid}`}>淘汰赛</Link>
              {tournament.operation_mode === 'DEMO' && tournament.stage === 'GROUP_STAGE' && demoAvailable && (
                <button onClick={confirmDemoFinish} disabled={busy} type="button">
                  <span className="demo-tag">Demo</span> 模拟完成剩余小组赛
                </button>
              )}
            </div>
          </details>
        </div>
      </div>

      {notice && (
        <div className={`card console-notice is-${notice.tone}`} role="status">
          <strong>{notice.title}</strong>
          <p className="muted">{notice.detail}</p>
          {notice.action && (
            <div className="button-row">
              <Link className="btn primary" to={notice.action.to}>{notice.action.label}</Link>
            </div>
          )}
        </div>
      )}

      {stats && (
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-num">{stats.total}</div>
            <div className="stat-label">总场数</div>
          </div>
          <div className="stat-card">
            <div className="stat-num">{stats.finished}</div>
            <div className="stat-label">已完成</div>
          </div>
          <div className="stat-card playing">
            <div className="stat-num">{stats.playing}</div>
            <div className="stat-label">进行中</div>
          </div>
          <div className="stat-card">
            <div className="stat-num">{stats.waiting}</div>
            <div className="stat-label">等待</div>
          </div>
        </div>
      )}

      <div className="card live-floor-card">
        <div className="live-floor-heading">
          <div><span className="eyebrow">LIVE FLOOR</span><h3>比赛现场</h3></div>
          <span className="live-floor-hint">
            {assignable ? '按台号固定排列；点击球台录入本场大比分' : (disabledReason ?? '按台号固定排列')}
          </span>
        </div>
        {tables.length === 0 ? (
          <p className="muted">当前赛事还没有可用球台。</p>
        ) : (
          <div className="live-table-stack">
            {tables.map((table) => (
              <LiveTableCard
                key={table.id}
                table={table}
                sideName={sideName}
                stageLabel={stageLabel}
                busy={busy}
                assignDisabledReason={disabledReason}
                recommendedMatch={recommendedMatchForTable(dashboard, table)}
                onAssign={setAssignTarget}
                onScore={(match) => openScoreSheet(match, 'record')}
                onRelease={release}
              />
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3>待进行比赛（{waiting.length}）</h3>
        {waiting.length === 0 && <p className="muted">暂无待进行的比赛。</p>}
        {displayWaiting.map((section) => (
          <div key={section.label} className="waiting-group">
            <h4>{section.label}（{section.matches.length} 场）</h4>
            <div className="waiting-match-grid">
              {section.matches.map((match) => (
                <article key={match.id} className="waiting-match-card">
                  <span>#{match.id}</span>
                  <strong title={sideName(match, 'a')}>{sideName(match, 'a')}</strong>
                  <i>VS</i>
                  <strong title={sideName(match, 'b')}>{sideName(match, 'b')}</strong>
                  <QueueEstimate
                    ahead={estimates.get(match.id)?.queue_ahead}
                    estimatedStartAt={estimates.get(match.id)?.estimated_start_at}
                    unavailableReason={estimates.get(match.id)?.unavailable_reason}
                  />
                  {/*
                    手机录分入口（D 轨 Day 3）：跳转到
                    /admin/t/:tid/matches/:matchId/score —— D 轨拥有的唯一精确 route。
                    只在双方已就绪时给出入口 —— 对阵未定的比赛在手机上也无法录分，
                    而“谁已就绪”直接来自 Match 契约字段，不是前端另行推导的规则。
                  */}
                  {matchSidesReady(match) && (
                    <Link className="btn small waiting-match-mobile" to={`/admin/t/${tid}/matches/${match.id}/score`}>
                      手机录分
                    </Link>
                  )}
                </article>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>已结束比赛（可修改比分）</h3>
        {finished.length === 0 && <p className="muted">暂无已结束的比赛。</p>}
        {finished.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>赛段</th>
                <th>对阵</th>
                <th>比分</th>
                <th>开赛 / 结束</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {finished.map((match) => (
                <tr key={match.id}>
                  <td>{match.stage === 'GROUP' ? '小组赛' : '淘汰赛'}</td>
                  <td>{sideName(match, 'a')} VS {sideName(match, 'b')}</td>
                  <td>
                    {match.result_type && match.result_type !== 'NORMAL' ? 'W/O' : `${match.player_a_score} : ${match.player_b_score}`}{' '}
                    {match.games.length > 0 && (
                      <span className="muted">{match.games.map((g) => `${g.side_a_score}-${g.side_b_score}`).join(' / ')}</span>
                    )}
                  </td>
                  <td className="match-time-cell"><span>{formatTime(match.started_at)}</span><span>{formatTime(match.finished_at)}</span></td>
                  <td className="row-actions">
                    <button className="btn small" onClick={() => openScoreSheet(match, 'revise')}>修改大比分</button>
                    <details className="row-more">
                      <summary className="btn small">更多</summary>
                      <div className="row-more-menu">
                        {match.stage === 'GROUP' && match.result_type === 'NORMAL' && (
                          <button onClick={() => openScoreSheet(match, 'revise', true)} type="button">
                            {match.games.length ? '修改小比分' : '补录小比分'}
                          </button>
                        )}
                        <button onClick={() => void showAudits(match)} type="button">操作记录</button>
                        <Link to={`/match-print?tid=${tid}&mid=${match.id}`}>打印成绩单</Link>
                      </div>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {assignTarget && dashboard && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`为 ${assignTarget.name} 安排比赛`}>
          <div className="console-assign-panel">
            <button className="modal-close" onClick={() => setAssignTarget(null)} aria-label="关闭">×</button>
            <span className="eyebrow">TABLE {String(assignTarget.id).padStart(2, '0')}</span>
            <h2>为 {assignTarget.name} 安排比赛</h2>
            <p className="muted">
              下列比赛全部来自后端当前合法的可安排集合（`next_playable`）。
              比赛优先级由后端调度器决定，本页不重新排序。
            </p>
            {dashboard.next_playable.length === 0 && (
              <p className="muted">当前没有可安排的比赛。</p>
            )}
            <div className="console-assign-list">
              {dashboard.next_playable.map((match) => {
                const recommended = assignTarget.recommended_match_id === match.id
                return (
                  <button
                    key={match.id}
                    className={`console-assign-item${recommended ? ' is-recommended' : ''}`}
                    onClick={() => void assignMatchToTable(match.id)}
                    type="button"
                  >
                    <span>#{match.id}</span>
                    <strong>{sideName(match, 'a')}</strong>
                    <i>VS</i>
                    <strong>{sideName(match, 'b')}</strong>
                    <small>{stageLabel(match)}</small>
                    {recommended && <em>后端推荐</em>}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {scoringMatch && (
        <ScoreSheet
          match={scoringMatch}
          sideA={sideName(scoringMatch, 'a')}
          sideB={sideName(scoringMatch, 'b')}
          gamesToWin={tournament.games_to_win}
          pointsToWin={tournament.points_to_win}
          busy={busy}
          detailMode={scoreDetailMode}
          auditMode={scoreMode}
          submitError={scoreSubmitError}
          onClose={() => { setScoringMatch(null); setScoreSubmitError(null) }}
          onSave={saveScoreSheet}
        />
      )}

      {auditMatch && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="比分操作记录">
          <div className="score-audit-panel">
            <button className="modal-close" onClick={() => setAuditMatch(null)} aria-label="关闭">×</button>
            <span className="eyebrow">MATCH #{auditMatch.id} · AUDIT TRAIL</span>
            <h2>比分操作记录</h2>
            <p className="muted">{sideName(auditMatch, 'a')} VS {sideName(auditMatch, 'b')} · 共 {audits.length} 条记录</p>
            <div className="score-audit-list">
              {audits.length === 0 && <p className="muted">该场比赛暂无审计记录。历史版本录入的比分不会自动伪造记录。</p>}
              {audits.map((audit) => (
                <article key={audit.id}>
                  <div><strong>{audit.action === 'REVISE' ? '修改比分' : '首次录入'}</strong><time>{formatTime(audit.created_at)}</time></div>
                  <div className="audit-score-change"><span>{auditScore(audit.before_snapshot)}</span><b>→</b><span>{auditScore(audit.after_snapshot)}</span></div>
                  <p>{audit.operator_name || '未登记操作人'} · {audit.change_reason || '未填写原因'}</p>
                </article>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
