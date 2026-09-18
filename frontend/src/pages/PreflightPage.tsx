import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, PreflightResult } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const labels = {
  READY: { title: '可以继续', mark: '●', short: '通过' },
  WARN: { title: '需要留意', mark: '▲', short: '注意' },
  BLOCK: { title: '暂不建议开赛', mark: '■', short: '阻断' },
} as const

export default function PreflightPage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : getActiveTournamentId()
  const [report, setReport] = useState<PreflightResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (tid === null) return
    setLoading(true)
    setError(null)
    // 新一轮检查开始后，旧结论不再代表当前现场状态；请求失败时不得继续展示旧 READY。
    setReport(null)
    try {
      setReport(await api.getPreflight(tid))
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '赛前检查加载失败')
    } finally {
      setLoading(false)
    }
  }, [tid])

  useEffect(() => { void load() }, [load])

  if (tid === null) {
    return <div className="card"><h2>赛前检查</h2><p className="muted">请先在<Link to="/">赛事首页</Link>选择一场赛事。</p></div>
  }

  const orderedChecks = report ? [...report.checks].sort((a, b) => {
    const priority = { BLOCK: 0, WARN: 1, READY: 2 }
    return priority[a.level] - priority[b.level]
  }) : []
  const overall = report ? labels[report.overall] : labels.WARN

  return (
    <div className="page preflight-page">
      <section className={`preflight-hero ${report?.overall.toLowerCase() ?? 'loading'}`}>
        <div className="preflight-hero-copy">
          <span className="eyebrow">MATCH READINESS · 主裁工作台</span>
          <h1>赛前检查</h1>
          <p>{report ? `${report.tournament.name} · ${overall.title}` : '正在核对赛事关键状态…'}</p>
          <div className="preflight-actions">
            <button className="btn primary" onClick={load} disabled={loading}>{loading ? '检查中…' : '重新检查'}</button>
            <Link className="btn" to={`/console?tid=${tid}`}>进入比赛控制台</Link>
          </div>
        </div>
        <div className="preflight-verdict" aria-live="polite">
          <span>{report ? labels[report.overall].mark : '···'}</span>
          <strong>{report ? overall.title : '检查中'}</strong>
          {report && <small>{report.blocker_count} 阻断 · {report.warning_count} 注意 · {report.ready_count} 通过</small>}
        </div>
      </section>

      {error && <div className="preflight-system-error"><strong>无法完成检查</strong><p>{error}</p><button className="btn" onClick={load}>重试</button></div>}

      {report && (
        <>
          <section className="preflight-scoreboard" aria-label="赛事规模摘要">
            <div><span>运动员</span><strong>{report.metrics.players}</strong></div>
            <div><span>参赛位</span><strong>{report.metrics.entries}</strong></div>
            <div><span>小组</span><strong>{report.metrics.groups}</strong></div>
            <div><span>球台</span><strong>{report.metrics.tables}</strong></div>
            <div><span>总场次</span><strong>{report.metrics.matches}</strong></div>
            <div className={report.metrics.playing ? 'live' : ''}><span>进行中</span><strong>{report.metrics.playing}</strong></div>
          </section>

          <section className="preflight-track" aria-label="检查状态灯带">
            {report.checks.map((check) => <span key={check.code} className={check.level.toLowerCase()} title={`${check.title}：${labels[check.level].short}`} />)}
          </section>

          <section className="preflight-checks">
            <header>
              <div><span className="eyebrow">CONTROL POINTS</span><h2>关键检查项</h2></div>
              <p>阻断项处理完成后再进入正式比赛；注意项不会替主裁自动做决定。</p>
            </header>
            <div className="preflight-check-grid">
              {orderedChecks.map((check) => (
                <article key={check.code} className={`preflight-check ${check.level.toLowerCase()}`}>
                  <div className="preflight-check-state"><i>{labels[check.level].mark}</i><span>{labels[check.level].short}</span></div>
                  <div className="preflight-check-copy"><h3>{check.title}</h3><p>{check.detail}</p></div>
                  {check.action_path && check.action_label && <Link to={check.action_path} className="preflight-check-link">{check.action_label} →</Link>}
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
