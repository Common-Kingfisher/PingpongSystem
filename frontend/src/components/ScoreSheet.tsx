import { useMemo, useState } from 'react'
import { KnockoutMatch, Match, ResultType, ScorePayload } from '../api'

type GameDraft = { a: string; b: string }

export default function ScoreSheet({ match, sideA, sideB, gamesToWin, pointsToWin, busy, detailMode = false, onClose, onSave }: {
  match: Match | KnockoutMatch
  sideA: string
  sideB: string
  gamesToWin: number
  pointsToWin: number
  busy: boolean
  /** 仅小组赛使用：可主动补录，也可在出线无法区分时按提示补录。 */
  detailMode?: boolean
  onClose: () => void
  onSave: (payload: ScorePayload) => Promise<void>
}) {
  const oldGames = 'games' in match ? match.games : []
  const [scoreA, setScoreA] = useState(match.player_a_score === null ? '0' : String(match.player_a_score))
  const [scoreB, setScoreB] = useState(match.player_b_score === null ? '0' : String(match.player_b_score))
  const initialGameCount = Math.max(1, Number(scoreA) + Number(scoreB) || gamesToWin)
  const [games, setGames] = useState<GameDraft[]>(oldGames.length
    ? oldGames.map((game) => ({ a: String(game.side_a_score), b: String(game.side_b_score) }))
    : Array.from({ length: initialGameCount }, () => ({ a: '0', b: '0' })))
  const [resultType, setResultType] = useState<ResultType>('NORMAL')
  const [note, setNote] = useState('')

  const wins = useMemo(() => games.reduce((sum, game) => {
    const a = Number(game.a)
    const b = Number(game.b)
    if (game.a !== '' && game.b !== '' && a !== b) sum[a > b ? 0 : 1] += 1
    return sum
  }, [0, 0]), [games])
  const bigA = Number(scoreA)
  const bigB = Number(scoreB)
  const validBigScore = scoreA !== '' && scoreB !== '' && bigA !== bigB
    && Math.max(bigA, bigB) === gamesToWin && Math.min(bigA, bigB) >= 0 && Math.min(bigA, bigB) < gamesToWin
  const validDetails = games.length === bigA + bigB && wins[0] === bigA && wins[1] === bigB
  const sideAId = 'entry_a_id' in match ? (match.entry_a_id ?? match.player_a_id) : match.player_a?.id ?? null
  const sideBId = 'entry_b_id' in match ? (match.entry_b_id ?? match.player_b_id) : match.player_b?.id ?? null

  const update = (index: number, side: 'a' | 'b', value: string) => {
    setGames((current) => current.map((game, i) => i === index ? { ...game, [side]: value } : game))
  }

  const saveNormal = () => onSave(detailMode ? {
    player_a_score: bigA,
    player_b_score: bigB,
    games: games.map((game) => ({ side_a_score: Number(game.a), side_b_score: Number(game.b) })),
    result_type: 'NORMAL',
    note: note || undefined,
  } : {
    player_a_score: bigA,
    player_b_score: bigB,
    result_type: 'NORMAL',
    note: note || undefined,
  })

  const saveException = (forfeitId: number | null) => onSave({
    result_type: resultType,
    forfeit_entry_id: forfeitId,
    note: note || undefined,
  })

  return (
    <div className="modal-backdrop score-sheet-backdrop" role="dialog" aria-modal="true" aria-label={detailMode ? '补录小组赛逐局小分' : '录入比赛大比分'}>
      <div className="score-sheet">
        <button className="modal-close" onClick={onClose} aria-label="关闭">×</button>
        <span className="eyebrow">MATCH #{match.id}</span>
        <h2>{detailMode ? '补录逐局小分' : '确认比赛结果'}</h2>
        <div className="score-sheet-versus">
          <strong>{sideA}</strong><span>{detailMode ? `${bigA} : ${bigB}` : 'VS'}</span><strong>{sideB}</strong>
        </div>

        {!detailMode && <div className="result-tabs">
          <button className={resultType === 'NORMAL' ? 'active' : ''} onClick={() => setResultType('NORMAL')}>正常完赛</button>
          <button className={resultType !== 'NORMAL' ? 'active' : ''} onClick={() => setResultType('FORFEIT')}>弃权 / 未到</button>
        </div>}

        {resultType === 'NORMAL' ? detailMode ? (
          <>
            <p className="score-rule detail-callout">补录小比分不会改变已确认的大比分；完整录入后可用于小组排名的同分判定。</p>
            <div className="game-input-list">
              {games.map((game, index) => (
                <div className="game-input" key={index}>
                  <span>第 {index + 1} 局</span>
                  <input aria-label={`第${index + 1}局${sideA}得分`} type="number" min={0} max={99} value={game.a} onChange={(event) => update(index, 'a', event.target.value)} />
                  <i>:</i>
                  <input aria-label={`第${index + 1}局${sideB}得分`} type="number" min={0} max={99} value={game.b} onChange={(event) => update(index, 'b', event.target.value)} />
                </div>
              ))}
            </div>
            <p className="score-rule">共 {bigA + bigB} 局 · 每局 {pointsToWin} 分 · {pointsToWin - 1}:{pointsToWin - 1} 后领先 2 分</p>
          </>
        ) : (
          <>
            <div className="big-score-entry">
              <label><span>{sideA}</span><input aria-label={`${sideA}大比分`} type="number" min={0} max={gamesToWin} value={scoreA} onChange={(event) => setScoreA(event.target.value)} /></label>
              <b>:</b>
              <label><span>{sideB}</span><input aria-label={`${sideB}大比分`} type="number" min={0} max={gamesToWin} value={scoreB} onChange={(event) => setScoreB(event.target.value)} /></label>
            </div>
            <p className="score-rule">现场先录大比分，例如 {gamesToWin}:0 或 {gamesToWin}:1；逐局小比分可在已结束比赛中按需补录。</p>
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
          {resultType === 'NORMAL' && <button className="btn primary" onClick={saveNormal} disabled={!(detailMode ? validBigScore && validDetails : validBigScore) || busy}>
            {detailMode ? '保存小分并重新排名' : '确认大比分'}
          </button>}
        </div>
      </div>
    </div>
  )
}
