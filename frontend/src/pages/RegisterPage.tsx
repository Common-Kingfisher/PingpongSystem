/**
 * Public 在线报名页（D 轨 Day5D 正式接线）。
 *
 * ## 语义变更（本页最重要的一件事）
 *
 * V0.2 legacy：
 *
 * ```text
 * 公开报名 → api.addPlayer() → 直接成为正式 Player
 * ```
 *
 * V0.3 冻结链路（本页现在的行为）：
 *
 * ```text
 * 公开报名 → POST /api/tournaments/{tid}/registrations
 *          → Registration = PENDING
 *          → 等待 EVENT_ADMIN 确认（C5 / 管理端）
 *          → 确认后才创建正式 Player
 * ```
 *
 * 因此本页**不再**持有下列能力（这是 D5D 的硬边界）：
 * 创建正式 Player / 创建 Entry / 创建 Match / 确认报名 / 改报名状态。
 * `api.addPlayer()` 本身保留（管理端手工添加选手仍在使用），只是**公开报名路径**归零。
 *
 * ## 契约来源
 *
 * 请求体 / 回执 / 状态枚举全部从 `frontend/src/generated/openapi.d.ts` 派生
 * （见 `api.ts` 的 `RegistrationSubmitRequest` / `RegistrationPublicResult`），
 * 页面不手写第二套 Registration DTO，也不发明 `registration_enabled` 之外的开闭规则。
 *
 * ## 隐私边界
 *
 * - `联系方式` 是**可选**字段，仅提交给赛事组织者做赛务联系；
 * - 成功后**只**展示回执里的 `registration_id` / `status` / `name` / `created_at`，
 *   不回显联系方式，也不通过任何其他接口把它重新查出来；
 * - 本页不渲染任何公开展示位（live / rankings / schedule / bigscreen / bracket / champion）。
 *
 * ## tid 来源
 *
 * - Public 路由：`/public/t/:tid/register` 由 `PublicRoutes` 的 adapter 解析后作为 **prop** 传入，
 *   URL 是唯一权威来源，非法 tid 在 adapter 层就被拦下（本页不会回退到 localStorage）；
 * - 旧管理端路由：`/register?tid=` 仍按 V0.2 兼容链（`?tid=` → `localStorage`）解析，
 *   这是既有的桌面入口，不属于 Public URL 语义。
 */

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, RegistrationPublicResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import RegistrationQr from '../components/RegistrationQr'
import './RegisterPage.css'

/** 积分默认值与后端 `RegistrationCreate.rating_points` 默认值一致（1000），不做任何换算。 */
const DEFAULT_RATING_POINTS = 1000

/**
 * 报名回执状态文案。
 *
 * key 直接取自 generated contract 的 `RegistrationStatus`（`PENDING` / `CONFIRMED`），
 * 是穷尽映射而不是“前端自造状态机”；公开入口只会拿到 `PENDING`。
 */
const REGISTRATION_STATUS_LABELS: Record<RegistrationPublicResult['status'], string> = {
  PENDING: '等待赛事组织者确认',
  CONFIRMED: '赛事组织者已确认',
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; tournament: Tournament }
  | { status: 'notfound'; message: string }
  | { status: 'error'; message: string }

export default function RegisterPage({ tid: tidProp }: { tid?: number } = {}) {
  const [params] = useSearchParams()
  const urlTid = params.get('tid')
  // tid 优先级：显式 prop（Public 路由的 path param）> ?tid= > localStorage（仅 V0.2 桌面入口兼容）
  const tid = tidProp ?? (urlTid ? Number(urlTid) : getActiveTournamentId())

  const [load, setLoad] = useState<LoadState>({ status: 'loading' })

  const [name, setName] = useState('')
  const [affiliation, setAffiliation] = useState('')
  const [contact, setContact] = useState('')
  const [ratingPoints, setRatingPoints] = useState(DEFAULT_RATING_POINTS)

  const [busy, setBusy] = useState(false)
  /** 同步锁：同一事件循环内的连续点击只放行一次（与 MobileScorePage 同一模式）。 */
  const busyRef = useRef(false)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [receipt, setReceipt] = useState<RegistrationPublicResult | null>(null)

  useEffect(() => {
    if (tid === null) {
      setLoad({ status: 'notfound', message: '这个地址里没有有效的赛事编号。' })
      return
    }
    let active = true
    setLoad({ status: 'loading' })
    // 切换赛事时重置提交态，避免上一场的回执/错误串到本场
    setReceipt(null)
    setErrorText(null)
    setBusy(false)
    busyRef.current = false

    api
      .getTournament(tid)
      .then((tournament) => {
        if (active) setLoad({ status: 'ready', tournament })
      })
      .catch((err: unknown) => {
        if (!active) return
        if (err instanceof ApiError && err.status === 404) {
          setLoad({ status: 'notfound', message: '该赛事不存在，可能已被删除。' })
        } else {
          setLoad({ status: 'error', message: err instanceof ApiError ? err.message : '无法连接服务器' })
        }
      })
    return () => {
      active = false
    }
  }, [tid])

  const submit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      if (tid === null) return
      // 防重复提交：先抢同步锁，再进入异步；`busy` 只负责按钮视觉态。
      if (busyRef.current) return
      busyRef.current = true
      setBusy(true)
      setErrorText(null)
      try {
        const result = await api.submitRegistration(tid, {
          name: name.trim(),
          affiliation: affiliation.trim() ? affiliation.trim() : null,
          contact: contact.trim() ? contact.trim() : null,
          rating_points: Number.isFinite(ratingPoints) ? ratingPoints : DEFAULT_RATING_POINTS,
        })
        setReceipt(result)
        setName('')
        setAffiliation('')
        setContact('')
        setRatingPoints(DEFAULT_RATING_POINTS)
      } catch (err) {
        // 失败时保留用户已填内容（不清空表单），只展示服务端可读 message。
        setErrorText(err instanceof ApiError ? err.message : '报名提交失败，请检查网络后重试')
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [affiliation, contact, name, ratingPoints, tid],
  )

  // ------------------------------------------------------------ 加载 / 错误态

  if (load.status === 'loading') {
    return (
      <div className="page reg-page">
        <div className="card reg-card" role="status">
          <p className="muted">正在加载赛事信息…</p>
        </div>
      </div>
    )
  }

  if (load.status !== 'ready') {
    const notfound = load.status === 'notfound'
    return (
      <div className="page reg-page">
        <div className="card reg-card">
          <div className="pub-message reg-message" role="alert">
            <h1>{notfound ? '赛事不可用' : '加载失败'}</h1>
            <p>{load.message}</p>
            {notfound && (
              <p className="pub-message-hint">
                请确认链接里的赛事编号是否正确，例如 <code>/public/t/12/register</code>。
              </p>
            )}
          </div>
        </div>
      </div>
    )
  }

  const { tournament } = load
  const registrationEnabled = tournament.registration_enabled

  // ------------------------------------------------------------ 提交成功回执

  if (receipt) {
    return (
      <div className="page reg-page">
        <div className="card reg-card">
          <div className="reg-heading">
            <h2>{tournament.name} · 在线报名</h2>
            {tid !== null && (
              <Link className="reg-back-link" to={`/public/t/${tid}/live`}>
                ← 返回实况
              </Link>
            )}
          </div>

          {/* 回执语义：只是“报名已提交并待确认”，**不是**“已参赛”。 */}
          <section className="reg-receipt" role="status">
            <h3>报名已提交</h3>
            <dl className="reg-receipt-facts">
              <div>
                <dt>姓名</dt>
                <dd>{receipt.name}</dd>
              </div>
              <div>
                <dt>报名编号</dt>
                <dd>#{receipt.registration_id}</dd>
              </div>
              <div>
                <dt>当前状态</dt>
                <dd className="reg-receipt-status">{REGISTRATION_STATUS_LABELS[receipt.status]}</dd>
              </div>
              <div>
                <dt>提交时间</dt>
                <dd>{receipt.created_at}</dd>
              </div>
            </dl>
            <p className="reg-receipt-note">
              报名需要赛事组织者确认，<b>确认后才会正式进入参赛名单</b>。请留意组织者的后续通知。
            </p>
          </section>
        </div>
      </div>
    )
  }

  // ------------------------------------------------------------ 报名关闭态

  if (!registrationEnabled) {
    return (
      <div className="page reg-page">
        <div className="card reg-card">
          <div className="reg-heading">
            <h2>{tournament.name} · 在线报名</h2>
            {tid !== null && (
              <Link className="reg-back-link" to={`/public/t/${tid}/live`}>
                ← 返回实况
              </Link>
            )}
          </div>

          {/* 情况 B：报名关闭 = 只读空态。不保留可编辑表单，也不只是 disable 按钮。 */}
          <section className="reg-closed" role="status">
            <h3>当前赛事暂未开放报名</h3>
            <p>请等待赛事组织者开放报名，或联系赛事组织者了解参赛方式。</p>
          </section>
        </div>
      </div>
    )
  }

  // ------------------------------------------------------------ 情况 A：报名开启

  return (
    <div className="page reg-page">
      <div className="card reg-card">
        <div className="reg-heading">
          <h2>{tournament.name} · 在线报名</h2>
          {tid !== null && (
            <Link className="reg-back-link" to={`/public/t/${tid}/live`}>
              ← 返回实况
            </Link>
          )}
        </div>

        <p className="muted reg-intro">
          填写报名信息后提交，赛事组织者确认后即可正式参赛。
        </p>

        <form className="reg-form" onSubmit={submit}>
          <div className="reg-field">
            <label htmlFor="reg-name">姓名（必填）</label>
            <input
              id="reg-name"
              maxLength={50}
              onChange={(e) => setName(e.target.value)}
              placeholder="请输入姓名"
              required
              type="text"
              value={name}
            />
          </div>

          <div className="reg-field">
            <label htmlFor="reg-affiliation">所属单位 / 学校 / 学院 / 俱乐部（选填）</label>
            <input
              id="reg-affiliation"
              maxLength={100}
              onChange={(e) => setAffiliation(e.target.value)}
              placeholder="如：计算机学院"
              type="text"
              value={affiliation}
            />
          </div>

          <div className="reg-field">
            <label htmlFor="reg-contact">联系方式（可选）</label>
            <input
              autoComplete="off"
              id="reg-contact"
              maxLength={200}
              onChange={(e) => setContact(e.target.value)}
              placeholder="如：手机号 / 微信号"
              type="text"
              value={contact}
            />
            <p className="reg-privacy">
              联系方式仅供赛事组织者用于赛务联系，不会在公开赛事页面展示。
            </p>
          </div>

          <div className="reg-field">
            <label htmlFor="reg-rating">运动员积分</label>
            <input
              id="reg-rating"
              max={99999}
              min={0}
              onChange={(e) => setRatingPoints(e.target.value === '' ? DEFAULT_RATING_POINTS : Number(e.target.value))}
              placeholder="如：1200"
              type="number"
              value={ratingPoints}
            />
          </div>

          <div className="reg-actions">
            <button className="reg-submit" disabled={busy} type="submit">
              {busy ? '提交中…' : '提交报名'}
            </button>
          </div>
        </form>

        {errorText && (
          <p className="reg-error" role="alert">
            {errorText}
          </p>
        )}

        {/* 组织者展示用：二维码 + 可复制的报名地址（地址由当前访问 origin 派生） */}
        {tid !== null && <RegistrationQr tournamentId={tid} />}
      </div>
    </div>
  )
}
