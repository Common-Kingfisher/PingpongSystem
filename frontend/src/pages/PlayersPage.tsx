import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, GenerateMatchesResult, GroupingResult, Player, Tournament } from '../api'

export default function PlayersPage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : null

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [groups, setGroups] = useState<GroupingResult>({ groups: [] })

  const [name, setName] = useState('')
  const [college, setCollege] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editCollege, setEditCollege] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [matchSummary, setMatchSummary] = useState<GenerateMatchesResult | null>(null)
  const [matchCount, setMatchCount] = useState<number | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    setError(null)
    const [t, ps, gs] = await Promise.all([
      api.getTournament(tid),
      api.listPlayers(tid),
      api.getGroups(tid),
    ])
    setTournament(t)
    setPlayers(ps)
    setGroups(gs)
    if (t.stage === 'GROUP_STAGE' || t.stage === 'KNOCKOUT' || t.stage === 'FINISHED') {
      // 已生成场数仅用于展示，失败不阻断整页（避免本页因该非关键请求报 500）
      try {
        const ms = await api.listMatches(tid, { stage: 'GROUP' })
        setMatchCount(ms.length)
      } catch {
        setMatchCount(null)
      }
    }
  }, [tid])

  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载数据失败'),
      )
    }
  }, [tid, load])

  if (tid === null) {
    return (
      <div className="card">
        <h2>选手与分组</h2>
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

  const addPlayer = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await api.addPlayer(tid, { name, college: college || null })
      setName('')
      setCollege('')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加选手失败')
    }
  }

  const startEdit = (p: Player) => {
    setEditingId(p.id)
    setEditName(p.name)
    setEditCollege(p.college ?? '')
  }

  const saveEdit = async (p: Player) => {
    setError(null)
    try {
      await api.updatePlayer(tid, p.id, { name: editName, college: editCollege || null })
      setEditingId(null)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    }
  }

  const removePlayer = async (p: Player) => {
    setError(null)
    if (!window.confirm(`确定删除选手「${p.name}」吗？`)) return
    try {
      await api.deletePlayer(tid, p.id)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const doAutoGroup = async () => {
    setError(null)
    setBusy(true)
    try {
      setGroups(await api.autoGroup(tid))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '自动分组失败')
    } finally {
      setBusy(false)
    }
  }

  const doUngroup = async () => {
    setError(null)
    if (!window.confirm('确定清空当前分组吗？')) return
    setBusy(true)
    try {
      await api.ungroup(tid)
      setGroups({ groups: [] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '清空分组失败')
    } finally {
      setBusy(false)
    }
  }

  const doGenerateMatches = async () => {
    setError(null)
    setBusy(true)
    try {
      const result = await api.generateGroupMatches(tid)
      setMatchSummary(result)
      setTournament(result.tournament)
      setMatchCount(result.matches_generated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '生成小组比赛失败')
    } finally {
      setBusy(false)
    }
  }

  const groupedCount = players.filter((p) => p.group_id !== null).length
  const locked = tournament !== null && tournament.stage !== 'REGISTRATION'

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 选手与分组
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        {tournament && (
          <p className="muted">
            日期 {tournament.date} · 球台 {tournament.table_count} 张 · 小组{' '}
            {tournament.group_count} 个 · 每组晋级 {tournament.qualify_per_group} 人 · 选手{' '}
            {players.length} 人（已分组 {groupedCount} 人） · 阶段{' '}
            <span className="badge">{tournament.stage}</span>
          </p>
        )}
        {error && <p className="status-error">{error}</p>}
        {locked && (
          <p className="muted">⚠️ 赛事已进入比赛阶段，选手名单已锁定（不可增删改）。</p>
        )}
      </div>

      <div className="card">
        <h3>添加选手</h3>
        <form className="form-inline" onSubmit={addPlayer}>
          <input
            type="text"
            placeholder="姓名（必填）"
            value={name}
            required
            disabled={locked}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            type="text"
            placeholder="学院/单位（选填）"
            value={college}
            disabled={locked}
            onChange={(e) => setCollege(e.target.value)}
          />
          <button type="submit" className="btn primary" disabled={locked}>
            添加
          </button>
        </form>

        <h3>选手列表</h3>
        {players.length === 0 && <p className="muted">暂无选手，请先添加。</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>姓名</th>
              <th>学院/单位</th>
              <th>分组</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                {editingId === p.id ? (
                  <>
                    <td>
                      <input
                        type="text"
                        value={editName}
                        required
                        onChange={(e) => setEditName(e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={editCollege}
                        onChange={(e) => setEditCollege(e.target.value)}
                      />
                    </td>
                    <td>{p.group_id !== null ? '已分组' : '—'}</td>
                    <td>
                      <button className="btn small primary" onClick={() => saveEdit(p)}>
                        保存
                      </button>{' '}
                      <button className="btn small" onClick={() => setEditingId(null)}>
                        取消
                      </button>
                    </td>
                  </>
                ) : (
                  <>
                    <td>{p.id}</td>
                    <td>{p.name}</td>
                    <td>{p.college || '—'}</td>
                    <td>{p.group_id !== null ? '已分组' : '—'}</td>
                    <td>
                      <button className="btn small" onClick={() => startEdit(p)} disabled={locked}>
                        修改
                      </button>{' '}
                      <button
                        className="btn small danger"
                        onClick={() => removePlayer(p)}
                        disabled={locked}
                      >
                        删除
                      </button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>自动分组</h3>
        <p className="muted">
          将 {players.length} 名选手随机、均衡地分入 {tournament?.group_count ?? '—'} 个小组。
        </p>
        <div className="button-row">
          <button
            className="btn primary"
            onClick={doAutoGroup}
            disabled={busy || players.length === 0 || locked}
          >
            {busy ? '处理中…' : '自动分组'}
          </button>
          {groups.groups.length > 0 && (
            <button className="btn" onClick={doUngroup} disabled={busy || locked}>
              清空分组
            </button>
          )}
        </div>

        {groups.groups.length > 0 && (
          <div className="group-grid">
            {groups.groups.map((g) => (
              <div className="group-card" key={g.id}>
                <h4>{g.name}</h4>
                <ul>
                  {g.players.map((p) => (
                    <li key={p.id}>
                      {p.name}
                      {p.college ? <span className="muted">（{p.college}）</span> : null}
                    </li>
                  ))}
                </ul>
                <p className="muted">{g.players.length} 人</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3>小组循环赛</h3>
        {tournament?.stage === 'REGISTRATION' ? (
          <>
            <p className="muted">
              为每个小组自动生成单循环比赛（同组每两人交手一次）。生成后赛事将进入小组赛阶段。
            </p>
            <div className="button-row">
              <button
                className="btn primary"
                onClick={doGenerateMatches}
                disabled={busy || groups.groups.length === 0}
              >
                {busy ? '处理中…' : '生成小组比赛'}
              </button>
            </div>
          </>
        ) : (
          <p className="muted">
            小组赛已生成，共{' '}
            <strong>{matchSummary ? matchSummary.matches_generated : matchCount ?? '—'}</strong>{' '}
            场
            {matchSummary && (
              <>
                （{Object.entries(matchSummary.per_group).map(([g, n]) => `${g} ${n} 场`).join('，')}）
              </>
            )}
            。比赛控制台见「比赛控制台」页（任务 7）。
          </p>
        )}
      </div>
    </div>
  )
}
