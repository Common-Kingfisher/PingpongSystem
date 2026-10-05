import { useCallback, useEffect, useRef, useState } from 'react'
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
            录入大比分
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
  /**
   * 卡片与 SVG 连线共处同一个横向滚动画布（Issue D）。
   *
   * 旧结构把 SVG 放在滚动容器**外面**（`.ko-bracket-wrap` 直接子元素）：
   * `.ko-bracket` 一横向滚动，卡片跟着动而 SVG 不动，连线立刻与卡片分离 ——
   * 这就是现场"移动端分支线错位"的直接原因。
   * 现在 SVG 与全部卡片同处 `canvas`，共享同一坐标系，滚动会同时平移两者。
   */
  const canvasRef = useRef<HTMLDivElement>(null)
  const [lines, setLines] = useState<string[]>([])

  /**
   * 依据**当前真实 DOM 几何**重算全部 SVG path。
   *
   * 测量原点取 canvas 而不是 wrap：SVG 与卡片都在 canvas 内，因此测量结果与
   * 滚动位置无关，不需要（也不应该）为滚动重算。
   */
  const recomputeLines = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const baseRect = canvas.getBoundingClientRect()
    const rects = new Map<number, { cy: number; left: number; right: number }>()
    canvas.querySelectorAll('[data-mid]').forEach((el) => {
      const id = Number(el.getAttribute('data-mid'))
      const r = el.getBoundingClientRect()
      rects.set(id, {
        cy: r.top + r.height / 2 - baseRect.top,
        left: r.left - baseRect.left,
        right: r.right - baseRect.left,
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
      const champEl = canvas.querySelector<HTMLElement>('[data-champ]')
      if (f && champEl) {
        const cr = champEl.getBoundingClientRect()
        const cxl = cr.left - baseRect.left
        next.push(`M ${f.right} ${f.cy} H ${cxl - 14}`)
      }
    }
    setLines(next)
  }, [rounds, champion])

  /**
   * 测量触发与合并。
   *
   * 只依赖 `[rounds, champion]` 是不够的：viewport 变化、横竖屏切换、字体加载、
   * 卡片尺寸变化、容器 resize 之后卡片几何都会变，而 path 仍保留旧坐标。
   * 现在监听 ResizeObserver（画布 + 外层容器）与 window resize / orientationchange，
   * 并用 requestAnimationFrame 合并同一帧内的多次触发。
   *
   * ⚠️ 刻意**不**监听 canvas 的 scroll：SVG 与卡片同在 canvas 内，滚动同时平移
   * 两者，测量坐标系不变 —— 为滚动重算既无必要，也会让移动端每帧都做一次布局读取。
   */
  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    let frame = 0
    const schedule = () => {
      if (frame !== 0) return
      frame = requestAnimationFrame(() => {
        frame = 0
        recomputeLines()
      })
    }

    recomputeLines()

    // jsdom / 老浏览器没有 ResizeObserver：保底只保留 window resize 与首次测量。
    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver === 'function') {
      observer = new ResizeObserver(schedule)
      if (canvas) observer.observe(canvas)
      if (wrap) observer.observe(wrap)
    }
    window.addEventListener('resize', schedule)
    window.addEventListener('orientationchange', schedule)

    return () => {
      // 清理必须成对：rAF / ResizeObserver / 两个 listener 一个都不能漏，
      // 否则每次重渲染都会多留一组监听（切页后仍在测量已卸载的节点）。
      if (frame !== 0) cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', schedule)
      window.removeEventListener('orientationchange', schedule)
    }
  }, [recomputeLines])

  return (
    <div ref={wrapRef} className={`ko-bracket-wrap ${large ? 'ko-bracket-large' : ''}`}>
      <div className="ko-bracket">
        <div ref={canvasRef} className="ko-canvas">
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

          <svg className="ko-lines" width="100%" height="100%">
            {lines.map((d, i) => (
              <path key={i} d={d} />
            ))}
          </svg>
        </div>
      </div>
    </div>
  )
}
