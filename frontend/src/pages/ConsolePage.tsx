import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Dashboard, Match, Player, Tournament } from '../api'

interface ScoreInput {
  a: string
  b: string
}

export default function ConsolePage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : null

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [finished, setFinished] = useState<Match[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [scores, setScores] = useState<Record<string, ScoreInput>>({})
  const [revisingId, setRevisingId] = useState<number | null>(null)

  const nameOf = useCallback(
    (id: number | null) => {
      if (id === null) return '待定'
      return players.find((p) => p.id === id)?.name ?? `#${id}`
    },
    [players],
  )

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, d, ps, fs] = await Promise.all([
      api.getTournament(tid),
      api.getDashboard(tid),
      api.listPlayers(tid),
      api.listMatches(tid, { status: 'FINISHED' }),
    ])
    setTournament(t)
    setDash(d)
    setPlayers(ps)
    setFinished(fs)
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

  const setScore = (matchId: number, field: 'a' | 'b', value: string) =>
    setScores((s) => ({ ...s, [matchId]: { ...(s[matchId] ?? { a: '', b: '' }), [field]: value } }))

  const submitScore = async (m: Match) => {
    const input = scores[m.id] ?? { a: '', b: '' }
    const a = Number(input.a)
    const b = Number(input.b)
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 0 || b < 0) {
      setError('比分必须是非负整数')
      return
    }
    if (a === b) {
      setError('比分不允许平局')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await api.recordScore(m.id, a, b)
      await refresh()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
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

  const assignFreeTable = async (tableId: number) => {
    const next = dash?.next_playable[0]
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

  const submitRevise = async (m: Match) => {
    setError(null)
    setBusy(true)
    try {
      const input = scores[`revise-${m.id}`] ?? { a: '', b: '' }
      const ra = Number(input.a)
      const rb = Number(input.b)
      if (!Number.isInteger(ra) || !Number.isInteger(rb) || ra < 0 || rb < 0) {
        setError('比分必须是非负整数')
        return
      }
      if (ra === rb) {
        setError('比分不允许平局')
        return
      }
      await api.reviseScore(m.id, ra, rb)
      await refresh()
      setRevisingId(null)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const stats = dash?.stats
  const allGroupsDone =
    tournament?.stage === 'GROUP_STAGE' && stats !== undefined && stats.finished === stats.total && stats.total > 0

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
            阶段 <span className="badge">{tournament.stage}</span>
            {allGroupsDone && (
              <span className="status-ok"> 小组赛全部结束，可前往淘汰赛页生成 8 强</span>
            )}
          </p>
        )}
        {error && <p className="status-error">{error}</p>}
        <div className="button-row">
          <button className="btn primary" onClick={scheduleBatch} disabled={busy}>
            一键调度下一批
          </button>
          <button className="btn" onClick={refresh} disabled={busy}>
            刷新
          </button>
        </div>
      </div>

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

      <div className="card">
        <h3>球台</h3>
        <div className="table-grid">
          {dash?.tables.map((tb) => {
            const m = tb.match
            if (!m) {
              return (
                <div className="table-card free" key={tb.id}>
                  <div className="table-name">{tb.name}</div>
                  <div className="table-status">空闲</div>
                  <button
                    className="btn small primary"
                    onClick={() => assignFreeTable(tb.id)}
                    disabled={busy}
                  >
                    安排比赛
                  </button>
                </div>
              )
            }
            const input = scores[m.id] ?? { a: '', b: '' }
            return (
              <div className="table-card occupied" key={tb.id}>
                <div className="table-name">
                  {tb.name} <span className="badge">进行中</span>
                </div>
                <div className="table-players">
                  <div>{nameOf(m.player_a_id)}</div>
                  <div>VS</div>
                  <div>{nameOf(m.player_b_id)}</div>
                </div>
                <div className="score-row">
                  <input
                    type="number"
                    min={0}
                    placeholder="A分"
                    value={input.a}
                    onChange={(e) => setScore(m.id, 'a', e.target.value)}
                  />
                  <span>:</span>
                  <input
                    type="number"
                    min={0}
                    placeholder="B分"
                    value={input.b}
                    onChange={(e) => setScore(m.id, 'b', e.target.value)}
                  />
                </div>
                <div className="button-row">
                  <button className="btn small primary" onClick={() => submitScore(m)} disabled={busy}>
                    录入比分
                  </button>
                  <button className="btn small" onClick={() => release(m)} disabled={busy}>
                    下球台
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="card">
        <h3>下一批可进行的比赛（{dash?.next_playable.length ?? 0}）</h3>
        {dash && dash.next_playable.length === 0 && <p className="muted">当前没有可执行的比赛。</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>赛段</th>
              <th>轮次</th>
              <th>对阵</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {dash?.next_playable.slice(0, 30).map((m, i) => (
              <tr key={m.id}>
                <td>{i + 1}</td>
                <td>{m.stage === 'GROUP' ? '小组赛' : '淘汰赛'}</td>
                <td>
                  {m.stage === 'GROUP' ? `第 ${m.round} 轮` : `第 ${m.round} 轮`}
                  {m.group_id ? ` · ${m.group_id}` : ''}
                </td>
                <td>
                  {nameOf(m.player_a_id)} VS {nameOf(m.player_b_id)}
                </td>
                <td>可安排</td>
              </tr>
            ))}
          </tbody>
        </table>
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
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {finished.slice(0, 40).map((m) => {
              const isEditing = revisingId === m.id
              const rev = scores[`revise-${m.id}`] ?? { a: '', b: '' }
              return (
                <tr key={m.id}>
                  <td>{m.stage === 'GROUP' ? '小组赛' : '淘汰赛'}</td>
                  <td>
                    {nameOf(m.player_a_id)} VS {nameOf(m.player_b_id)}
                  </td>
                  <td>
                    {isEditing ? (
                      <span className="score-row inline">
                        <input
                          type="number"
                          min={0}
                          value={rev.a}
                          onChange={(e) =>
                            setScores((s) => ({
                              ...s,
                              [`revise-${m.id}`]: { ...rev, a: e.target.value },
                            }))
                          }
                        />
                        :
                        <input
                          type="number"
                          min={0}
                          value={rev.b}
                          onChange={(e) =>
                            setScores((s) => ({
                              ...s,
                              [`revise-${m.id}`]: { ...rev, b: e.target.value },
                            }))
                          }
                        />
                      </span>
                    ) : (
                      <>
                        {m.player_a_score} : {m.player_b_score}{' '}
                        <span className="muted">（胜：{nameOf(m.winner_id)}）</span>
                      </>
                    )}
                  </td>
                  <td>
                    {isEditing ? (
                      <>
                        <button className="btn small primary" onClick={() => submitRevise(m)} disabled={busy}>
                          保存
                        </button>{' '}
                        <button className="btn small" onClick={() => setRevisingId(null)}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button className="btn small" onClick={() => setRevisingId(m.id)}>
                        修改比分
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
