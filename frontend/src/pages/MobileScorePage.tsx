/**
 * 手机录分页（D 轨 Day 3）。
 *
 * ## 定位
 *
 * 现场裁判用手机打开**一场比赛**，快速录分。它不重写任何比分业务：
 *
 * - 比分合法性、小比分与大比分一致性、异常结果计分、改分下游影响
 *   → 全部由后端 `backend/app/services/scores.py` 裁决；
 * - 本页只负责：手机可点的输入、明显的可选小分入口、可读的错误展示、防重复提交；
 * - 写入用的仍然是**同一条** `POST /api/matches/{matchId}/score`（`api.recordScore`），
 *   没有第二条比分写入通道，本页也不是新的业务真相源：
 *   提交成功后一律**重新拉取真实 Match**，不靠本地 state 假装 FINISHED。
 *
 * ## 赛事上下文
 *
 * `tid` 与 `matchId` 只来自路由 path（`/admin/t/:tid/score/:matchId`），
 * 由 `MobileScoreRoutes.tsx` 中**已匹配的 route adapter** 解析后传入。
 * 本页不读 `localStorage.activeTournamentId`，也不读 `?tid=`，
 * 因此不会出现“打开别人的赛事/比赛”。
 *
 * ## 认证边界
 *
 * 见 `MobileScoreRoutes.tsx::AdminScoreGuardBoundary` —— 本页只发布 `P`（props），
 * 不实现任何登录态、token 或第二套权限系统。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, Match, Player, ResultType, ScorePayload, Tournament } from '../api'
import { formatName } from '../format'
import {
  ABNORMAL_RESULT_TYPES,
  GameDraft,
  RESULT_TYPE_LABELS,
  abnormalResultLabel,
  buildAbnormalScorePayload,
  buildNormalScorePayload,
  gamesScoreLabel,
  matchSidesReady,
  matchStageLabel,
  matchStatusLabel,
  parseScoreInput,
} from '../mobileScore'
import './MobileScorePage.css'

const OPERATOR_STORAGE_KEY = 'pingpong_referee_name'

/** 页面上一次最多展示的逐局行数（赛制上限，不是“必须填几局”）。 */
function maxGameRows(gamesToWin: number): number {
  return Math.max(1, gamesToWin * 2 - 1)
}

type Mode = 'normal' | 'abnormal'

interface LoadedData {
  tournament: Tournament
  match: Match
  players: Player[]
  groupName: string | null
  tableName: string | null
}

/** 加载失败时页面需要的语义（不是网络层错误码）。 */
type LoadFailure =
  | { kind: 'invalid-link'; title: string; detail: string }
  | { kind: 'tournament-missing'; title: string; detail: string }
  | { kind: 'match-missing'; title: string; detail: string }
  | { kind: 'network'; title: string; detail: string }
  | { kind: 'server'; title: string; detail: string; status: number }

function describeLoadError(error: unknown, tid: number): LoadFailure {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return {
        kind: 'tournament-missing',
        title: '赛事不可用',
        detail: `该赛事不存在，或已被删除：#${tid}。请确认链接后重新扫码/重新打开。`,
      }
    }
    if (error.status === 401 || error.status === 403) {
      return {
        kind: 'server',
        title: '没有访问权限',
        detail: error.message,
        status: error.status,
      }
    }
    return { kind: 'server', title: '加载失败', detail: error.message, status: error.status }
  }
  return {
    kind: 'network',
    title: '网络连接失败',
    detail: '网络连接失败，请检查局域网连接后重试。',
  }
}

export default function MobileScorePage({ tid, matchId }: { tid: number; matchId: number }) {
  const [data, setData] = useState<LoadedData | null>(null)
  const [failure, setFailure] = useState<LoadFailure | null>(null)

  // ---- 表单状态（提交失败时**不得**清空） ----
  const [mode, setMode] = useState<Mode>('normal')
  const [scoreA, setScoreA] = useState('')
  const [scoreB, setScoreB] = useState('')
  const [gamesOpen, setGamesOpen] = useState(false)
  const [games, setGames] = useState<GameDraft[]>([])
  const [resultType, setResultType] = useState<ResultType>('FORFEIT')
  const [forfeitSide, setForfeitSide] = useState<'a' | 'b' | null>(null)
  const [note, setNote] = useState('')
  const [noteOpen, setNoteOpen] = useState(false)
  const [operatorName, setOperatorName] = useState(() => {
    try {
      return localStorage.getItem(OPERATOR_STORAGE_KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [confirmAbnormal, setConfirmAbnormal] = useState(false)

  // ---- 提交状态 ----
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  /**
   * 防重复提交的第二道锁（第一道是按钮 `disabled`）。
   *
   * 现场手机上连点会**在同一个事件循环内**触发多次 handler；React 的 state 更新是异步的，
   * 只看 `submitting` 仍可能放过第二次点击，因此这里用 ref 做同步判定。
   */
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    const [tournament, matches, players, groups] = await Promise.all([
      api.getTournament(tid),
      api.listMatches(tid),
      api.listPlayers(tid).catch(() => [] as Player[]),
      api.getGroups(tid).catch(() => null),
    ])

    const match = matches.find((item) => item.id === matchId)
    if (!match) {
      setData(null)
      setFailure({
        kind: 'match-missing',
        title: '比赛不存在',
        detail: `本赛事（#${tid}）里没有编号为 #${matchId} 的比赛。请确认链接是否属于当前赛事。`,
      })
      return
    }

    const groupName = match.group_id === null
      ? null
      : groups?.groups.find((group) => group.id === match.group_id)?.name ?? null

    // 球台号：优先用赛事球台列表里的名字（“1 号台”），取不到就退回 #id，不猜位置。
    let tableName: string | null = null
    if (match.table_id !== null) {
      const dashboard = await api.getDashboard(tid).catch(() => null)
      const table = dashboard?.tables.find((item) => item.id === match.table_id) ?? null
      tableName = table?.name ?? `#${match.table_id}`
    }

    setFailure(null)
    setData({ tournament, match, players, groupName, tableName })
  }, [tid, matchId])

  useEffect(() => {
    let active = true
    setData(null)
    setFailure(null)
    load().catch((error: unknown) => {
      if (!active) return
      setFailure(describeLoadError(error, tid))
    })
    return () => {
      active = false
    }
  }, [load, tid, matchId])

  const tournament = data?.tournament ?? null
  const match = data?.match ?? null
  const players = data?.players ?? []

  /** 名称解析：后端 entry 名优先（双打/团体同样适用），其次按选手 id 查名单。 */
  const sideName = useCallback(
    (side: 'a' | 'b'): string => {
      if (!match) return '待定'
      const entryName = side === 'a' ? match.entry_a_name : match.entry_b_name
      if (entryName && entryName.trim() !== '') return entryName
      const playerId = side === 'a' ? match.player_a_id : match.player_b_id
      if (playerId === null) return '待定'
      return players.find((player) => player.id === playerId)?.name ?? `#${playerId}`
    },
    [match, players],
  )

  const entryIds = useMemo(
    () => ({
      a: match ? match.entry_a_id ?? match.player_a_id ?? null : null,
      b: match ? match.entry_b_id ?? match.player_b_id ?? null : null,
    }),
    [match],
  )

  const names = useMemo(() => ({ a: sideName('a'), b: sideName('b') }), [sideName])

  const gamesToWin = tournament?.games_to_win ?? 0
  const pointsToWin = tournament?.points_to_win ?? 0
  const rowCap = gamesToWin > 0 ? maxGameRows(gamesToWin) : 0

  // ---------------------------------------------------------------- 大比分交互
  //
  // 只做“数字输入 + 步进”这类交互便利，不做合法性业务判定（交给后端）。
  // 唯一的自动补全发生在**步进按钮**上：点 `+` 加到本赛事胜局上限时，把另一方收敛到
  // 有效区间，避免裁判在手机上敲出 5:4 这类必然被拒的值。
  // 手动输入时**绝不**偷偷改另一方 —— 否则“只填了一边”的空值提示永远不会出现，
  // 而且会掩盖裁判真正想录入的比分。
  const applyBigScore = useCallback(
    (side: 'a' | 'b', value: string) => {
      if (side === 'a') setScoreA(value)
      else setScoreB(value)
    },
    [],
  )

  const bumpScore = (side: 'a' | 'b', delta: number) => {
    if (gamesToWin <= 0 || submitting) return
    const current = side === 'a' ? scoreA : scoreB
    const other = side === 'a' ? scoreB : scoreA
    const otherApply = side === 'a' ? setScoreB : setScoreA
    const base = parseScoreInput(current) ?? 0
    const next = Math.max(0, Math.min(gamesToWin, base + delta))
    applyBigScore(side, String(next))
    if (next !== gamesToWin) return
    const otherValue = parseScoreInput(other)
    if (otherValue !== null && otherValue >= 0 && otherValue < gamesToWin) return
    otherApply(String(gamesToWin - 1))
  }

  // ---------------------------------------------------------------- 逐局小比分（可选）
  const openGames = () => {
    setGamesOpen(true)
    setGames((current) => {
      if (current.length > 0) return current
      const a = parseScoreInput(scoreA) ?? 0
      const b = parseScoreInput(scoreB) ?? 0
      const rows = Math.min(Math.max(a + b, 1), Math.max(rowCap, 1))
      return Array.from({ length: rows }, () => ({ a: '', b: '' }))
    })
  }

  const updateGame = (index: number, side: 'a' | 'b', value: string) => {
    setGames((current) => current.map((game, i) => (i === index ? { ...game, [side]: value } : game)))
  }

  const addGame = () => setGames((current) => (current.length >= rowCap ? current : [...current, { a: '', b: '' }]))

  const removeGame = (index: number) => setGames((current) => current.filter((_, i) => i !== index))

  // ---------------------------------------------------------------- 提交
  const runSubmit = async (payload: ScorePayload) => {
    if (!match || inFlight.current) return
    inFlight.current = true
    setSubmitting(true)
    setFormError(null)
    setConfirmAbnormal(false)
    try {
      const trimmedOperator = operatorName.trim()
      await api.recordScore(match.id, payload)
      if (trimmedOperator !== '') {
        try {
          localStorage.setItem(OPERATOR_STORAGE_KEY, trimmedOperator)
        } catch {
          // 隐私模式下 localStorage 不可用；不影响录分主流程
        }
      }
      // 不以本地 state 假装成功：重新拉取真实 Match（状态、比分、小比分均以服务端为准）。
      // 成功态由重新加载后的 match.status === 'FINISHED' 驱动，不依赖本次提交参数。
      await load()
    } catch (error) {
      // 网络失败不得清空用户输入：这里只设置错误文案，表单状态保持原样。
      if (error instanceof ApiError) {
        setFormError(describeSubmitError(error))
      } else {
        setFormError('网络连接失败，请检查局域网连接后重试')
      }
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  const submitNormal = async () => {
    if (inFlight.current || !match) return
    const { payload, error } = buildNormalScorePayload({
      scoreA,
      scoreB,
      games: gamesOpen ? games : [],
      gamesToWin,
      operatorName,
      note,
    })
    if (!payload) {
      setFormError(error)
      return
    }
    await runSubmit(payload)
  }

  const submitAbnormal = async () => {
    if (inFlight.current || !match) return
    const entryId = forfeitSide === null ? null : entryIds[forfeitSide]
    if (entryId === null) {
      setFormError('请选择异常结果对应的一方。')
      return
    }
    const { payload, error } = buildAbnormalScorePayload({
      resultType,
      forfeitEntryId: entryId,
      operatorName,
      note,
    })
    if (!payload) {
      setFormError(error)
      return
    }
    if (!confirmAbnormal) {
      setConfirmAbnormal(true)
      setFormError(null)
      return
    }
    await runSubmit(payload)
  }

  // ---------------------------------------------------------------- 渲染
  if (failure) {
    return (
      <div className="ms-shell">
        <div className="ms-message" role="alert">
          <h1>{failure.title}</h1>
          <p>{failure.detail}</p>
          <div className="ms-message-actions">
            <Link className="ms-btn" to={`/console?tid=${tid}`}>
              返回比赛控制台
            </Link>
            <Link className="ms-btn ms-btn--ghost" to={`/public/t/${tid}/live`}>
              查看赛事实况
            </Link>
          </div>
        </div>
      </div>
    )
  }

  if (!data || !match || !tournament) {
    return (
      <div className="ms-shell">
        <p className="ms-loading" role="status">
          正在加载比赛…
        </p>
      </div>
    )
  }

  // 提交成功后的“完成态”：依据**服务端返回的真实 Match**，不依据本地提交参数。
  const finished = match.status === 'FINISHED'
  const finishedAbnormal = finished && match.result_type !== null && match.result_type !== 'NORMAL'
  const finishedGames = match.games ?? []

  if (finished) {
    return (
      <div className="ms-shell">
        <FinishedView
          entryIds={entryIds}
          groupName={data.groupName}
          match={match}
          names={names}
          resultLabel={abnormalResultLabel(match.result_type ?? 'NORMAL', match.forfeit_entry_id, names, entryIds)}
          abnormal={finishedAbnormal}
          gamesLabel={finishedGames.length > 0 ? gamesScoreLabel(finishedGames) : null}
          tableName={data.tableName}
          tournament={tournament}
          tid={tid}
        />
      </div>
    )
  }

  const sidesReady = matchSidesReady(match)
  const normalHint = describeNormalHint(scoreA, scoreB, gamesToWin, gamesOpen ? games : [], pointsToWin)

  return (
    <div className="ms-shell">
      <header className="ms-header">
        <div className="ms-header-top">
          <span className="ms-brand" aria-hidden="true">
            TT
          </span>
          <div className="ms-header-title">
            <strong>{tournament.name}</strong>
            <span>{matchStageLabel(match, data.groupName)}</span>
          </div>
        </div>
        <div className="ms-header-meta">
          <span className="ms-chip">{matchStatusLabel(match.status)}</span>
          <span className="ms-chip">球台：{data.tableName ?? '未安排'}</span>
          <span className="ms-chip">比赛 #{match.id}</span>
          <span className="ms-chip">{formatName(gamesToWin)}</span>
          <span className="ms-chip">每局 {pointsToWin} 分</span>
        </div>
      </header>

      <section className="ms-versus" aria-label="本场对阵">
        <div className="ms-side">
          <span className="ms-side-tag">A</span>
          <strong className="ms-side-name" title={names.a}>
            {names.a}
          </strong>
        </div>
        <span className="ms-versus-mark">VS</span>
        <div className="ms-side ms-side--b">
          <span className="ms-side-tag">B</span>
          <strong className="ms-side-name" title={names.b}>
            {names.b}
          </strong>
        </div>
      </section>

      {!sidesReady && (
        <p className="ms-notice ms-notice--warn" role="status">
          本场对手尚未确定（等待上一轮结果）。此时无法录分。
        </p>
      )}

      {/*
        模式切换用的是 aria-pressed 而不是 ARIA tab 角色：
        这里没有 tabpanel / 键盘左右切换语义，用 `role="tab"` 反而会让屏幕阅读器
        期待并不存在的 tab 行为（而且会覆盖 button 角色）。
      */}
      <div className="ms-mode-tabs" aria-label="录入类型">
        <button
          aria-pressed={mode === 'normal'}
          className={`ms-mode-tab${mode === 'normal' ? ' is-active' : ''}`}
          onClick={() => {
            setMode('normal')
            setFormError(null)
            setConfirmAbnormal(false)
          }}
          type="button"
        >
          正常比赛
        </button>
        <button
          aria-pressed={mode === 'abnormal'}
          className={`ms-mode-tab${mode === 'abnormal' ? ' is-active' : ''}`}
          onClick={() => {
            setMode('abnormal')
            setFormError(null)
            setConfirmAbnormal(false)
          }}
          type="button"
        >
          异常结果
        </button>
      </div>

      {mode === 'normal' ? (
        <section className="ms-card" aria-label="大比分录入">
          <div className="ms-score-grid">
            <div className="ms-score-side">
              <span className="ms-score-who">{names.a}</span>
              <div className="ms-score-row">
                <button
                  aria-label={`${names.a} 减一局`}
                  className="ms-step"
                  disabled={submitting}
                  onClick={() => bumpScore('a', -1)}
                  type="button"
                >
                  −
                </button>
                <input
                  aria-label={`${names.a} 大比分`}
                  className="ms-score-input"
                  disabled={submitting}
                  inputMode="numeric"
                  min={0}
                  onChange={(event) => applyBigScore('a', event.target.value)}
                  pattern="[0-9]*"
                  type="number"
                  value={scoreA}
                />
                <button
                  aria-label={`${names.a} 加一局`}
                  className="ms-step"
                  disabled={submitting}
                  onClick={() => bumpScore('a', 1)}
                  type="button"
                >
                  +
                </button>
              </div>
            </div>

            <span className="ms-score-colon" aria-hidden="true">
              :
            </span>

            <div className="ms-score-side ms-score-side--b">
              <span className="ms-score-who">{names.b}</span>
              <div className="ms-score-row">
                <button
                  aria-label={`${names.b} 减一局`}
                  className="ms-step"
                  disabled={submitting}
                  onClick={() => bumpScore('b', -1)}
                  type="button"
                >
                  −
                </button>
                <input
                  aria-label={`${names.b} 大比分`}
                  className="ms-score-input"
                  disabled={submitting}
                  inputMode="numeric"
                  min={0}
                  onChange={(event) => applyBigScore('b', event.target.value)}
                  pattern="[0-9]*"
                  type="number"
                  value={scoreB}
                />
                <button
                  aria-label={`${names.b} 加一局`}
                  className="ms-step"
                  disabled={submitting}
                  onClick={() => bumpScore('b', 1)}
                  type="button"
                >
                  +
                </button>
              </div>
            </div>
          </div>
          <p className="ms-hint">
            大比分必填（先胜 {gamesToWin} 局者胜）。逐局小比分可以不录。
          </p>
        </section>
      ) : (
        <section className="ms-card" aria-label="异常结果">
          <label className="ms-field">
            <span>结果类型</span>
            <select
              disabled={submitting}
              onChange={(event) => {
                setResultType(event.target.value as ResultType)
                setConfirmAbnormal(false)
                setFormError(null)
              }}
              value={resultType}
            >
              {ABNORMAL_RESULT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {RESULT_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="ms-field ms-field--radio">
            <legend>异常方</legend>
            {(['a', 'b'] as const).map((side) => (
              <label className="ms-radio" key={side}>
                <input
                  checked={forfeitSide === side}
                  disabled={submitting}
                  name="ms-forfeit-side"
                  onChange={() => {
                    setForfeitSide(side)
                    setConfirmAbnormal(false)
                    setFormError(null)
                  }}
                  type="radio"
                  value={side}
                />
                <span>{names[side]}</span>
              </label>
            ))}
          </fieldset>

          <p className="ms-hint">
            异常结果不会生成逐局小比分。小组赛的排名行政比分由服务端按赛事规则计入。
          </p>
        </section>
      )}

      {mode === 'normal' && (
        <section className="ms-card ms-card--games">
          {!gamesOpen ? (
            <button className="ms-games-toggle" onClick={openGames} type="button">
              + 录入逐局小比分（可选）
            </button>
          ) : (
            <>
              <div className="ms-games-head">
                <strong>逐局小比分（可选）</strong>
                <button
                  className="ms-games-close"
                  onClick={() => {
                    setGamesOpen(false)
                    setGames([])
                  }}
                  type="button"
                >
                  收起并清空
                </button>
              </div>
              <div className="ms-games-list">
                {games.map((game, index) => (
                  <div className="ms-game-row" key={index}>
                    <span className="ms-game-no">第 {index + 1} 局</span>
                    <div className="ms-game-inputs">
                      <input
                        aria-label={`第${index + 1}局${names.a}得分`}
                        disabled={submitting}
                        inputMode="numeric"
                        min={0}
                        onChange={(event) => updateGame(index, 'a', event.target.value)}
                        pattern="[0-9]*"
                        type="number"
                        value={game.a}
                      />
                      <i aria-hidden="true">:</i>
                      <input
                        aria-label={`第${index + 1}局${names.b}得分`}
                        disabled={submitting}
                        inputMode="numeric"
                        min={0}
                        onChange={(event) => updateGame(index, 'b', event.target.value)}
                        pattern="[0-9]*"
                        type="number"
                        value={game.b}
                      />
                    </div>
                    <button
                      aria-label={`删除第 ${index + 1} 局`}
                      className="ms-game-remove"
                      disabled={submitting}
                      onClick={() => removeGame(index)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
              <div className="ms-games-actions">
                {/* 已经到达本赛制上限时不给“再加一局”，避免导出一个必然被服务端拒绝的半成品 */}
                {games.length < rowCap && (
                  <button
                    className="ms-btn ms-btn--ghost"
                    disabled={submitting}
                    onClick={addGame}
                    type="button"
                  >
                    再加一局
                  </button>
                )}
                <span className="ms-games-count">
                  共 {games.length} 局（上限 {rowCap}）
                </span>
              </div>
              <p className="ms-hint">
                录了就要录完：每一局两边都要填。逐局胜局汇总必须与大比分一致，否则服务端会拒绝并说明原因。
              </p>
            </>
          )}
        </section>
      )}

      <section className="ms-card ms-card--notes">
        <label className="ms-field">
          <span>操作人（选填）</span>
          <input
            autoComplete="off"
            disabled={submitting}
            maxLength={100}
            onChange={(event) => setOperatorName(event.target.value)}
            placeholder="填写后随比分一起留痕"
            type="text"
            value={operatorName}
          />
        </label>
        {!noteOpen ? (
          <button className="ms-link-btn" onClick={() => setNoteOpen(true)} type="button">
            + 添加备注（选填）
          </button>
        ) : (
          <label className="ms-field">
            <span>备注（选填）</span>
            <textarea
              disabled={submitting}
              maxLength={500}
              onChange={(event) => setNote(event.target.value)}
              placeholder="迟到、判罚或现场说明"
              rows={2}
              value={note}
            />
          </label>
        )}
      </section>

      {formError && (
        <p className="ms-error" role="alert">
          {formError}
        </p>
      )}

      {confirmAbnormal && (
        <div className="ms-confirm" role="alertdialog" aria-label="确认异常结果">
          <p>
            确认将本场比赛记录为「{RESULT_TYPE_LABELS[resultType]}」？异常方：{forfeitSide ? names[forfeitSide] : '未选择'}
          </p>
          <div className="ms-confirm-actions">
            <button
              className="ms-btn ms-btn--ghost"
              onClick={() => setConfirmAbnormal(false)}
              type="button"
            >
              再检查一下
            </button>
            <button className="ms-btn ms-btn--danger" disabled={submitting} onClick={submitAbnormal} type="button">
              {submitting ? '提交中…' : '确认提交'}
            </button>
          </div>
        </div>
      )}

      <div className="ms-submit-bar">
        {normalHint && mode === 'normal' && <p className="ms-submit-hint">{normalHint}</p>}
        <button
          className="ms-submit"
          disabled={submitting || !sidesReady}
          onClick={mode === 'normal' ? submitNormal : submitAbnormal}
          type="button"
        >
          {submitting ? '提交中…' : mode === 'normal' ? '确认提交大比分' : '提交异常结果'}
        </button>
        <div className="ms-submit-links">
          <Link to={`/console?tid=${tid}`}>返回比赛控制台</Link>
          <Link to={`/public/t/${tid}/live`}>查看赛事实况</Link>
        </div>
      </div>
    </div>
  )
}

/** 后端 4xx 的可读文案：尽量让裁判知道哪里有问题，而不是统一“提交失败”。 */
function describeSubmitError(error: ApiError): string {
  if (error.status === 422) return `服务端未接受本次比分：${error.message}`
  if (error.status === 409) return `当前比赛状态不允许这样操作：${error.message}`
  if (error.status === 404) return `比赛不存在或已不属于本赛事：${error.message}`
  if (error.status === 401) return `登录状态已失效，请重新登录后再提交。（${error.message}）`
  if (error.status === 403) return `当前账号没有本赛事的录分权限：${error.message}`
  if (error.status >= 500) return `服务端出错，本次比分未保存：${error.message}`
  return error.message
}

/**
 * 大比分 / 小比分的**交互提示**（不是业务裁决）。
 *
 * 明确不做：合法局分判定、胜负汇总计算、一致性结论 —— 那些由后端返回。
 * 这里只说“还没填完 / 明显不是数字 / 明显平局”这类肉眼可见的问题。
 */
function describeNormalHint(
  scoreA: string,
  scoreB: string,
  gamesToWin: number,
  games: GameDraft[],
  pointsToWin: number,
): string | null {
  const emptyA = scoreA.trim() === ''
  const emptyB = scoreB.trim() === ''
  if (emptyA && emptyB) return null
  if (emptyA || emptyB) return '还有一方的大比分没有填写。'

  const a = parseScoreInput(scoreA)
  const b = parseScoreInput(scoreB)
  if (a === null || b === null) return '大比分只能填写 0 以上的整数。'
  if (a === b) return '大比分不能平局。'

  if (games.length > 0) {
    const half = games.findIndex(
      (game) => (game.a.trim() === '') !== (game.b.trim() === ''),
    )
    if (half >= 0) return `第 ${half + 1} 局只填了一边，请补全或删除该局。`
  }

  if (Math.max(a, b) !== gamesToWin) {
    return `本赛事 ${gamesToWin} 局制：胜方大比分应为 ${gamesToWin}。`
  }
  if (games.length === 0) return null
  return `逐局小比分将随大比分一起提交；每局 ${pointsToWin} 分制，最终一致性由服务端校验。`
}

/** 已结束比赛的展示：区分「异常结果」与「正常逐局比分」，不复用改分流程。 */
function FinishedView({
  match,
  tournament,
  tid,
  names,
  entryIds,
  abnormal,
  resultLabel,
  gamesLabel,
  groupName,
  tableName,
}: {
  match: Match
  tournament: Tournament
  tid: number
  names: { a: string; b: string }
  entryIds: { a: number | null; b: number | null }
  abnormal: boolean
  resultLabel: string
  gamesLabel: string | null
  groupName: string | null
  tableName: string | null
}) {
  const winnerSide =
    entryIds.a !== null && entryIds.a === match.winner_entry_id ? 'a'
      : entryIds.b !== null && entryIds.b === match.winner_entry_id ? 'b'
        : match.winner_id !== null && match.winner_id === match.player_a_id ? 'a'
          : match.winner_id !== null && match.winner_id === match.player_b_id ? 'b'
            : (match.player_a_score ?? 0) > (match.player_b_score ?? 0) ? 'a' : 'b'

  return (
    <div className="ms-finished">
      <header className="ms-header">
        <div className="ms-header-top">
          <span className="ms-brand" aria-hidden="true">
            TT
          </span>
          <div className="ms-header-title">
            <strong>{tournament.name}</strong>
            <span>{matchStageLabel(match, groupName)}</span>
          </div>
        </div>
        <div className="ms-header-meta">
          <span className="ms-chip">已结束</span>
          <span className="ms-chip">球台：{tableName ?? '未安排'}</span>
          <span className="ms-chip">比赛 #{match.id}</span>
        </div>
      </header>

      <section className={`ms-done${abnormal ? ' ms-done--abnormal' : ''}`}>
        <p className="ms-done-title">比分已保存</p>

        {abnormal ? (
          <>
            <p className="ms-done-result">{resultLabel}</p>
            <p className="ms-versus-line">
              {names.a} <i>VS</i> {names.b}
            </p>
            <p className="ms-done-note">异常结果，没有逐局小比分。</p>
            {match.player_a_score !== null && match.player_b_score !== null
              && (match.player_a_score !== 0 || match.player_b_score !== 0) && (
                <p className="ms-done-admin">
                  排名用行政比分：{names.a} {match.player_a_score} : {match.player_b_score} {names.b}
                  （由服务端按赛事规则计入，不是现场逐局比分）
                </p>
              )}
          </>
        ) : (
          <>
            <p className="ms-done-score">
              <span className={winnerSide === 'a' ? 'is-winner' : ''}>{names.a}</span>
              <b>
                {match.player_a_score} : {match.player_b_score}
              </b>
              <span className={winnerSide === 'b' ? 'is-winner' : ''}>{names.b}</span>
            </p>
            <p className="ms-done-result">比赛已结束</p>
            {gamesLabel ? (
              <p className="ms-done-games">逐局小比分：{gamesLabel}</p>
            ) : (
              <p className="ms-done-note">本场只录入了大比分，没有逐局小比分。</p>
            )}
          </>
        )}

        {match.result_note && <p className="ms-done-note">备注：{match.result_note}</p>}
      </section>

      <div className="ms-finished-actions">
        <Link className="ms-btn" to={`/console?tid=${tid}`}>
          返回比赛控制台
        </Link>
        <Link className="ms-btn ms-btn--ghost" to={`/public/t/${tid}/live`}>
          查看当前赛事
        </Link>
        <Link className="ms-btn ms-btn--ghost" to={`/match-print?tid=${tid}&mid=${match.id}`}>
          打印成绩单
        </Link>
      </div>

      <p className="ms-hint ms-finished-hint">
        比赛已结束。如需修改结果，请前往赛事管理端（本页只用于现场首次录分）。
      </p>
    </div>
  )
}
