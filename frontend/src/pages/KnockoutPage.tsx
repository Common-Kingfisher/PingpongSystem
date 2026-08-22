import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, KnockoutMatch, KnockoutTree, Tournament } from '../api'

function MatchCard({ m }: { m: KnockoutMatch }) {
  const winner = m.winner_id
  return (
    <div className={`ko-match status-${m.status.toLowerCase()}`}>
      <div className="ko-pair">
        <span className={winner === m.player_a?.id ? 'ko-winner' : ''}>
          {m.player_a ? m.player_a.name : '待定'}
          {m.player_a_score !== null && <em> {m.player_a_score}</em>}
        </span>
        <span className="ko-vs">VS</span>
        <span className={winner === m.player_b?.id ? 'ko-winner' : ''}>
          {m.player_b ? m.player_b.name : '待定'}
          {m.player_b_score !== null && <em> {m.player_b_score}</em>}
        </span>
      </div>
      <div className="ko-status">
        {m.status === 'FINISHED' && '✅ 已结束'}
        {m.status === 'PLAYING' && '🏓 进行中'}
        {m.status === 'WAITING' && (m.player_a && m.player_b ? '可安排' : '等待晋级')}
      </div>
    </div>
  )
}

export default function KnockoutPage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : null

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, k] = await Promise.all([api.getTournament(tid), api.getKnockout(tid)])
    setTournament(t)
    setTree(k)
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
  const groupsDone = tournament?.stage === 'GROUP_STAGE' || knockoutReady

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
          <p className="muted">
            阶段 <span className="badge">{tournament.stage}</span>
            {!knockoutReady && groupsDone && ' · 小组赛已结束，可生成淘汰赛'}
          </p>
        )}
        {error && <p className="status-error">{error}</p>}

        {!knockoutReady && (
          <div className="button-row">
            <button
              className="btn primary"
              onClick={doGenerate}
              disabled={busy || !groupsDone}
            >
              {busy ? '处理中…' : '生成淘汰赛（自动晋级）'}
            </button>
          </div>
        )}
      </div>

      {tree?.champion && (
        <div className="card champion-banner">
          <h3>
            🏆 冠军：{tree.champion.name}
            <span className="muted">　亚军：{tree.runner_up?.name ?? '—'}</span>
          </h3>
        </div>
      )}

      {knockoutReady && (
        <div className="ko-tree">
          {tree!.rounds.map((r) => (
            <div className="ko-round" key={r.round}>
              <h3>{r.label}</h3>
              {r.matches.map((m) => (
                <MatchCard key={m.id} m={m} />
              ))}
            </div>
          ))}
        </div>
      )}

      {!knockoutReady && !groupsDone && (
        <div className="card">
          <p className="muted">小组赛全部结束后可在此生成淘汰赛（每场胜者自动晋级）。</p>
        </div>
      )}
    </div>
  )
}
