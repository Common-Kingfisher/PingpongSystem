import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Entry, GroupingResult, KnockoutTree, Match, Player, ScheduleEstimateMatch, Tournament } from '../api'
import { getActiveTournamentId, parseTournamentId } from '../activeTournament'
import { matchStageLabel, matchStatusLabel } from '../mobileScore'
import { tournamentStageLabel } from '../format'

type ScheduleVariant = 'admin' | 'public'

/**
 * 赛程页。
 *
 * ## 两个概念（Day5 第 12 / 13 节，不得混淆）
 *
 * - **实时赛程**：来自运行数据库，表示"系统当前真实比赛计划与状态"。本页默认展示它。
 * - **官方秩序册**：赛前发布 / 文件 / 快照 / 打印材料，**不是**运行数据库事实源。
 *   本页不伪造官方秩序册；如需发布材料，见 `/orderbook` 的实时快照与打印。
 *
 * ## variant 边界
 *
 * `public` 保持 D 轨既有"选手赛程"查询行为不变（`PublicRoutes` 传入 path param tid，
 * 不传 variant，因此继续拿到 public）。管理端路由显式传 `admin`，默认展示实时赛程。
 */
export default function SchedulePage({ tid: tidProp, variant = 'public' }: { tid?: number; variant?: ScheduleVariant } = {}) {
  const [params] = useSearchParams()
  const tid = tidProp ?? parseTournamentId(params.get('tid')) ?? getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [entries, setEntries] = useState<Entry[]>([])
  const [groups, setGroups] = useState<GroupingResult>({ groups: [] })
  const [matches, setMatches] = useState<Match[]>([])
  const [knockout, setKnockout] = useState<KnockoutTree | null>(null)
  const [estimates, setEstimates] = useState<Map<number, ScheduleEstimateMatch>>(new Map())
  const [tableNames, setTableNames] = useState<Record<number, string>>({})
  const [tableCount, setTableCount] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadedAt, setLoadedAt] = useState<Date | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, ps, es, gs, ms, dash, tree, eta] = await Promise.all([
      api.getTournament(tid),
      api.listPlayers(tid),
      api.listEntries(tid),
      api.getGroups(tid),
      api.listMatches(tid),
      api.getDashboard(tid),
      // 签表与预计时间都是可选材料：缺失只是少一列信息，不应让整页加载失败。
      api.getKnockout(tid).catch(() => null),
      api.getScheduleEstimates(tid).catch(() => null),
    ])
    setTournament(t)
    setPlayers(ps)
    setEntries(es)
    setGroups(gs)
    setMatches(ms)
    setKnockout(tree)
    const names: Record<number, string> = {}
    for (const table of dash.tables) names[table.id] = table.name
    setTableNames(names)
    setTableCount(dash.tables.length)
    setEstimates(new Map((eta?.matches ?? []).map((item) => [item.match_id, item])))
    setLoadedAt(new Date())
  }, [tid])

  useEffect(() => {
    if (tid === null) {
      setLoading(false)
      return
    }
    setLoading(true)
    load()
      .then(() => setError(null))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : '加载赛程失败'))
      .finally(() => setLoading(false))
  }, [tid, load])

  const participants = useMemo(() => entries.length
    ? entries.map((entry) => ({ id: entry.id, name: entry.display_name, group_id: entry.group_id, seed_no: entry.seed_no, member_ids: entry.members.map((m) => m.player_id) }))
    : players.map((player) => ({ id: player.id, name: player.name, group_id: player.group_id, seed_no: player.seed_no, member_ids: [player.id] })), [entries, players])

  const groupNameById = useMemo(() => {
    const map: Record<number, string> = {}
    for (const group of groups.groups) map[group.id] = group.name
    return map
  }, [groups.groups])

  /** 淘汰赛轮次名由后端签表给出（"8强赛"/"半决赛"/"决赛"），前端不按 round 数字自行命名。 */
  const roundLabelByMatchId = useMemo(() => {
    const map = new Map<number, string>()
    for (const round of knockout?.rounds ?? []) {
      for (const match of round.matches) map.set(match.id, round.label)
    }
    return map
  }, [knockout])

  const selected = participants.find((p) => p.id === selectedId) ?? null
  const groupName = selected?.group_id != null ? groupNameById[selected.group_id] ?? null : null

  const myMatches = useMemo(() => {
    if (!selected) return []
    return matches
      .filter((m) => (m.entry_a_id ?? m.player_a_id) === selected.id || (m.entry_b_id ?? m.player_b_id) === selected.id)
      .sort((a, b) => a.id - b.id)
  }, [matches, selected])

  const playingMatch = myMatches.find((m) => m.status === 'PLAYING') ?? null
  const nextMatch = playingMatch ?? myMatches.find((m) => m.status === 'WAITING') ?? null
  const history = myMatches.filter((m) => m.status === 'FINISHED')

  const sideName = (match: Match, side: 'a' | 'b') => {
    const name = side === 'a' ? match.entry_a_name : match.entry_b_name
    if (name) return name
    const id = side === 'a' ? (match.entry_a_id ?? match.player_a_id) : (match.entry_b_id ?? match.player_b_id)
    return id === null ? '待定' : `#${id}`
  }

  const labelFor = (match: Match): string => {
    if (match.stage === 'GROUP') {
      return matchStageLabel(match, match.group_id === null ? null : groupNameById[match.group_id])
    }
    return roundLabelByMatchId.get(match.id) ?? matchStageLabel(match, null)
  }

  const tableLabel = (match: Match): string =>
    match.table_id === null ? '待安排' : tableNames[match.table_id] ?? `球台${match.table_id}`

  const scoreLabel = (match: Match): string => {
    if (match.status !== 'FINISHED') return '—'
    if (match.result_type && match.result_type !== 'NORMAL') return 'W/O'
    return `${match.player_a_score ?? '–'} : ${match.player_b_score ?? '–'}`
  }

  const estimateLabel = (match: Match): string => {
    if (match.status === 'FINISHED') return '已结束'
    if (match.status === 'PLAYING') return '进行中'
    const item = estimates.get(match.id)
    const startAt = item?.estimated_start_at
    // 后端可将"尚不可估算"显式序列化为 null；null 与缺字段走同一明确降级。
    if (!item || startAt == null) return item?.unavailable_reason || '暂不可估算'
    const normalized = startAt.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(startAt)
      ? startAt
      : `${startAt.replace(' ', 'T')}Z`
    const date = new Date(normalized)
    if (Number.isNaN(date.getTime())) return item.unavailable_reason || '暂不可估算'
    return `约 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
  }

  const opponentOf = (m: Match) => {
    if (!selected) return null
    const a = m.entry_a_id ?? m.player_a_id
    const b = m.entry_b_id ?? m.player_b_id
    const oid = a === selected.id ? b : a
    return participants.find((p) => p.id === oid) ?? null
  }

  const statusText = selected
    ? playingMatch
      ? '正在比赛'
      : nextMatch
        ? '等待比赛'
        : '已完成赛事'
    : ''

  if (tid === null) {
    return (
      <div className="card">
        <h2>赛程</h2>
        <p className="muted">请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。</p>
      </div>
    )
  }

  const liveRows = [...matches].sort((a, b) => a.id - b.id)
  const finishedCount = liveRows.filter((match) => match.status === 'FINISHED').length

  return (
    <div className="page">
      <div className="card">
        <h2 className="console-title">
          <span className="console-title-text">
            {tournament ? tournament.name : '赛事'} · {variant === 'admin' ? '实时赛程' : '选手赛程'}
          </span>
          <Link className="btn small float-right" to="/">← 返回首页</Link>
        </h2>
        {tournament && (
          <p className="muted">
            阶段 <span className="badge">{tournamentStageLabel(tournament.stage, tournament.format_code)}</span>{' '}
            <span className="badge">{tableCount} 张球台</span>
          </p>
        )}
        {error && <p className="status-error">赛程加载失败：{error}</p>}
        {loading && !tournament && <p className="muted">正在加载赛程…</p>}
      </div>

      {variant === 'admin' && (
        <section className="card schedule-live">
          <div className="schedule-live-head">
            <div>
              <span className="eyebrow">LIVE SCHEDULE</span>
              <h3>实时赛程（{liveRows.length} 场）</h3>
            </div>
            <div className="schedule-tools no-print">
              <button className="btn small" onClick={() => { setLoading(true); void load().catch(() => setError('刷新失败')).finally(() => setLoading(false)) }} type="button">
                刷新
              </button>
              <button className="btn small primary" onClick={() => window.print()} type="button">A4 打印</button>
              <Link className="btn small" to={`/orderbook?tid=${tid}`}>打印快照</Link>
            </div>
          </div>

          {/*
            打印快照语义（Day5 第 15 节）：这是"某一时间点的系统实时赛程快照"，
            不得冒充赛事组委会发布的官方秩序册。
          */}
          <div className="print-snapshot-meta">
            <p><b>赛事名称：</b>{tournament?.name ?? '—'}</p>
            <p><b>生成时间：</b>{loadedAt ? loadedAt.toLocaleString('zh-CN', { hour12: false }) : '—'}</p>
            <p><b>当前阶段：</b>{tournament ? tournamentStageLabel(tournament.stage, tournament.format_code) : '—'}</p>
            <p><b>数据状态：</b>实时系统快照（{finishedCount} / {liveRows.length} 场已结束）· 非官方秩序册</p>
          </div>

          {liveRows.length === 0 ? (
            <p className="muted">当前赛事还没有生成比赛。生成比赛后这里会显示实时赛程。</p>
          ) : (
            <table className="data-table schedule-table">
              <thead>
                <tr>
                  <th>场次</th>
                  <th>轮次 / 阶段</th>
                  <th>对阵</th>
                  <th>球台</th>
                  <th>状态</th>
                  <th>比分</th>
                  <th>预计上场</th>
                </tr>
              </thead>
              <tbody>
                {liveRows.map((match) => (
                  <tr key={match.id}>
                    <td>M{match.id}</td>
                    <td>{labelFor(match)}</td>
                    <td className="schedule-pair">{sideName(match, 'a')} VS {sideName(match, 'b')}</td>
                    <td>{tableLabel(match)}</td>
                    <td><span className={`schedule-status is-${match.status.toLowerCase()}`}>{matchStatusLabel(match.status)}</span></td>
                    <td>{scoreLabel(match)}</td>
                    <td>{estimateLabel(match)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <div className="card">
        <h3>{variant === 'admin' ? '按选手查询' : '选手赛程'}</h3>
        <div className="form-inline" style={{ marginTop: 10 }}>
          <select
            aria-label="选择选手"
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : null)}
            style={{ padding: 8, borderRadius: 6, border: '1px solid #cbd2d9', fontSize: 14 }}
          >
            <option value="">选择选手…</option>
            {participants.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        {participants.length === 0 && <p className="muted">当前赛事还没有参赛名单。</p>}
      </div>

      {selected && (
        <>
          <div className="card">
            <h2>{selected.name}</h2>
            <p className="muted">
              所属小组：{groupName ?? '未分组'} · 种子：
              {selected.seed_no != null ? `⭐ ${selected.seed_no}号种子` : '无'} · 当前状态：
              <strong>{statusText}</strong>
            </p>
          </div>

          {nextMatch && (
            <div className="card next-match">
              <h3>
                {playingMatch ? '正在比赛' : '下一场比赛'}
                <span className="float-right muted">{labelFor(nextMatch)}</span>
              </h3>
              <div className="next-pair">
                <span>{selected.name}</span>
                <span className="muted">VS</span>
                <span>{opponentOf(nextMatch)?.name ?? '待定'}</span>
              </div>
              <p className="muted">
                状态：{matchStatusLabel(nextMatch.status)} · 球台：{tableLabel(nextMatch)}
              </p>
            </div>
          )}

          <div className="card">
            <h3>比赛记录（{history.length}）</h3>
            {history.length === 0 && <p className="muted">暂无已结束的比赛。</p>}
            <ul className="history-list">
              {history.map((m) => {
                const won = (m.winner_entry_id ?? m.winner_id) === selected.id
                const aIsSelected = (m.entry_a_id ?? m.player_a_id) === selected.id
                const myScore = aIsSelected ? m.player_a_score : m.player_b_score
                const oppScore = aIsSelected ? m.player_b_score : m.player_a_score
                return (
                  <li key={m.id}>
                    <span className={won ? 'status-ok' : 'status-error'}>{won ? '✅ 胜' : '❌ 负'}</span>{' '}
                    {selected.name} {myScore} : {oppScore} {opponentOf(m)?.name ?? '—'}
                    <span className="muted">（{labelFor(m)}）</span>
                  </li>
                )
              })}
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
