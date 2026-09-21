import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Entry, GroupingResult, Match, Player, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

export default function SchedulePage({ tid: tidProp }: { tid?: number } = {}) {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  // tid 优先级：显式 prop（Public 路由的 path param）> ?tid= > localStorage（V0.2 兼容）
  const tid = tidProp ?? (urlTid ? Number(urlTid) : getActiveTournamentId())

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [entries, setEntries] = useState<Entry[]>([])
  const [groups, setGroups] = useState<GroupingResult>({ groups: [] })
  const [matches, setMatches] = useState<Match[]>([])
  const [tableNames, setTableNames] = useState<Record<number, string>>({})
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, ps, es, gs, ms, dash] = await Promise.all([
      api.getTournament(tid),
      api.listPlayers(tid),
      api.listEntries(tid),
      api.getGroups(tid),
      api.listMatches(tid),
      api.getDashboard(tid),
    ])
    setTournament(t)
    setPlayers(ps)
    setEntries(es)
    setGroups(gs)
    setMatches(ms)
    const names: Record<number, string> = {}
    for (const tb of dash.tables) names[tb.id] = tb.name
    setTableNames(names)
  }, [tid])

  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载赛程失败'),
      )
    }
  }, [tid, load])

  const participants = useMemo(() => entries.length
    ? entries.map((entry) => ({ id: entry.id, name: entry.display_name, group_id: entry.group_id, seed_no: entry.seed_no, member_ids: entry.members.map((m) => m.player_id) }))
    : players.map((player) => ({ id: player.id, name: player.name, group_id: player.group_id, seed_no: player.seed_no, member_ids: [player.id] })), [entries, players])
  const selected = participants.find((p) => p.id === selectedId) ?? null
  const groupName =
    selected?.group_id != null
      ? groups.groups.find((g) => g.id === selected.group_id)?.name ?? null
      : null

  const myMatches = useMemo(() => {
    if (!selected) return []
    return matches
      .filter((m) => (m.entry_a_id ?? m.player_a_id) === selected.id || (m.entry_b_id ?? m.player_b_id) === selected.id)
      .sort((a, b) => a.id - b.id)
  }, [matches, selected])

  const playingMatch = myMatches.find((m) => m.status === 'PLAYING') ?? null
  const nextMatch = playingMatch ?? myMatches.find((m) => m.status === 'WAITING') ?? null
  const history = myMatches.filter((m) => m.status === 'FINISHED')

  const matchLabel = (m: Match): string => {
    if (m.stage === 'GROUP') {
      return `小组赛 · ${groupName ?? `组${m.group_id ?? ''}`}`
    }
    const maxR = Math.max(0, ...matches.filter((x) => x.stage === 'KNOCKOUT').map((x) => x.round))
    const participants = 2 ** (maxR - m.round + 1)
    if (participants === 2) return '决赛'
    if (participants === 4) return '半决赛'
    return `${participants}强赛`
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

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 选手赛程
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        {tournament && (
          <p className="muted">
            阶段 <span className="badge">{tournament.stage}</span> · 只读查询
          </p>
        )}
        {error && <p className="status-error">{error}</p>}

        <div className="form-inline" style={{ marginTop: 10 }}>
          <select
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : null)}
            style={{ padding: 8, borderRadius: 6, border: '1px solid #cbd2d9', fontSize: 14 }}
          >
            <option value="">选择选手…</option>
            {participants.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
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
                <span className="float-right muted">{matchLabel(nextMatch)}</span>
              </h3>
              <div className="next-pair">
                <span>{selected.name}</span>
                <span className="muted">VS</span>
                <span>{opponentOf(nextMatch)?.name ?? '待定'}</span>
              </div>
              <p className="muted">
                状态：{nextMatch.status === 'PLAYING' ? '比赛中' : '等待比赛'} · 球台：
                {nextMatch.table_id != null ? tableNames[nextMatch.table_id] ?? '—' : '待安排'}
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
                    <span className={won ? 'status-ok' : 'status-error'}>
                      {won ? '✅ 胜' : '❌ 负'}
                    </span>{' '}
                    {selected.name} {myScore} : {oppScore} {opponentOf(m)?.name ?? '—'}
                    <span className="muted">（{matchLabel(m)}）</span>
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
