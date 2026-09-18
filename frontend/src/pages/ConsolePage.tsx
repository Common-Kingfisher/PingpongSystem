import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Dashboard, Match, Player, ScoreAudit, TableWithMatch, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import ScoreSheet from '../components/ScoreSheet'
import LiveTableCard from '../components/LiveTableCard'

export default function ConsolePage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [finished, setFinished] = useState<Match[]>([])
  const [waiting, setWaiting] = useState<Match[]>([])
  const [groupNames, setGroupNames] = useState<Record<number, string>>({})
  const [groupOrder, setGroupOrder] = useState<number[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [scoringMatch, setScoringMatch] = useState<Match | null>(null)
  const [scoreMode, setScoreMode] = useState<'record' | 'revise'>('record')
  const [scoreDetailMode, setScoreDetailMode] = useState(false)
  const [auditMatch, setAuditMatch] = useState<Match | null>(null)
  const [audits, setAudits] = useState<ScoreAudit[]>([])

  const nameOf = useCallback(
    (id: number | null) => {
      if (id === null) return '待定'
      return players.find((p) => p.id === id)?.name ?? `#${id}`
    },
    [players],
  )

  const sideName = (match: Match, side: 'a' | 'b') =>
    (side === 'a' ? match.entry_a_name : match.entry_b_name)
    ?? nameOf(side === 'a' ? match.player_a_id : match.player_b_id)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, d, ps, fs, ws, gs] = await Promise.all([
      api.getTournament(tid),
      api.getDashboard(tid),
      api.listPlayers(tid),
      api.listMatches(tid, { status: 'FINISHED' }),
      api.listMatches(tid, { status: 'WAITING' }),
      api.getGroups(tid),
    ])
    setTournament(t)
    setDash(d)
    setPlayers(ps)
    setFinished(fs)
    setWaiting(ws)
    const names: Record<number, string> = {}
    for (const g of gs.groups) names[g.id] = g.name
    setGroupNames(names)
    setGroupOrder(gs.groups.map((g) => g.id))
    setLoaded(true)
  }, [tid])

  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载控制台失败'),
      )
    }
  }, [tid, load])

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

  const refresh = async () => {
    setError(null)
    try {
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '刷新失败')
    }
  }

  const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : '操作失败')

  const saveScoreSheet = async (payload: import('../api').ScorePayload) => {
    if (!scoringMatch) return
    setBusy(true)
    setError(null)
    try {
      if (scoreMode === 'revise') await api.reviseScore(scoringMatch.id, payload as import('../api').ScoreRevisionPayload)
      else await api.recordScore(scoringMatch.id, payload)
      setScoringMatch(null)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const showAudits = async (match: Match) => {
    setError(null)
    try {
      setAudits(await api.listScoreAudits(match.id))
      setAuditMatch(match)
    } catch (e) {
      fail(e)
    }
  }

  const formatTime = (value: string | null | undefined) => value
    ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('zh-CN', { hour12: false })
    : '—'

  const auditScore = (snapshot: Record<string, unknown>) => {
    const type = snapshot.result_type
    if (type && type !== 'NORMAL') return '弃权判负'
    const a = snapshot.player_a_score
    const b = snapshot.player_b_score
    return a === null || b === null ? '未录入' : `${a} : ${b}`
  }

  const release = async (m: Match) => {
    setError(null)
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

  // 与后端 group_table_affinity 一致（软约束）：第 i 个小组优先使用第 i 张球台，
  // 小组多于球台时按球台数取模；没有对应小组的球台不做偏好。
  const preferredGroupForTable = (tableId: number): number | undefined => {
    const tables = dash?.tables ?? []
    if (tables.length === 0) return undefined
    return groupOrder.find((_, i) => tables[i % tables.length].id === tableId)
  }

  const preferredLabelForTable = (tableId: number): string | undefined => {
    const gid = preferredGroupForTable(tableId)
    if (gid === undefined) return undefined
    return groupNames[gid] ?? `组${gid}`
  }

  /** 服务端调度建议（亲和 + 组间公平 + 连续上场惩罚由后端统一计算）。 */
  const recommendedMatchForTable = (table: TableWithMatch): Match | undefined => {
    const matchId = table.recommended_match_id
    if (matchId === null || matchId === undefined) return undefined
    return dash?.next_playable.find((m) => m.id === matchId)
  }

  /** 球台提示：优先显示服务端建议的对阵，其次显示该台的固定小组。 */
  const tableHint = (table: TableWithMatch): string | undefined => {
    const recommended = recommendedMatchForTable(table)
    if (recommended) {
      return `建议安排：${sideName(recommended, 'a')} vs ${sideName(recommended, 'b')}`
    }
    const label = preferredLabelForTable(table.id)
    return label ? `本台优先：${label}` : undefined
  }

  /** 该球台要安排的比赛：服务端建议优先，其次本台对应小组，最后任意一场。 */
  const nextMatchForTable = (table: TableWithMatch): Match | undefined => {
    const playable = dash?.next_playable ?? []
    if (playable.length === 0) return undefined
    const recommended = recommendedMatchForTable(table)
    if (recommended) return recommended
    const gid = preferredGroupForTable(table.id)
    if (gid === undefined) return playable[0]
    return playable.find((m) => m.group_id === gid) ?? playable[0]
  }

  const assignFreeTable = async (tableId: number) => {
    const table = dash?.tables.find((t) => t.id === tableId)
    const next = table ? nextMatchForTable(table) : undefined
    if (!next) {
      setError('当前没有可安排的比赛')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await api.assignTable(next.id, tableId)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const scheduleBatch = async () => {
    setError(null)
    setBusy(true)
    try {
      const r = await api.scheduleNext(tid as number)
      if (r.assigned === 0) setError('没有可安排的比赛（或选手均在比赛）')
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const stats = dash?.stats

  // 小组赛完成判定：按真实 GROUP Match 状态统计，不依赖 total 为 0 的边界
  const waitingGroupMatches = waiting.filter((m) => m.stage === 'GROUP')
  const playingGroupMatches =
    dash?.tables.filter((t) => t.match !== null && t.match.stage === 'GROUP').map((t) => t.match as Match) ?? []
  const finishedGroupMatches = finished.filter((m) => m.stage === 'GROUP')
  const groupTotal =
    waitingGroupMatches.length + playingGroupMatches.length + finishedGroupMatches.length
  const groupStageCompleted =
    groupTotal > 0 &&
    finishedGroupMatches.length === groupTotal &&
    waitingGroupMatches.length === 0 &&
    playingGroupMatches.length === 0
  // 展示用：仅当赛事仍在小组赛阶段且小组赛全部结束时给出"已完成"状态
  const showGroupCompleted = tournament?.stage === 'GROUP_STAGE' && groupStageCompleted

  const hasUnfinishedGroup = stats !== undefined && (stats.waiting > 0 || stats.playing > 0)

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
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  // 待进行比赛按小组分组
  const groupWaiting = waiting.filter((m) => m.stage === 'GROUP' && m.group_id !== null)
  const knockoutWaiting = waiting.filter((m) => m.stage === 'KNOCKOUT')
  const waitingByGroup: Record<number, Match[]> = {}
  for (const m of groupWaiting) {
    ;(waitingByGroup[m.group_id as number] ??= []).push(m)
  }
  const groupIds = Object.keys(waitingByGroup)
    .map(Number)
    .sort((a, b) => a - b)

  // 待进行比赛分组展示：全量横向换行，不再截断为前 20 场。
  const displayWaiting: { label: string; matches: Match[] }[] = []
  for (const gid of groupIds) {
    displayWaiting.push({ label: groupNames[gid] ?? `组${gid}`, matches: waitingByGroup[gid] })
  }
  if (knockoutWaiting.length > 0) displayWaiting.push({ label: '淘汰赛', matches: knockoutWaiting })
  const stageLabel = (match: Match) => match.stage === 'GROUP'
    ? (match.group_id === null ? '小组赛' : `${groupNames[match.group_id] ?? '小组赛'} · 小组赛`)
    : '淘汰赛'

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 比赛控制台
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        {tournament && (
          <p className="muted">
            阶段 <span className="badge">{tournament.stage}</span>{' '}·{' '}
            <span className={`badge mode-badge ${tournament.operation_mode === 'LIVE' ? 'live' : 'demo'}`}>
              {tournament.operation_mode === 'LIVE' ? '正式赛事' : '演示赛事'}
            </span>
          </p>
        )}
        {dash && (
          <>
            <p className="muted">
              比赛进度 {dash.stats.finished} / {dash.stats.total} · 正在进行 {dash.stats.playing} ·
              等待 {dash.stats.waiting} · 球台 {dash.tables.length}
            </p>
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{
                  width: `${dash.stats.total > 0 ? Math.round((dash.stats.finished / dash.stats.total) * 100) : 0}%`,
                }}
              />
            </div>
          </>
        )}
        {error && <p className="status-error">{error}</p>}
        <div className="button-row">
          {tournament?.stage !== 'FINISHED' && !showGroupCompleted && (
            <button className="btn primary" onClick={scheduleBatch} disabled={busy}>
              自动安排下一批比赛
            </button>
          )}
          {tournament?.operation_mode === 'DEMO' && tournament.stage === 'GROUP_STAGE' && hasUnfinishedGroup && (
            <button className="btn" onClick={confirmDemoFinish} disabled={busy}>
              <span className="demo-tag">Demo</span> 模拟完成剩余小组赛
            </button>
          )}
          <button className="btn" onClick={refresh} disabled={busy}>
            刷新
          </button>
        </div>
      </div>

      {!loaded && !error && (
        <div className="card">
          <p className="muted">正在加载赛事数据…</p>
        </div>
      )}

      {showGroupCompleted && (
        <div className="card">
          <p className="status-ok">✅ 小组赛已全部完成，晋级名单已经确定，可以进入淘汰赛。</p>
          <div className="button-row">
            <Link className="btn" to={`/rankings?tid=${tid}`}>
              查看小组排名
            </Link>
            <Link className="btn primary" to={`/knockout?tid=${tid}`}>
              进入淘汰赛
            </Link>
          </div>
        </div>
      )}

      {tournament?.stage === 'REGISTRATION' && (
        <div className="card">
          <p className="muted">
            当前赛事尚未生成比赛。请先在「选手与分组」页：1. 添加选手；2. 自动分组；3. 生成小组循环赛。
          </p>
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
          <span className="live-floor-hint">点击球台录入本场大比分</span>
        </div>
        <div className="live-table-stack">
          {dash?.tables.map((table) => <LiveTableCard
            key={table.id}
            table={table}
            sideName={sideName}
            stageLabel={stageLabel}
            busy={busy}
            groupFinished={showGroupCompleted}
            hintLabel={tableHint(table)}
            onAssign={assignFreeTable}
            onScore={(match) => { setScoreDetailMode(false); setScoreMode('record'); setScoringMatch(match) }}
            onRelease={release}
          />)}
        </div>
      </div>

      <div className="card">
        <h3>待进行比赛（{waiting.length}）</h3>
        {waiting.length === 0 && <p className="muted">暂无待进行的比赛。</p>}
        {displayWaiting.map((sec) => (
          <div key={sec.label} className="waiting-group">
            <h4>
              {sec.label}（{sec.matches.length} 场）
            </h4>
            <div className="waiting-match-grid">
              {sec.matches.map((m) => (
                <article key={m.id} className="waiting-match-card">
                  <span>#{m.id}</span><strong>{sideName(m, 'a')}</strong><i>VS</i><strong>{sideName(m, 'b')}</strong>
                </article>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>已结束比赛（可修改比分）</h3>
        {finished.length === 0 && <p className="muted">暂无已结束的比赛。</p>}
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
            {finished.map((m) => {
              return (
                <tr key={m.id}>
                  <td>{m.stage === 'GROUP' ? '小组赛' : '淘汰赛'}</td>
                  <td>
                    {sideName(m, 'a')} VS {sideName(m, 'b')}
                  </td>
                  <td>
                    {m.result_type && m.result_type !== 'NORMAL' ? 'W/O' : `${m.player_a_score} : ${m.player_b_score}`}{' '}
                    {m.games.length > 0 && <span className="muted">{m.games.map((g) => `${g.side_a_score}-${g.side_b_score}`).join(' / ')}</span>}
                  </td>
                  <td className="match-time-cell"><span>{formatTime(m.started_at)}</span><span>{formatTime(m.finished_at)}</span></td>
                  <td>
                    <button className="btn small" onClick={() => { setScoreDetailMode(false); setScoreMode('revise'); setScoringMatch(m) }}>
                      修改大比分
                    </button>
                    {m.stage === 'GROUP' && m.result_type === 'NORMAL' && <button className="btn small" onClick={() => { setScoreDetailMode(true); setScoreMode('revise'); setScoringMatch(m) }}>
                      {m.games.length ? '修改小比分' : '补录小比分'}
                    </button>}
                    <button className="btn small" onClick={() => showAudits(m)}>操作记录</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {scoringMatch && tournament && (
        <ScoreSheet
          match={scoringMatch}
          sideA={sideName(scoringMatch, 'a')}
          sideB={sideName(scoringMatch, 'b')}
          gamesToWin={tournament.games_to_win}
          pointsToWin={tournament.points_to_win}
          busy={busy}
          detailMode={scoreDetailMode}
          auditMode={scoreMode}
          onClose={() => setScoringMatch(null)}
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
