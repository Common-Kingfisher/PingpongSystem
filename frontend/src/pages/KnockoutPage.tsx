import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, KnockoutMatch, KnockoutTree, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import KnockoutBracket from '../components/KnockoutBracket'

interface ScoreModalState {
  match: KnockoutMatch
  a: string
  b: string
}

export default function KnockoutPage() {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  const tid = urlTid ? Number(urlTid) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [rankings, setRankings] = useState<RankingsResult | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState<ScoreModalState | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [t, k, r] = await Promise.all([
      api.getTournament(tid),
      api.getKnockout(tid),
      api.getRankings(tid),
    ])
    setTournament(t)
    setTree(k)
    setRankings(r)
    setLoaded(true)
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

  const openScore = (m: KnockoutMatch) => {
    setModal({ match: m, a: '', b: '' })
  }

  const submitScore = async () => {
    if (!modal) return
    const a = Number(modal.a)
    const b = Number(modal.b)
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 0 || b < 0) {
      setError('比分必须是非负整数')
      return
    }
    if (a === b) {
      setError('比分不允许平局')
      return
    }
    // Demo 仅支持 3:0 / 3:1 / 3:2 / 0:3 / 1:3 / 2:3
    if (!((a === 3 && b <= 2) || (b === 3 && a <= 2))) {
      setError('Demo 比分仅支持 3:0 / 3:1 / 3:2 / 0:3 / 1:3 / 2:3')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await api.recordScore(modal.match.id, a, b)
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

  const groupsAllDone =
    (rankings?.rankings.length ?? 0) > 0 &&
    rankings!.rankings.every((g) => g.finished_matches === g.total_matches && g.total_matches > 0)

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
            {!knockoutReady && groupsAllDone && ' · 小组赛已全部结束，可生成淘汰赛'}
          </p>
        )}
        {error && <p className="status-error">{error}</p>}

        {!knockoutReady && groupsAllDone && (
          <div className="button-row">
            <button className="btn primary" onClick={doGenerate} disabled={busy}>
              {busy ? '处理中…' : '生成淘汰赛（自动晋级）'}
            </button>
          </div>
        )}
      </div>

      {knockoutReady ? (
        <KnockoutBracket
          rounds={tree!.rounds}
          champion={tree!.champion}
          runnerUp={tree!.runner_up}
          onScore={openScore}
        />
      ) : (
        <div className="card">
          <p className="muted">
            淘汰赛尚未生成。需要先完成全部小组赛并确定晋级选手（可在「比赛控制台」录入比分）。
          </p>
        </div>
      )}

      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>录入比分</h3>
            <p className="muted">合法比分：3:0 / 3:1 / 3:2 / 0:3 / 1:3 / 2:3</p>
            <div className="modal-pair">
              <div className="modal-line">
                <span className="modal-name">{modal.match.player_a?.name ?? '待定'}</span>
                <input
                  type="number"
                  min={0}
                  autoFocus
                  value={modal.a}
                  onChange={(e) => setModal({ ...modal, a: e.target.value })}
                />
              </div>
              <div className="modal-line">
                <span className="modal-name">{modal.match.player_b?.name ?? '待定'}</span>
                <input
                  type="number"
                  min={0}
                  value={modal.b}
                  onChange={(e) => setModal({ ...modal, b: e.target.value })}
                />
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setModal(null)}>
                取消
              </button>
              <button className="btn primary" onClick={submitScore} disabled={busy}>
                {busy ? '处理中…' : '确认比分'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
