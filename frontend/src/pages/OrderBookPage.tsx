import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, Dashboard, Entry, GroupingResult, KnockoutTree, Match, RankingsResult, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

export default function OrderBookPage() {
  const [params] = useSearchParams()
  const raw = params.get('tid')
  const tid = raw ? Number(raw) : getActiveTournamentId()
  const [data, setData] = useState<{ tournament: Tournament; entries: Entry[]; groups: GroupingResult; rankings: RankingsResult; tree: KnockoutTree; matches: Match[]; dashboard: Dashboard } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [tournament, entries, groups, rankings, tree, matches, dashboard] = await Promise.all([
      api.getTournament(tid), api.listEntries(tid), api.getGroups(tid), api.getRankings(tid), api.getKnockout(tid), api.listMatches(tid), api.getDashboard(tid),
    ])
    setData({ tournament, entries, groups, rankings, tree, matches, dashboard })
  }, [tid])
  useEffect(() => { load().catch(() => setError('秩序册数据加载失败，请确认后端已启动并刷新页面。')) }, [load])

  if (error) return <div className="card"><h2>赛事秩序册</h2><p className="status-error">{error}</p></div>
  if (!data) return <div className="card"><h2>赛事秩序册</h2><p className="muted">正在整理赛事资料…</p></div>
  const tableNames = Object.fromEntries(data.dashboard.tables.map((table) => [table.id, table.name]))
  const sideName = (match: Match, side: 'a' | 'b') => side === 'a'
    ? match.entry_a_name ?? '待定'
    : match.entry_b_name ?? '待定'
  return <article className="order-book">
    <div className="order-toolbar"><Link to={`/?tid=${tid}`}>返回赛事</Link><button onClick={() => window.print()}>打印 / 保存 PDF</button></div>
    <header className="order-cover">
      <span>TOURNAMENT ORDER BOOK</span><h1>{data.tournament.name}</h1>
      <p>{data.tournament.date} · {data.tournament.event_type === 'DOUBLES' ? '双打' : '单打'} · 三局两胜，每局 11 分</p>
    </header>
    <section><h2>01 赛事规程</h2><div className="order-facts">
      <p><b>{data.tournament.table_count}</b> 张球台</p><p><b>{data.tournament.group_count}</b> 个小组</p><p><b>{data.entries.length}</b> 个参赛位</p>
      <p><b>{data.tournament.bronze_mode === 'BRONZE_MATCH' ? '季军赛' : '并列季军'}</b> 季军方式</p>
    </div></section>
    <section><h2>02 参赛名单</h2><table><thead><tr><th>编号</th><th>参赛单位</th><th>成员</th><th>积分</th></tr></thead><tbody>
      {data.entries.map((entry, index) => <tr key={entry.id}><td>{String(index + 1).padStart(2, '0')}</td><td>{entry.display_name}</td><td>{entry.members.map((m) => m.name).join(' / ')}</td><td>{entry.rating_points}</td></tr>)}
    </tbody></table></section>
    <section><h2>03 小组与排名</h2><div className="order-groups">{data.groups.groups.map((group) => {
      const ranking = data.rankings.rankings.find((item) => item.group_id === group.id)
      return <div key={group.id}><h3>{group.name} · 前 {group.qualify_count ?? data.tournament.qualify_per_group} 名出线</h3><ol>{(ranking?.entries ?? group.entries).map((entry) => <li key={'id' in entry ? entry.id : entry.player_id}>{'display_name' in entry ? entry.display_name : entry.name}</li>)}</ol></div>
    })}</div></section>
    <section><h2>04 赛程与球台</h2>{data.matches.length ? <table><thead><tr><th>场次</th><th>阶段</th><th>对阵</th><th>球台</th><th>状态</th></tr></thead><tbody>{data.matches.slice(0, 40).map((match) => <tr key={match.id}><td>M{match.id}</td><td>{match.stage === 'GROUP' ? '小组赛' : match.bracket === 'PLACEMENT' ? '名次排位' : '淘汰赛'}</td><td>{sideName(match, 'a')} VS {sideName(match, 'b')}</td><td>{match.table_id ? tableNames[match.table_id] ?? `球台${match.table_id}` : '待安排'}</td><td>{match.status}</td></tr>)}</tbody></table> : <p>生成比赛后显示初步赛程与球台安排。</p>}</section>
    <section><h2>05 最终名次</h2>{data.tree.placements.length ? <ol className="order-placements">{data.tree.placements.map((item, index) => <li key={index}>{String(item.label ?? '')}　{String((item.entry as { name?: string } | undefined)?.name ?? '待定')}</li>)}</ol> : <p>比赛尚未结束，名次将在录分后自动生成。</p>}</section>
    <footer>生成时间：{new Date().toLocaleString('zh-CN')} · 本文件为演示版秩序册，后续可替换为组委会官方模板</footer>
  </article>
}
