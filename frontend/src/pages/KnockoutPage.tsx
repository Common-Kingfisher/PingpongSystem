import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, KnockoutMatch, KnockoutRound, KnockoutTree, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

// ---------------------------------------------------------------- 比分编辑 Modal

interface ScoreModalState {
  match: KnockoutMatch
  label: string
  a: string
  b: string
}

// ---------------------------------------------------------------- 比赛卡片

function KoCard({
  m,
  onScore,
}: {
  m: KnockoutMatch
  onScore: (m: KnockoutMatch, label: string) => void
}) {
  const aName = m.player_a?.name ?? '待定'
  const bName = m.player_b?.name ?? '待定'
  const aScore = m.player_a_score
  const bScore = m.player_b_score
  const finished = m.status === 'FINISHED'
  const bothSet = m.player_a !== null && m.player_b !== null
  const canScore = bothSet && !finished
  const winA = finished && m.winner_id === m.player_a?.id
  const winB = finished && m.winner_id === m.player_b?.id
  const statusText = finished
    ? '已结束'
    : m.status === 'PLAYING'
      ? '比赛中'
      : bothSet
        ? '待比赛'
        : '等待晋级'

  return (
    <div className="ko-card" data-mid={m.id}>
      <div className={`ko-card-row ${winA ? 'win' : ''}`}>
        <span className="ko-card-name">{aName}</span>
        {aScore !== null && <span className="ko-card-score">{aScore}</span>}
      </div>
      <div className={`ko-card-row ${winB ? 'win' : ''}`}>
        <span className="ko-card-name">{bName}</span>
        {bScore !== null && <span className="ko-card-score">{bScore}</span>}
      </div>
      <div className="ko-card-foot">
        <span className="ko-card-status">{statusText}</span>
        {canScore && (
          <button className="btn small primary ko-score-btn" onClick={() => onScore(m, '')}>
            录入比分
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Bracket（含 SVG 连接线）

function Bracket({
  rounds,
  champion,
  runnerUp,
  onScore,
}: {
  rounds: KnockoutRound[]
  champion: { id: number; name: string | null } | null
  runnerUp: { id: number; name: string | null } | null
  onScore: (m: KnockoutMatch, label: string) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const wrapRect = wrap.getBoundingClientRect()
    const rects = new Map<number, { cy: number; left: number; right: number }>()
    wrap.querySelectorAll('[data-mid]').forEach((el) => {
      const id = Number(el.getAttribute('data-mid'))
      const r = el.getBoundingClientRect()
      rects.set(id, {
        cy: r.top + r.height / 2 - wrapRect.top,
        left: r.left - wrapRect.left,
        right: r.right - wrapRect.left,
      })
    })

    const next: string[] = []
    for (const round of rounds) {
      for (const m of round.matches) {
        const t = rects.get(m.id)
        if (!t) continue
        const feeders = [m.prev_match_a_id, m.prev_match_b_id].filter(
          (x): x is number => x != null,
        )
        for (const fid of feeders) {
          const f = rects.get(fid)
          if (!f) continue
          const midX = t.left - 30
          next.push(`M ${f.right} ${f.cy} H ${midX} V ${t.cy} H ${t.left}`)
        }
      }
    }

    // 决赛 → 冠军
    const final = rounds.length > 0 ? rounds[rounds.length - 1].matches[0] : null
    if (champion && final) {
      const f = rects.get(final.id)
      const champEl = wrap.querySelector<HTMLElement>('[data-champ]')
      if (f && champEl) {
        const cr = champEl.getBoundingClientRect()
        const cxl = cr.left - wrapRect.left
        next.push(`M ${f.right} ${f.cy} H ${cxl - 14}`)
      }
    }
    setLines(next)
  }, [rounds, champion])

  const colClass = (round: number) => `ko-col-cards ko-r${round}`

  return (
    <div ref={wrapRef} className="ko-bracket-wrap">
      <div className="ko-bracket">
        {rounds.map((round) => (
          <div key={round.round} className="ko-col">
            <h3 className="ko-col-title">{round.label}</h3>
            <div className={colClass(round.round)}>
              {round.matches.map((m) => (
                <KoCard key={m.id} m={m} onScore={onScore} />
              ))}
            </div>
          </div>
        ))}

        <div className="ko-col">
          <h3 className="ko-col-title">冠军</h3>
          <div className="ko-champ" data-champ>
            {champion ? (
              <>
                <div className="ko-champ-trophy">🏆</div>
                <div className="ko-champ-name">{champion.name ?? '冠军'}</div>
                {runnerUp && <div className="ko-champ-sub">亚军：{runnerUp.name ?? '—'}</div>}
              </>
            ) : (
              <div className="ko-champ-await">等待决赛产生冠军</div>
            )}
          </div>
        </div>
      </div>
      <svg className="ko-lines" width="100%" height="100%">
        {lines.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------- 页面

export default function KnockoutPage() {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  const tid = urlTid ? Number(urlTid) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [rankings, setRankings] = useState<RankingsResult | null>(null)
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

  const openScore = (m: KnockoutMatch, _label: string) => {
    setModal({ match: m, label: '', a: '', b: '' })
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
        <Bracket rounds={tree!.rounds} champion={tree!.champion} runnerUp={tree!.runner_up} onScore={openScore} />
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
