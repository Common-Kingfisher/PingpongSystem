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
  freeTables,
  isPlayableMatch,
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
   *
   * `token` 属于**单次请求**：`finally` 只允许清掉自己那一条记账。冲突收口会用
   * `force` 跳过上面的去重并新起一次请求，若仍按 `(tid, generation)` 清理，
   * 先返回的那次会把新请求的在途记账一起抹掉。
   */
  const requestInFlightRef = useRef<{ tid: number; generation: number; token: symbol } | null>(null)

  const [feedback, setFeedback] = useState<ConsoleFeedback | null>(null)
  const [busy, setBusy] = useState(false)
  const [scoringMatch, setScoringMatch] = useState<Match | null>(null)
  const [scoreMode, setScoreMode] = useState<'record' | 'revise'>('record')
  const [scoreDetailMode, setScoreDetailMode] = useState(false)
  const [scoreSubmitError, setScoreSubmitError] = useState<ConsoleFeedback | null>(null)
  const [auditMatch, setAuditMatch] = useState<Match | null>(null)
  const [audits, setAudits] = useState<ScoreAudit[]>([])
  const [assignTarget, setAssignTarget] = useState<TableWithMatch | null>(null)
  /**
   * 「待进行比赛 → 指定球台」的当前目标比赛（Issue A）。
   *
   * 这是与 `assignTarget`（球台 → 比赛）**并存**的第二个手动入口，方向相反：
   * 现场先找到「张三 VS 李四」，再选球台。两者底层共用同一个
   * `api.assignTable(matchId, tableId)`，不存在第二套排台逻辑。
   */
  const [tablePickerMatch, setTablePickerMatch] = useState<Match | null>(null)

  /**
   * 拉取一次现场状态快照。
   *
   * 返回值表达**这一次调用是否真的为当前 (tid, generation) 提交了一份新快照**，
   * 供冲突收口等需要区分「已加载最新状态」与「没能加载」的路径使用：
   *
   * - `true`：已提交新快照；或同一 (tid, generation) 已有在途刷新（它正在拉同一份权威状态，
   *   这种情况不能算失败，否则会把"刷新中"误报成"刷新失败"）；
   * - `false`：没有提交（请求失败、或响应回来时已属于旧代次）。
   *
   * `force: true` 跳过在途去重：冲突收口必须拿到**此刻**的权威状态，不能被一个
   * 更早发起的在途请求代表。
   */
  const refresh = useCallback(async (options?: { force?: boolean }): Promise<boolean> => {
    if (tid === null) return false
    const requestTid = tid
    const generation = requestGenerationRef.current
    /** 本次请求是否仍代表"当前生效的赛事与代次"。 */
    const isCurrent = () =>
      activeTidRef.current === requestTid && requestGenerationRef.current === generation

    // 只有完全相同的 (tid, generation) 才去重；旧赛事的在途请求不阻塞新赛事的首次刷新。
    const inFlight = requestInFlightRef.current
    if (
      !options?.force
      && inFlight !== null
      && inFlight.tid === requestTid
      && inFlight.generation === generation
    ) return true
    const token = Symbol('console-refresh')
    requestInFlightRef.current = { tid: requestTid, generation, token }

    try {
      // 先取赛事本身：团体赛有独立链路，不能走个人赛 Match Console（第 11 节硬边界）。
      const tournament = await api.getTournament(requestTid)
      if (!isCurrent()) return false
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
        if (!isCurrent()) return false
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
      return true
    } catch (reason) {
      // 旧 tid / 旧代次的失败不得污染新赛事：既不能把新赛事标成 stale，也不能写它的错误文案。
      if (!isCurrent()) return false
      // 已有成功快照时保留它，只标记 stale；不得把比赛列表清空、球台变空、比分变 0。
      if (snapshotRef.current) setStale(true)
      else setInitialError(reason instanceof ApiError ? reason.message : '加载控制台失败')
      return false
    } finally {
      // 只清除"本次请求自己"的记账：不能覆盖新赛事已经建立的在途状态。
      const current = requestInFlightRef.current
      if (current !== null && current.token === token) {
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
      /*
       * 首次录分被其他终端抢先（Issue E，6.2）。
       *
       * 409 表示服务端权威状态已经变了（本场已被别人录成 FINISHED）——被拒的这一次
       * **没有**写入任何比分。此时把裁判留在旧表单上，他会以为"卡住了"并反复点击。
       * 正确收口：关闭旧弹窗 → 立刻拉取权威现场状态 → 让 dashboard 展示服务端最新
       * Match / 球台状态。
       *
       * ⚠️ 只对 record 收口。revise 的 409 还有别的业务含义（例如淘汰赛下游已开打），
       * 一律假设成"别人已经录分"会覆盖服务端的真实语义，因此 revise 仍展示服务端原文案。
       * ⚠️ 任何情况下都**不**自动重发一次比分写入：那正是"把 409 重试成第二次写入"。
       */
      if (!wasRevision && e instanceof ApiError && e.status === 409) {
        setScoringMatch(null)
        setScoreSubmitError(null)
        const refreshed = await refresh({ force: true })
        setFeedback(refreshed
          ? {
              tone: 'warning',
              title: '比赛状态已由其他终端更新',
              message: '该场比赛状态已由其他终端更新，已加载最新现场状态。本次提交的比分没有写入。',
            }
          : {
              tone: 'danger',
              title: '检测到状态冲突',
              message: '检测到状态冲突，但刷新最新现场状态失败，请手动重试（点击「刷新」）。（本次提交的比分没有写入）',
            })
      } else {
        setScoreSubmitError(consoleErrorFeedback(e, wasRevision ? '修改比分失败' : '录入比分失败'))
      }
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

  /**
   * 「待进行比赛 → 指定球台」：Issue A 的现场操作路径。
   *
   * 与上面的 `assignMatchToTable` 是**同一个**后端调用（`api.assignTable(matchId, tableId)`），
   * 只是入口方向相反（Match → Table 而不是 Table → Match）。前端不重排优先级、
   * 不自行判定哪张台"应该"给哪场，候选球台一律来自后端当前 FREE 状态。
   */
  const assignTableToMatch = async (match: Match, table: TableWithMatch) => {
    setTablePickerMatch(null)
    setFeedback(null)
    setBusy(true)
    try {
      await api.assignTable(match.id, table.id)
      await refresh()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        /*
         * 球台在提交前被其他终端抢走。相信后端的 409：本机看到的空闲列表已经过期。
         * 先强制刷新到最新现场状态，再明确要求重新选择 —— 绝不在这条路径上重发一次
         * 安排请求（第二次写入可能落在另一张已被占用的球台上）。
         */
        await refresh({ force: true })
        setFeedback({
          tone: 'warning',
          title: '球台状态已变化',
          message: `球台状态已变化，请重新选择。（服务端：${e.message}）`,
        })
      } else {
        fail(e)
      }
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
  // 「指定球台」的候选：后端当前真正 FREE 的球台（不是前端记下来的旧状态）。
  const availableTables = freeTables(dashboard)
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
                    Issue A：现场更自然的路径是「先找到张三 VS 李四，再指定到 3 号台」。
                    入口只对**后端合法可安排**的比赛出现（`dashboard.next_playable` 成员），
                    而不是所有 WAITING 比赛 —— 后者包含双方未就绪或选手正在其他场次的场次。
                    点击后只选球台，绝不允许前端重新组合两名选手或临时造一场 Match。
                  */}
                  {(matchSidesReady(match) || isPlayableMatch(dashboard, match)) && (
                    <div className="waiting-match-actions">
                      {matchSidesReady(match) && (
                        <Link className="btn small waiting-match-mobile" to={`/admin/t/${tid}/matches/${match.id}/score`}>
                          手机录分
                        </Link>
                      )}
                      {isPlayableMatch(dashboard, match) && (
                        <button
                          className="btn small waiting-match-assign"
                          onClick={() => { setFeedback(null); setTablePickerMatch(match) }}
                          disabled={busy}
                          type="button"
                        >
                          指定球台
                        </button>
                      )}
                    </div>
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

      {/*
        Issue A：Match → Table 的指定球台面板。
        候选球台逐张来自后端 dashboard.tables 的 FREE 状态；提交仍走既有 assign-table。
      */}
      {tablePickerMatch && dashboard && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`为比赛 #${tablePickerMatch.id} 指定球台`}>
          <div className="console-assign-panel">
            <button className="modal-close" onClick={() => setTablePickerMatch(null)} aria-label="关闭">×</button>
            <span className="eyebrow">MATCH #{tablePickerMatch.id} · 指定球台</span>
            <h2>指定球台</h2>
            <p className="muted">
              {sideName(tablePickerMatch, 'a')} VS {sideName(tablePickerMatch, 'b')} · {stageLabel(tablePickerMatch)}
            </p>
            <p className="muted">
              下列球台全部来自后端当前状态里真正空闲（FREE）的球台。指定后本场立即变为「进行中」，该球台变为占用。
            </p>
            {availableTables.length === 0 ? (
              <p className="muted">当前没有空闲球台。请先把进行中的比赛下台，或录入该场比赛结果。</p>
            ) : (
              <div className="console-assign-list">
                {availableTables.map((table) => (
                  <button
                    key={table.id}
                    className="console-assign-item console-table-item"
                    onClick={() => void assignTableToMatch(tablePickerMatch, table)}
                    disabled={busy}
                    type="button"
                  >
                    <span>{String(table.id).padStart(2, '0')}</span>
                    <strong>{table.name}</strong>
                    <small>空闲</small>
                  </button>
                ))}
              </div>
            )}
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
