import { Link } from 'react-router-dom'
import './AccessStatePage.css'

export default function TournamentUnavailablePage() {
  return (
    <main className="access-state-page">
      <section className="access-state-card">
        <span className="access-state-code">404 · RESOURCE_NOT_FOUND</span>
        <h1>无法访问赛事。</h1>
        <p>该赛事不存在，或当前账号没有访问权限。为保护赛事信息，系统不会说明具体原因。</p>
        <div className="access-state-actions">
          <Link to="/events">返回赛事列表</Link>
        </div>
      </section>
    </main>
  )
}
