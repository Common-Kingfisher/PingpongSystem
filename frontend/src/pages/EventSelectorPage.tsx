import { Link } from 'react-router-dom'
import './EventSelectorPage.css'

export interface EventSelectorItemViewModel {
  id: number
  name: string
  dateLabel: string
  stageLabel: string
  formatLabel: string
  progressLabel: string
  roleLabel: string
}

export interface EventSelectorPageProps {
  events?: EventSelectorItemViewModel[] | null
  currentUserLabel?: string | null
  canCreate?: boolean
  onCreate?: () => void
  onLogout?: () => void
}

export default function EventSelectorPage({
  events = null,
  currentUserLabel,
  canCreate = false,
  onCreate,
  onLogout,
}: EventSelectorPageProps) {
  const ready = events !== null

  return (
    <main className="event-selector-page">
      <header className="event-selector-topbar">
        <Link className="event-selector-brand" to="/events"><span>TT</span>PingpongSystem</Link>
        <div><span>{currentUserLabel || '用户信息待接入'}</span><button disabled={!onLogout} onClick={onLogout}>退出登录</button></div>
      </header>

      <section className="event-selector-main">
        <header className="event-selector-heading">
          <div><span>MY TOURNAMENTS</span><h1>选择要管理的赛事</h1><p>进入赛事后，系统会保留当前工作页面，方便在多场赛事间切换。</p></div>
          <button disabled={!canCreate || !onCreate} onClick={onCreate}>创建赛事</button>
        </header>

        {!ready ? (
          <section className="event-selector-contract">
            <strong>等待赛事权限契约</strong>
            <p>页面不会从本地缓存推断权限。A 轨提供当前账号的可管理赛事列表后，这里将直接消费权威结果。</p>
          </section>
        ) : events.length === 0 ? (
          <section className="event-selector-empty">
            <span>0 EVENTS</span>
            <h2>目前没有可管理的赛事。</h2>
            <p>你可以创建一场新赛事。创建成功后，后端会将当前账号登记为赛事 Owner。</p>
            <button disabled={!canCreate || !onCreate} onClick={onCreate}>创建赛事</button>
          </section>
        ) : (
          <section className="event-selector-grid" aria-label="可管理赛事">
            {events.map((event) => (
              <article className="event-selector-card" key={event.id}>
                <header><span>{event.stageLabel}</span><b>{event.roleLabel}</b></header>
                <h2>{event.name}</h2>
                <dl>
                  <div><dt>比赛日期</dt><dd>{event.dateLabel}</dd></div>
                  <div><dt>赛事类型 / 赛制</dt><dd>{event.formatLabel}</dd></div>
                  <div><dt>比赛进度</dt><dd>{event.progressLabel}</dd></div>
                </dl>
                <Link to={`/?tid=${event.id}`}>进入赛事管理 <span aria-hidden="true">→</span></Link>
              </article>
            ))}
          </section>
        )}
      </section>
    </main>
  )
}
