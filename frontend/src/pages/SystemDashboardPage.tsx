import './SystemPages.css'

export interface SystemDashboardViewModel {
  systemStatusLabel: string
  activeUsers: number
  inactiveUsers: number
  tournaments: number
  alerts: string[]
}

export default function SystemDashboardPage({ data }: { data?: SystemDashboardViewModel | null }) {
  return (
    <div className="system-page">
      <header className="system-page-heading"><div><span>SYSTEM OVERVIEW</span><h1>系统总览</h1></div></header>
      {!data ? (
        <div className="system-contract-note">等待 A 轨提供系统状态、用户概况与赛事概况接口。这里不根据前端缓存推导系统健康状态。</div>
      ) : (
        <>
          <section className="system-metric-grid">
            <article className="system-metric"><span>系统状态</span><strong>{data.systemStatusLabel}</strong></article>
            <article className="system-metric"><span>用户概况</span><strong>{data.activeUsers} / {data.inactiveUsers}</strong></article>
            <article className="system-metric"><span>赛事数量</span><strong>{data.tournaments}</strong></article>
          </section>
          <section className="system-panel-grid">
            <article className="system-panel"><header><strong>用户管理快捷入口</strong><small>USERS</small></header><div className="system-panel-empty">用户管理操作由后端权限接口接入后启用。</div></article>
            <article className="system-panel"><header><strong>系统异常 / 运维提醒</strong><small>ALERTS</small></header><div className="system-panel-empty">{data.alerts.length ? data.alerts.join('；') : '当前没有运维提醒。'}</div></article>
          </section>
        </>
      )}
    </div>
  )
}
