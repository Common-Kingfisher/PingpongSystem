import { Link } from 'react-router-dom'
import './AdminDashboardPage.css'

export interface AdminDashboardViewModel {
  tournamentName: string
  stageLabel: string
  progress: {
    finished: number
    total: number
    playing: number
    waiting: number
  }
  participants: {
    players: number
    entries: number
    groups: number
  }
  nextAction: {
    label: string
    detail: string
    to: string
  } | null
  liveMatches: Array<{
    id: number
    tableLabel: string
    sideA: string
    sideB: string
  }>
  publicLinks: Array<{
    label: string
    to: string
  }>
}

export interface AdminDashboardPageProps {
  data?: AdminDashboardViewModel | null
}

export default function AdminDashboardPage({ data }: AdminDashboardPageProps) {
  if (!data) {
    return (
      <section className="admin-dashboard admin-dashboard--empty">
        <span className="admin-dashboard-kicker">赛事总览</span>
        <h1>等待赛事概览数据</h1>
        <p>
          Day 1 不在前端推导赛事状态。待后端提供 completion state、next action 与当前比赛摘要后，
          这里直接消费权威结果。
        </p>
      </section>
    )
  }

  const percent = data.progress.total === 0
    ? 0
    : Math.round((data.progress.finished / data.progress.total) * 100)

  return (
    <div className="admin-dashboard">
      <header className="admin-dashboard-heading">
        <div>
          <span className="admin-dashboard-kicker">赛事总览</span>
          <h1>{data.tournamentName}</h1>
        </div>
        <span className="admin-stage-chip">{data.stageLabel}</span>
      </header>

      <section className="admin-progress-panel" aria-label="比赛进度">
        <div className="admin-progress-copy">
          <span>比赛进度</span>
          <strong>{data.progress.finished}<small> / {data.progress.total}</small></strong>
          <p>进行中 {data.progress.playing} 场 · 待比赛 {data.progress.waiting} 场</p>
        </div>
        <div className="admin-progress-track" aria-label={`已完成 ${percent}%`}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <b>{percent}%</b>
      </section>

      <section className="admin-overview-grid">
        <article className="admin-overview-card">
          <header><span>参赛概况</span><small>ROSTER</small></header>
          <dl>
            <div><dt>运动员</dt><dd>{data.participants.players}</dd></div>
            <div><dt>Entry</dt><dd>{data.participants.entries}</dd></div>
            <div><dt>小组</dt><dd>{data.participants.groups}</dd></div>
          </dl>
        </article>

        <article className="admin-overview-card admin-next-action">
          <header><span>下一步</span><small>NEXT ACTION</small></header>
          {data.nextAction ? (
            <>
              <h2>{data.nextAction.label}</h2>
              <p>{data.nextAction.detail}</p>
              <Link to={data.nextAction.to}>前往处理</Link>
            </>
          ) : (
            <p className="admin-dashboard-muted">后端尚未返回推荐操作。</p>
          )}
        </article>
      </section>

      <section className="admin-overview-card admin-live-matches">
        <header><span>正在进行</span><small>LIVE MATCHES</small></header>
        {data.liveMatches.length === 0 ? (
          <p className="admin-dashboard-muted">当前没有正在进行的比赛。</p>
        ) : (
          <div className="admin-live-match-list">
            {data.liveMatches.map((match) => (
              <article key={match.id}>
                <span>{match.tableLabel}</span>
                <strong>{match.sideA}</strong>
                <i>VS</i>
                <strong>{match.sideB}</strong>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="admin-public-shortcuts">
        <span>Public 快捷入口</span>
        <div>
          {data.publicLinks.map((link) => <Link key={link.to} to={link.to}>{link.label}</Link>)}
          {data.publicLinks.length === 0 && <small>等待 D 轨 Public 路由接入。</small>}
        </div>
      </section>
    </div>
  )
}
