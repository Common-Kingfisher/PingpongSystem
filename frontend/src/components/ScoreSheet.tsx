import { useMemo, useState } from 'react'
import { KnockoutMatch, Match, ResultType, ScorePayload } from '../api'
import TouchScoreInput from './field/TouchScoreInput'

type GameDraft = { a: string; b: string }

export default function ScoreSheet({ match, sideA, sideB, gamesToWin, pointsToWin, busy, detailMode = false, auditMode = 'record', submitError = null, onClose, onSave }: {
  match: Match | KnockoutMatch
  sideA: string
  sideB: string
  gamesToWin: number
  pointsToWin: number
  busy: boolean
  /** FINISHED GROUP 比赛的逐局小分补录/修改模式；默认 false = 大比分录入/修改。 */
  detailMode?: boolean
  auditMode?: 'record' | 'revise'
  submitError?: { title: string; message: string } | null
  onClose: () => void
  onSave: (payload: ScorePayload) => Promise<void>
}) {
  const existingGames = 'games' in match ? match.games : []
  const existingNote = 'result_note' in match ? match.result_note : null

  const originalA = match.player_a_score
  const originalB = match.player_b_score
  // 历史仅大比分（无 MatchGame）的已结束 GROUP 比赛：可补录逐局小分用于排名。
  const aggregateOnlyHistory = detailMode && 'games' in match && existingGames.length === 0

  // 备注：回填已有备注；仅当用户修改时才提交，避免空串静默清空原备注。
  const [note, setNote] = useState(existingNote ?? '')
  const [noteDirty, setNoteDirty] = useState(false)
  const updateNote = (value: string) => { setNote(value); setNoteDirty(true) }
  const notePayload = noteDirty ? note : undefined

  // 默认模式：大比分录入/修改。新比赛默认 0:0，现场直接改成 {gamesToWin}:{0..gamesToWin-1}。
  const [scoreA, setScoreA] = useState(originalA === null ? '0' : String(originalA))
  const [scoreB, setScoreB] = useState(originalB === null ? '0' : String(originalB))
  const [resultType, setResultType] = useState<ResultType>('NORMAL')
  const [operatorName, setOperatorName] = useState(() => localStorage.getItem('pingpong_referee_name') ?? '')
  const [changeReason, setChangeReason] = useState('')
  const [revisionPending, setRevisionPending] = useState<
    { kind: 'normal' } | { kind: 'exception'; forfeitId: number | null; sideLabel: string } | null
  >(null)
  const auditReady = operatorName.trim().length > 0
    && (auditMode === 'record' || changeReason.trim().length >= 2)

  const auditPayload = () => {
    const operator = operatorName.trim()
    if (operator) localStorage.setItem('pingpong_referee_name', operator)
    return {
      operator_name: operator,
      change_reason: auditMode === 'revise' ? changeReason.trim() : '首次录入比赛结果',
    }
  }

  // detailMode：逐局小分补录（局数由已确认大比分决定，不回填 games_to_win*2-1）。
  // 新建补录行默认 0:0；0:0 视为“尚未录入”，不会在弹窗刚打开时显示错误。
  const initialGames: GameDraft[] = existingGames.length
    ? existingGames.map((g) => ({ a: String(g.side_a_score), b: String(g.side_b_score) }))
    : Array.from({ length: (originalA ?? 0) + (originalB ?? 0) }, () => ({ a: '0', b: '0' }))
  const [games, setGames] = useState<GameDraft[]>(initialGames)
  const updateGame = (index: number, side: 'a' | 'b', value: string) => {
    setGames((cur) => cur.map((g, i) => (i === index ? { ...g, [side]: value } : g)))
  }

  // 单局即时校验（服务端仍是最终裁决）。
  const gameHint = (game: GameDraft): string | null => {
    if (game.a === '' || game.b === '') return null
    const a = Number(game.a)
    const b = Number(game.b)
    if (a === 0 && b === 0) return null
    if (a < 0 || b < 0) return '比分不能为负数'
    if (a === b) return '平分无效'
    const winner = Math.max(a, b)
    const loser = Math.min(a, b)
    if (winner < pointsToWin) return `未达到 ${pointsToWin} 分`
    if (loser < pointsToWin - 1) return winner === pointsToWin ? null : `胜方需恰好 ${pointsToWin} 分`
    return winner === loser + 2 ? null : '平分延长后需领先 2 分'
  }

  const wins = useMemo(() => {
    const w = [0, 0]
    for (const g of games) {
      const a = Number(g.a)
      const b = Number(g.b)
      if (g.a !== '' && g.b !== '' && a !== b) w[a > b ? 0 : 1] += 1
    }
    return w
  }, [games])

  const derivedA = wins[0]
  const derivedB = wins[1]
  const allGamesFilled = games.every((g) =>
    g.a !== '' && g.b !== '' && !(g.a === '0' && g.b === '0'))
  const hasInvalidGame = games.some((g) => g.a !== '' && g.b !== '' && gameHint(g) !== null)
  const gamesConsistent = derivedA === originalA && derivedB === originalB
  const canSubmitSupplement = gamesConsistent && !hasInvalidGame && allGamesFilled

  // 默认模式大比分校验
  const bigA = Number(scoreA)
  const bigB = Number(scoreB)
  const validBigScore = scoreA !== '' && scoreB !== '' && bigA !== bigB
    && Math.max(bigA, bigB) === gamesToWin && Math.min(bigA, bigB) >= 0 && Math.min(bigA, bigB) < gamesToWin
  const untouchedZeroScore = scoreA === '0' && scoreB === '0'

  const sideAId = 'games' in match ? (match.entry_a_id ?? match.player_a_id) : match.player_a?.id ?? null
  const sideBId = 'games' in match ? (match.entry_b_id ?? match.player_b_id) : match.player_b?.id ?? null

  const normalPayload = (): ScorePayload => {
    if (detailMode) {
      return {
        player_a_score: originalA ?? 0,
        player_b_score: originalB ?? 0,
        games: games.map((g) => ({ side_a_score: Number(g.a), side_b_score: Number(g.b) })),
        result_type: 'NORMAL',
        note: notePayload,
        ...auditPayload(),
      }
    }
    return {
      player_a_score: bigA,
      player_b_score: bigB,
      result_type: 'NORMAL',
      note: notePayload,
      ...auditPayload(),
    }
  }

  const exceptionPayload = (forfeitId: number | null): ScorePayload => ({
    result_type: resultType,
    forfeit_entry_id: forfeitId,
    note: notePayload,
    ...auditPayload(),
  })

  const requestNormalSave = () => {
    if (auditMode === 'revise') setRevisionPending({ kind: 'normal' })
    else void onSave(normalPayload())
  }

  const requestExceptionSave = (forfeitId: number | null, sideLabel: string) => {
    if (auditMode === 'revise') setRevisionPending({ kind: 'exception', forfeitId, sideLabel })
    else void onSave(exceptionPayload(forfeitId))
  }

  const confirmRevision = () => {
    if (!revisionPending) return
    const payload = revisionPending.kind === 'normal'
      ? normalPayload()
      : exceptionPayload(revisionPending.forfeitId)
    void onSave(payload)
  }

  return (
    <div className="modal-backdrop score-sheet-backdrop" role="dialog" aria-modal="true" aria-label={detailMode ? '补录小组赛逐局小分' : '录入比赛大比分'}>
      <div className="score-sheet">
        <button className="modal-close" onClick={onClose} aria-label="关闭">×</button>
        <span className="eyebrow">MATCH #{match.id}</span>
        <h2>{detailMode ? '补录逐局小分' : auditMode === 'revise' ? '修改比赛结果' : '确认比赛结果'}</h2>
        {submitError && (
          <div className="score-submit-error" role="alert">
            <strong>{submitError.title}</strong>
            <span>{submitError.message}</span>
            <small>已填写内容仍保留，请检查后重试。</small>
          </div>
        )}

        {detailMode ? (
          <>
            <div className="score-sheet-versus">
              <strong>{sideA}</strong><span>{originalA ?? 0} : {originalB ?? 0}</span><strong>{sideB}</strong>
            </div>
            <p className="muted">已确认大比分（只读）：{sideA} {originalA ?? 0} : {originalB ?? 0} {sideB}</p>
            {aggregateOnlyHistory && (
              <p className="status-warn">当前仅保存了大比分，可补录逐局小比分用于排名统计。</p>
            )}
            <div className="game-input-list">
              {games.map((game, index) => {
                const hint = gameHint(game)
                return (
                  <div className="game-input" key={index}>
                    <span>第 {index + 1} 局</span>
                    <input aria-label={`第${index + 1}局${sideA}得分`} type="number" min={0} max={99} value={game.a} onChange={(e) => updateGame(index, 'a', e.target.value)} />
                    <i>:</i>
                    <input aria-label={`第${index + 1}局${sideB}得分`} type="number" min={0} max={99} value={game.b} onChange={(e) => updateGame(index, 'b', e.target.value)} />
                    {hint && <small className="status-error" style={{ gridColumn: '1 / -1' }}>{hint}</small>}
                  </div>
                )
              })}
            </div>
            <p className="score-rule">每局 {pointsToWin} 分 · {pointsToWin - 1}:{pointsToWin - 1} 后领先 2 分 · 先胜 {gamesToWin} 局者胜</p>
            {gamesConsistent && allGamesFilled && !hasInvalidGame ? (
              <p className="status-ok" style={{ margin: '8px 0' }}>逐局胜局与已确认大比分一致。</p>
            ) : hasInvalidGame ? (
              <p className="status-error">存在非法局分，请检查。</p>
            ) : !allGamesFilled ? (
              <p className="status-warn">请填完所有局比分。</p>
            ) : (
              <p className="status-error">逐局胜局汇总为 {derivedA}:{derivedB}，与已确认大比分 {originalA ?? 0}:{originalB ?? 0} 不一致，请检查逐局比分。</p>
            )}
          </>
        ) : (
          <>
            <div className="result-tabs">
              <button className={resultType === 'NORMAL' ? 'active' : ''} onClick={() => setResultType('NORMAL')}>正常完赛</button>
              <button className={resultType !== 'NORMAL' ? 'active' : ''} onClick={() => setResultType('FORFEIT')}>弃权 / 未到</button>
            </div>
            {resultType === 'NORMAL' ? (
              <>
                <div className="big-score-entry">
                  <TouchScoreInput label={sideA} value={scoreA} max={gamesToWin} onChange={setScoreA} side="a" />
                  <b>:</b>
                  <TouchScoreInput label={sideB} value={scoreB} max={gamesToWin} onChange={setScoreB} side="b" />
                </div>
                <p className="score-rule">现场先录大比分：先胜 {gamesToWin} 局；每局 {pointsToWin} 分。逐局小比分仍在已结束的小组赛中按需补录。</p>
                {!untouchedZeroScore && scoreA !== '' && scoreB !== '' && !validBigScore && (
                  <p className="score-rule status-error">大比分应为 {gamesToWin}:0 至 {gamesToWin}:{gamesToWin - 1}（或反之），不能平局、不能超出局数。</p>
                )}
              </>
            ) : (
              <div className="forfeit-panel">
                <label>结果类型
                  <select value={resultType} onChange={(e) => setResultType(e.target.value as ResultType)}>
                    <option value="FORFEIT">主动弃权</option>
                    <option value="NO_SHOW">未到场</option>
                    <option value="DISQUALIFIED">取消资格</option>
                    <option value="WALKOVER">直接晋级</option>
                  </select>
                </label>
                <p>选择弃权一方。淘汰赛中对方直接晋级；小组赛按弃权规则计入排名。</p>
                <div className="forfeit-actions">
                  <button className="btn danger" onClick={() => requestExceptionSave(sideAId, sideA)} disabled={busy || !auditReady}>{sideA} 弃权</button>
                  <button className="btn danger" onClick={() => requestExceptionSave(sideBId, sideB)} disabled={busy || !auditReady}>{sideB} 弃权</button>
                </div>
              </div>
            )}
          </>
        )}

        <label className="score-note">裁判备注
          <input value={note} onChange={(e) => updateNote(e.target.value)} placeholder="选填：迟到、判罚或现场说明" />
        </label>
        <div className="score-audit-fields">
          <label>操作人
            <input value={operatorName} onChange={(event) => setOperatorName(event.target.value)} placeholder="必填：主裁判姓名" />
          </label>
          {auditMode === 'revise' && <label>修改理由
            <textarea value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="必填：说明为什么修改本场结果" />
          </label>}
          <p>本次操作将保存修改前后比分、操作人和时间，记录不可覆盖。</p>
        </div>
        {revisionPending ? (
          <div className="score-revision-confirm" role="alertdialog" aria-label="确认修改已结束比赛">
            <span>REVISION CHECK</span>
            <strong>确认修改已结束的比赛？</strong>
            <p>
              当前记录为 {sideA} {originalA ?? 0} : {originalB ?? 0} {sideB}。
              {revisionPending.kind === 'exception' && ` 本次将登记“${revisionPending.sideLabel} 弃权／未到”。`}
              修改可能影响排名或后续签位，服务端会执行最终校验，并保存操作人、理由和时间。
            </p>
            <div>
              <button className="btn" type="button" onClick={() => setRevisionPending(null)} disabled={busy}>返回检查</button>
              <button className="btn danger" type="button" onClick={confirmRevision} disabled={busy}>确认并保存修改</button>
            </div>
          </div>
        ) : (
          <div className="modal-actions">
            <button className="btn" onClick={onClose}>取消</button>
            {resultType === 'NORMAL' && (
              <button className="btn primary" onClick={requestNormalSave} disabled={(detailMode ? !canSubmitSupplement : !validBigScore) || busy || !auditReady}>
                {detailMode ? '保存小分' : auditMode === 'revise' ? '检查并修改' : '确认大比分'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
