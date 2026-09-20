import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, TeamKnockout, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '无法加载团体淘汰签，请稍后重试'

export default function TeamKnockoutPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [tree, setTree] = useState<TeamKnockout | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true); setError(null)
    try { const [event, knockout] = await Promise.all([api.getTournament(tid), api.getTeamKnockout(tid)]); setTournament(event); setTree(knockout) }
    catch (requestError) { setTournament(null); setTree(null); setError(messageOf(requestError)) }
    finally { setLoading(false) }
  }, [tid])
  useEffect(() => { void load() }, [load])
  const generate = async () => { if (tid === null) return; setBusy(true); setError(null); try { setTree(await api.generateTeamKnockout(tid)) } catch (requestError) { setError(messageOf(requestError)) } finally { setBusy(false) } }
  if (tid === null || !Number.isInteger(tid)) return <div className="card"><h2>团体淘汰赛</h2><p>请提供有效的 <code>tid</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p aria-live="polite">正在加载团体淘汰签…</p></div>
  if (!tournament || !tree) return <div className="card"><h2>团体淘汰赛</h2><p className="status-error" role="alert">{error ?? '无法加载团体淘汰签'}</p><button className="btn" onClick={() => void load()}>重试</button></div>
  if (tournament.event_type !== 'TEAM') return <div className="card"><h2>团体淘汰赛</h2><p className="status-error">当前赛事不是团体赛。</p><Link className="btn" to={`/?tid=${tid}`}>返回赛事首页</Link></div>
  return <div className="page"><header className="team-ties-header"><div><span className="eyebrow">TEAM KNOCKOUT</span><h1>{tournament.name} · 团体淘汰赛</h1><p className="muted">签表与首轮对阵均由后端生成。本工作线止于首轮；胜者向下一轮传播尚未实现。</p></div><Link className="btn" to={`/team-qualification?tid=${tid}`}>返回晋级确认</Link></header>{error && <p className="status-error" role="alert">{error}</p>}{!tree.generated ? <section className="card"><h2>尚未生成淘汰首轮</h2><p>请先确认晋级名单。后端会验证所有前置条件和配对合法性。</p><button className="btn primary" disabled={busy} onClick={() => void generate()}>生成团体淘汰首轮</button></section> : <>{tree.rounds.map((round) => <section className="card" key={round.round}><h2>{round.round_name}</h2><p className="muted">应有 {round.match_count} 场；未产生参赛者的后续轮次不会创建对抗。</p>{round.matches.map((match) => <div className="button-row" key={match.tie_id}><span>{match.team_a?.team_name ?? '待上轮胜者'} VS {match.team_b?.team_name ?? '待上轮胜者'}</span><Link className="btn small" to={`/team-tie?tid=${tid}&tie=${match.tie_id}`}>查看对抗</Link></div>)}</section>)}<p className="status-info">首轮已由后端生成。本工作线到此结束，不处理胜者传播。</p></>}<div className="button-row"><button className="btn" disabled={busy} onClick={() => void load()}>刷新</button></div></div>
}
