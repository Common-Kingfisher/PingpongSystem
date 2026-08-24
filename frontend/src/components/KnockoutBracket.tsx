import { useEffect, useRef, useState } from 'react'
import { KnockoutMatch, KnockoutRound } from '../api'

// ---------------------------------------------------------------- 比赛卡片

function KoCard({
  m,
  onScore,
}: {
  m: KnockoutMatch
  onScore?: (m: KnockoutMatch) => void
}) {
  const aName = m.player_a?.name ?? '待定'
  const bName = m.player_b?.name ?? '待定'
  const aScore = m.player_a_score
  const bScore = m.player_b_score
  const finished = m.status === 'FINISHED'
  const bothSet = m.player_a !== null && m.player_b !== null
  const canScore = onScore !== undefined && bothSet && !finished
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
        <span className="ko-card-name">
          {m.player_a?.seed_no != null && (
            <span className="seed-badge">⭐{m.player_a.seed_no}</span>
          )}{' '}
          {aName}
        </span>
        {aScore !== null && <span className="ko-card-score">{aScore}</span>}
      </div>
      <div className={`ko-card-row ${winB ? 'win' : ''}`}>
        <span className="ko-card-name">
          {m.player_b?.seed_no != null && (
            <span className="seed-badge">⭐{m.player_b.seed_no}</span>
          )}{' '}
          {bName}
        </span>
        {bScore !== null && <span className="ko-card-score">{bScore}</span>}
      </div>
      <div className="ko-card-foot">
        <span className="ko-card-status">{statusText}</span>
        {canScore && (
          <button className="btn small primary ko-score-btn" onClick={() => onScore(m)}>
            录入比分
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Bracket（含 SVG 连接线）

export default function KnockoutBracket({
  rounds,
  champion,
  runnerUp,
  onScore,
  large = false,
}: {
  rounds: KnockoutRound[]
  champion: { id: number; name: string | null; seed_no?: number | null } | null
  runnerUp: { id: number; name: string | null; seed_no?: number | null } | null
  onScore?: (m: KnockoutMatch) => void
  large?: boolean
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

  return (
    <div ref={wrapRef} className={`ko-bracket-wrap ${large ? 'ko-bracket-large' : ''}`}>
      <div className="ko-bracket">
        {rounds.map((round) => (
          <div key={round.round} className="ko-col">
            <h3 className="ko-col-title">{round.label}</h3>
            <div className={`ko-col-cards ko-r${round.round}`}>
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
                <div className="ko-champ-name">
                  {champion.seed_no != null && (
                    <span className="seed-badge">⭐{champion.seed_no}</span>
                  )}{' '}
                  {champion.name ?? '冠军'}
                </div>
                {runnerUp && (
                  <div className="ko-champ-sub">
                    亚军：
                    {runnerUp.seed_no != null && (
                      <span className="seed-badge">⭐{runnerUp.seed_no}</span>
                    )}{' '}
                    {runnerUp.name ?? '—'}
                  </div>
                )}
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
