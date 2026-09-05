import { useEffect, useMemo, useState } from 'react'
import { KnockoutMatch, Match, ResultType, ScorePayload } from '../api'

type GameDraft = { a: string; b: string }

export default function ScoreSheet({ match, sideA, sideB, gamesToWin, pointsToWin, busy, detailMode = false, onClose, onSave }: {
  match: Match | KnockoutMatch
  sideA: string
  sideB: string
  gamesToWin: number
  pointsToWin: number
  busy: boolean
  /** 兼容层：小组赛补录/修改小分进入同一逐局编辑器，且不显示异常结果切换。 */
  detailMode?: boolean
  onClose: () => void
  onSave: (payload: ScorePayload) => Promise<void>
}) {
  const existingGames = 'games' in match ? match.games : []
  // 历史仅大比分（无 MatchGame）的已结束比赛：不能伪造小分，提示重新录入。
  const aggregateOnlyHistory = 'games' in match && match.status === 'FINISHED' && existingGames.length === 0
  const maxGames = gamesToWin * 2 - 1

  const initialGames: GameDraft[] = existingGames.length
    ? existingGames.map((game) => ({ a: String(game.side_a_score), b: String(game.side_b_score) }))
    : [{ a: '', b: '' }]

  const [games, setGames] = useState<GameDraft[]>(initialGames)
  const [resultType, setResultType] = useState<ResultType>('NORMAL')
  const [note, setNote] = useState('')

  const wins = useMemo(() => {
    const w = [0, 0]
    for (const game of games) {
      const a = Number(game.a)
      const b = Number(game.b)
      if (game.a !== '' && game.b !== '' && a !== b) w[a > b ? 0 : 1] += 1
    }
    return w
  }, [games])

  const bigA = wins[0]
  const bigB = wins[1]
  const decided = Math.max(bigA, bigB) >= gamesToWin

  // 每完成一局（双方已填且非平局）且尚未决出胜负时，自动追加下一局。
  useEffect(() => {
    setGames((prev) => {
      if (prev.length >= maxGames) return prev
      const last = prev[prev.length - 1]
      const complete = !!last && last.a !== '' && last.b !== '' && Number(last.a) !== Number(last.b)
      if (!complete) return prev
      let wa = 0
      let wb = 0
      for (const g of prev) {
        if (g.a !== '' && g.b !== '' && Number(g.a) !== Number(g.b)) {
          if (Number(g.a) > Number(g.b)) wa += 1
          else wb += 1
        }
      }
      if (Math.max(wa, wb) >= gamesToWin) return prev
      return [...prev, { a: '', b: '' }]
    })
  }, [games, gamesToWin, maxGames])

  // 客户端即时提示（服务端仍是最终裁决，规则错误直接展示 API detail）。
  const gameHint = (game: GameDraft): string | null => {
    if (game.a === '' || game.b === '') return null
    const a = Number(game.a)
    const b = Number(game.b)
    if (a === b) return '平分无效'
    const winner = Math.max(a, b)
    const loser = Math.min(a, b)
    if (winner < pointsToWin) return `未达到 ${pointsToWin} 分`
    if (loser < pointsToWin - 1) return winner === pointsToWin ? null : `胜方需恰好 ${pointsToWin} 分`
    return winner === loser + 2 ? null : '平分延长后需领先 2 分'
  }

  const filledGames = games.filter((game) => game.a !== '' && game.b !== '')
  const hasInvalidGame = filledGames.some((game) => gameHint(game) !== null)
  const canSubmitNormal = decided && !hasInvalidGame

  const update = (index: number, side: 'a' | 'b', value: string) => {
    setGames((current) => current.map((game, i) => (i === index ? { ...game, [side]: value } : game)))
  }

  const saveNormal = () => onSave({
    player_a_score: bigA,
    player_b_score: bigB,
    games: filledGames.map((game) => ({ side_a_score: Number(game.a), side_b_score: Number(game.b) })),
    result_type: 'NORMAL',
    note: note || undefined,
  })

  const saveException = (forfeitId: number | null) => onSave({
    result_type: resultType,
    forfeit_entry_id: forfeitId,
    note: note || undefined,
  })

  const sideAId = 'entry_a_id' in match ? (match.entry_a_id ?? match.player_a_id) : match.player_a?.id ?? null
  const sideBId = 'entry_b_id' in match ? (match.entry_b_id ?? match.player_b_id) : match.player_b?.id ?? null

  return (
    <div className="modal-backdrop score-sheet-backdrop" role="dialog" aria-modal="true" aria-label="逐局录入比赛比分">
      <div className="score-sheet">
        <button className="modal-close" onClick={onClose} aria-label="关闭">×</button>
        <span className="eyebrow">MATCH #{match.id}</span>
        <h2>{detailMode ? '修改 / 补录逐局小分' : '逐局录入比赛'}</h2>
        <div className="score-sheet-versus">
          <strong>{sideA}</strong><span>{bigA} : {bigB}</span><strong>{sideB}</strong>
        </div>

        {aggregateOnlyHistory && (
          <p className="status-warn">该比赛历史记录仅保存大比分。修改结果时需要重新录入逐局比分。</p>
        )}

        {!detailMode && <div className="result-tabs">
          <button className={resultType === 'NORMAL' ? 'active' : ''} onClick={() => setResultType('NORMAL')}>正常完赛</button>
          <button className={resultType !== 'NORMAL' ? 'active' : ''} onClick={() => setResultType('FORFEIT')}>弃权 / 未到</button>
        </div>}

        {resultType === 'NORMAL' ? (
          <>
            <div className="game-input-list">
              {games.map((game, index) => {
                const hint = gameHint(game)
                return (
                  <div className="game-input" key={index}>
                    <span>第 {index + 1} 局</span>
                    <input aria-label={`第${index + 1}局${sideA}得分`} type="number" min={0} max={99} value={game.a} onChange={(event) => update(index, 'a', event.target.value)} />
                    <i>:</i>
                    <input aria-label={`第${index + 1}局${sideB}得分`} type="number" min={0} max={99} value={game.b} onChange={(event) => update(index, 'b', event.target.value)} />
                    {hint && <small className="status-error" style={{ gridColumn: '1 / -1' }}>{hint}</small>}
                  </div>
                )
              })}
            </div>
            <p className="score-rule">每局 {pointsToWin} 分 · {pointsToWin - 1}:{pointsToWin - 1} 后领先 2 分 · 先胜 {gamesToWin} 局者胜</p>
            {decided ? (
              <p className="status-ok" style={{ margin: '8px 0', fontWeight: 700 }}>最终结果：{sideA} {bigA} : {bigB} {sideB}</p>
            ) : (
              <p className="status-warn">比赛尚未结束（当前 {bigA} : {bigB}）</p>
            )}
          </>
        ) : (
          <div className="forfeit-panel">
            <label>结果类型
              <select value={resultType} onChange={(event) => setResultType(event.target.value as ResultType)}>
                <option value="FORFEIT">主动弃权</option>
                <option value="NO_SHOW">未到场</option>
                <option value="DISQUALIFIED">取消资格</option>
                <option value="WALKOVER">直接晋级</option>
              </select>
            </label>
            <p>选择弃权一方。淘汰赛中对方直接晋级；小组赛按弃权规则计入排名。</p>
            <div className="forfeit-actions">
              <button className="btn danger" onClick={() => saveException(sideAId)} disabled={busy}>{sideA} 弃权</button>
              <button className="btn danger" onClick={() => saveException(sideBId)} disabled={busy}>{sideB} 弃权</button>
            </div>
          </div>
        )}

        <label className="score-note">裁判备注
          <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="选填：迟到、判罚或现场说明" />
        </label>
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>取消</button>
          {resultType === 'NORMAL' && <button className="btn primary" onClick={saveNormal} disabled={!canSubmitNormal || busy}>
            {decided ? '确认比赛结果' : '比赛尚未结束'}
          </button>}
        </div>
      </div>
    </div>
  )
}
