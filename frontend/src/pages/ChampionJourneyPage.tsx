import { CSSProperties, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, KnockoutMatch, KnockoutTree } from '../api'
import { getActiveTournamentId } from '../activeTournament'

type Placement = { rank: number; label: string; entry: { id: number; name: string | null } | null }
type Connector = { key: string; d: string; active: boolean }

function MatchTile({ match, active, capture }: { match: KnockoutMatch; active: boolean; capture: (node: HTMLElement | null) => void }) {
  const exceptional = Boolean(match.result_type && match.result_type !== 'NORMAL')
  const aWon = match.winner_id !== null && match.player_a?.id === match.winner_id
  const bWon = match.winner_id !== null && match.player_b?.id === match.winner_id
  const scoreA = exceptional ? (aWon ? 'W' : '—') : (match.player_a_score ?? '—')
  const scoreB = exceptional ? (bWon ? 'W' : '—') : (match.player_b_score ?? '—')
  const winner = aWon ? match.player_a?.name : bWon ? match.player_b?.name : null

  return <article ref={capture} data-match-id={match.id} data-champion-path={active || undefined} className={`journey-tree-match ${active ? 'is-champion-path' : ''}`}>
    <span className="journey-tree-match-id">M{match.id}</span>
    <div className={aWon ? 'is-winner' : ''}>
      <strong>{match.player_a?.name ?? '待定'}</strong><b>{scoreA}</b>
    </div>
    <div className={bWon ? 'is-winner' : ''}>
      <strong>{match.player_b?.name ?? '待定'}</strong><b>{scoreB}</b>
    </div>
    <footer>{winner ? <>晋级 <strong>{winner}</strong></> : '等待比赛结果'}</footer>
  </article>
}

export default function ChampionJourneyPage() {
  const [params] = useSearchParams()
  const raw = params.get('tid')
  const tid = raw ? Number(raw) : getActiveTournamentId()
  const [tree, setTree] = useState<KnockoutTree | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connectors, setConnectors] = useState<Connector[]>([])
  const treeRef = useRef<HTMLDivElement | null>(null)
  const summitRef = useRef<HTMLElement | null>(null)
  const matchRefs = useRef(new Map<number, HTMLElement>())

  const load = useCallback(async () => {
    if (tid === null) return
    setTree(await api.getKnockout(tid))
  }, [tid])

  useEffect(() => { load().catch((e) => setError(e instanceof ApiError ? e.message : '加载失败')) }, [load])

  const path = useMemo(() => new Set(tree?.champion_path_match_ids ?? []), [tree])
  const displayRounds = useMemo(() => [...(tree?.rounds ?? [])].reverse(), [tree])
  const placements = (tree?.placements ?? []).filter(
    (item): item is Placement => typeof item.rank === 'number' && typeof item.label === 'string',
  )

  const captureMatch = useCallback((matchId: number, node: HTMLElement | null) => {
    if (node) matchRefs.current.set(matchId, node)
    else matchRefs.current.delete(matchId)
  }, [])

  const measureConnectors = useCallback(() => {
    const root = treeRef.current
    if (!root || !tree) return
    const rootBox = root.getBoundingClientRect()
    const point = (element: HTMLElement, edge: 'top' | 'bottom') => {
      const box = element.getBoundingClientRect()
      return {
        x: box.left - rootBox.left + box.width / 2,
        y: (edge === 'top' ? box.top : box.bottom) - rootBox.top,
      }
    }
    const next: Connector[] = []
    for (const round of tree.rounds) {
      for (const match of round.matches) {
        const target = matchRefs.current.get(match.id)
        if (!target) continue
        for (const previousId of [match.prev_match_a_id, match.prev_match_b_id]) {
          if (previousId === null) continue
          const source = matchRefs.current.get(previousId)
          if (!source) continue
          const from = point(source, 'top')
          const to = point(target, 'bottom')
          const middleY = (from.y + to.y) / 2
          next.push({
            key: `${previousId}-${match.id}`,
            d: `M ${from.x} ${from.y} V ${middleY} H ${to.x} V ${to.y}`,
            active: path.has(previousId) && path.has(match.id),
          })
        }
      }
    }
    const final = tree.rounds[tree.rounds.length - 1]?.matches[0]
    const finalNode = final ? matchRefs.current.get(final.id) : null
    if (final && finalNode && summitRef.current) {
      const from = point(finalNode, 'top')
      const to = point(summitRef.current, 'bottom')
      const middleY = (from.y + to.y) / 2
      next.push({
        key: `${final.id}-champion`,
        d: `M ${from.x} ${from.y} V ${middleY} H ${to.x} V ${to.y}`,
        active: Boolean(tree.champion && path.has(final.id)),
      })
    }
    setConnectors(next)
  }, [path, tree])

  useLayoutEffect(() => {
    const root = treeRef.current
    if (!root || !tree) return
    const frame = window.requestAnimationFrame(measureConnectors)
    const observer = new ResizeObserver(measureConnectors)
    observer.observe(root)
    window.addEventListener('resize', measureConnectors)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('resize', measureConnectors)
    }
  }, [measureConnectors, tree])

  if (tid === null) return <div className="card"><h2>冠军之路</h2><p>请先选择赛事。</p></div>
  if (!tree && !error) return <div className="journey-page"><p>正在点亮赛场…</p></div>

  return <div className="journey-page">
    <header className="journey-header">
      <div>
        <span className="broadcast-kicker">TABLE TENNIS · ROAD TO CHAMPION</span>
        <h1>{tree?.tournament.name ?? '冠军之路'}</h1>
        <p>{tree?.tournament.event_type === 'DOUBLES' ? '双打' : '单打'} · 从下往上查看每轮对阵与晋级结果</p>
      </div>
      <div className="journey-actions">
        <button onClick={() => window.print()}>导出画面</button>
        <Link to={`/knockout?tid=${tid}`}>返回签表</Link>
      </div>
    </header>

    {error && <p className="journey-error">{error}</p>}
    {(tree?.rounds.length ?? 0) === 0 ? <div className="journey-empty">淘汰赛生成后，完整晋级路线会在这里出现。</div> :
      <div ref={treeRef} className="journey-tree" aria-label="自下而上的冠军晋级路线">
        <div className="arena-grid" aria-hidden="true" />
        <svg className="journey-connectors" data-testid="journey-connectors" width="100%" height="100%" aria-hidden="true">
          {connectors.map((connector) => <path key={connector.key} data-champion-path={connector.active || undefined} className={connector.active ? 'is-champion-path' : ''} d={connector.d} />)}
        </svg>
        <section ref={summitRef} className={`journey-summit ${tree?.champion ? 'is-decided' : ''}`}>
          <span>CHAMPION</span><i>🏆</i><h2>{tree?.champion?.name ?? '冠军待定'}</h2>
          {tree?.runner_up && <p>亚军 · {tree.runner_up.name}</p>}
        </section>
        {displayRounds.map((round, index) => {
          const active = round.matches.some((match) => path.has(match.id))
          const style = { '--match-count': round.matches.length } as CSSProperties
          return <section className={`journey-tree-round ${active ? 'has-champion-path' : ''}`} key={round.round} style={style}>
            <div className="journey-tree-round-title"><span>{String(displayRounds.length - index).padStart(2, '0')}</span><h2>{round.label}</h2><small>{round.matches.length} 场</small></div>
            <div className="journey-tree-matches">
              {round.matches.map((match) => <MatchTile key={match.id} match={match} active={path.has(match.id)} capture={(node) => captureMatch(match.id, node)} />)}
            </div>
          </section>
        })}
        <div className="journey-origin"><span />参赛选手从这里出发，胜者逐轮向上晋级</div>
      </div>}

    {placements.length > 0 && <section className="podium-strip">
      {placements.map((row, index) => <div key={`${row.rank}-${index}`} className={`podium-rank rank-${row.rank}`}>
        <span>{row.label}</span><b>{row.entry?.name ?? '待定'}</b><i>#{row.rank}</i>
      </div>)}
    </section>}
  </div>
}
