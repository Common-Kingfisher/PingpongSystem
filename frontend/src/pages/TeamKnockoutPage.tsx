import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, TeamKnockout, TeamQualification, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '无法加载团体淘汰签，请稍后重试'

export default function TeamKnockoutPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [knockout, setKnockout] = useState<TeamKnockout | null>(null)
  const [qualification, setQualification] = useState<TeamQualification | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true); setError(null)
    try { const [nextTournament, nextKnockout, nextQualification] = await Promise.all([api.getTournament(tid), api.getTeamKnockout(tid), api.getTeamQualification(tid)]); setTournament(nextTournament); setKnockout(nextKnockout); setQualification(nextQualification) }
    catch (requestError) { setTournament(null); setKnockout(null); setQualification(null); setError(messageOf(requestError)) }
    finally { setLoading(false) }
  }, [tid])
  useEffect(() => { void load() }, [load])

  const generate = async () => {
    if (tid === null) return
    setGenerating(true); setError(null)
    try { setKnockout(await api.generateTeamKnockout(tid)) }
    catch (requestError) { setError(messageOf(requestError)) }
    finally { setGenerating(false) }
  }

  if (tid === null || !Number.isInteger(tid)) return <div className="card"><h2>团体淘汰签</h2><p className="muted">请提供有效的 <code>tid</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p aria-live="polite">正在加载团体淘汰签…</p></div>
  if (!tournament || !knockout) return <div className="card"><h2>团体淘汰签</h2><p className="status-error" role="alert">{error ?? '无法加载团体淘汰签'}</p><button className="btn" onClick={() => void load()}>重试</button></div>
  if (tournament.event_type !== 'TEAM') return <div className="card"><h2>团体淘汰签</h2><p className="status-error">当前赛事不是团体赛。</p><Link className="btn" to={`/knockout?tid=${tid}`}>前往淘汰赛</Link></div>

  return <div className="page team-knockout-page">
    <header className="team-ties-header"><div><span className="eyebrow">TEAM KNOCKOUT</span><h1>{tournament.name} · 团体淘汰签</h1><p className="muted">签表与首轮对抗由后端根据已确认晋级名单生成；后续轮次仅显示待定槽位，不伪造尚未产生的对抗。</p></div><div className="button-row"><button className="btn" onClick={() => void load()} disabled={loading || generating}>刷新</button><Link className="btn" to={`/team-qualification?tid=${tid}`}>晋级确认</Link></div></header>
    {error && <p className="status-error" role="alert">{error}</p>}
    {!knockout.generated ? <section className="card team-ties-empty"><h2>{qualification?.confirmed.length ? '晋级名单已确认，尚未生成团体淘汰签' : '尚未确认团体晋级名单'}</h2><p>{qualification?.confirmed.length ? '后端会在生成时核验种子顺序、队伍状态与签表规模；若暂不能生成，会显示服务端返回的实际原因。' : '请先完成全部小组的晋级确认。生成只创建双方已确定的首轮对抗，后续轮次待上游胜者产生后再由后端支持。'}</p><div className="button-row"><Link className="btn" to={`/team-qualification?tid=${tid}`}>{qualification?.confirmed.length ? '查看晋级确认' : '前往晋级确认'}</Link><button className="btn primary" onClick={() => void generate()} disabled={generating}>{generating ? '正在生成…' : '生成首轮淘汰签'}</button></div></section> : <>
      <div className="team-knockout-rounds" aria-label="团体淘汰签轮次">
        {knockout.rounds.map((round) => <section className="card team-knockout-round" key={round.round}><header><h2>{round.round_name}</h2><span>{round.match_count} 场</span></header><div className="team-knockout-matches">{round.matches.length === 0 ? Array.from({ length: round.match_count }, (_, index) => <article className="team-knockout-match pending" key={index}><strong>待上游胜者</strong><span>本版本尚未创建此轮对抗</span></article>) : round.matches.map((match) => <article className="team-knockout-match" key={match.tie_id}><div><strong>{match.team_a?.team_name ?? '待定'}</strong><b>{match.team_a_score}</b></div><div><strong>{match.team_b?.team_name ?? '待定'}</strong><b>{match.team_b_score}</b></div><footer><span className={`team-tie-status ${match.status.toLowerCase()}`}>{match.status === 'WAITING' ? '待开始' : match.status === 'PLAYING' ? '进行中' : '已结束'}</span>{match.teams_decided && <Link className="btn small" to={`/team-tie?tid=${tid}&tie=${match.tie_id}`}>进入对抗</Link>}</footer></article>)}</div></section>)}
      </div>
      <p className="team-standings-footnote muted">当前仅生成首轮；淘汰签胜者晋级、撤销/重建和阶段推进尚未实现，页面不会把待定槽位显示成可操作比赛。</p>
    </>}
  </div>
}
