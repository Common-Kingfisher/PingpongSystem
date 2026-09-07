import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, KnockoutMatch, Match, OrderBookSnapshot, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const chineseNumber = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']

function competitionRule(tournament: Tournament) {
  const gamesToWin = tournament.games_to_win ?? 2
  const pointsToWin = tournament.points_to_win ?? 11
  const totalGames = gamesToWin * 2 - 1
  const totalLabel = chineseNumber[totalGames] ?? String(totalGames)
  const winLabel = chineseNumber[gamesToWin] ?? String(gamesToWin)
  return `${totalLabel}局${winLabel}胜 · 每局 ${pointsToWin} 分`
}

function statusLabel(status: Match['status']) {
  return ({ WAITING: '待进行', PLAYING: '进行中', FINISHED: '已结束' } as const)[status]
}

function placementModeLabel(mode: Tournament['placement_mode']) {
  if (mode === 'COMPLETE') return '完整名次赛'
  if (mode === 'TIERED') return '分档排位（后续版本 · 当前未启用）'
  return '不设排位赛'
}

function knockoutResult(match: KnockoutMatch) {
  if (match.result_type === 'WALKOVER') return 'W/O'
  if (match.result_type === 'FORFEIT') return '弃权'
  if (match.result_type === 'NO_SHOW') return '未到场'
  if (match.result_type === 'DISQUALIFIED') return '取消资格'
  return `${match.player_a_score ?? '–'} : ${match.player_b_score ?? '–'}`
}

export default function OrderBookPage() {
  const [params] = useSearchParams()
  const raw = params.get('tid')
  const tid = raw ? Number(raw) : getActiveTournamentId()
  const [data, setData] = useState<OrderBookSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    setData(await api.getOrderBookSnapshot(tid))
  }, [tid])
  useEffect(() => { load().catch(() => setError('秩序册数据加载失败，请确认后端已启动并刷新页面。')) }, [load])

  if (error) return <div className="card"><h2>赛事秩序册</h2><p className="status-error">{error}</p></div>
  if (!data) return <div className="card"><h2>赛事秩序册</h2><p className="muted">正在整理赛事资料…</p></div>
  const tableNames = Object.fromEntries(data.dashboard.tables.map((table) => [table.id, table.name]))
  const sideName = (match: Match, side: 'a' | 'b') => side === 'a'
    ? match.entry_a_name ?? '待定'
    : match.entry_b_name ?? '待定'
  const finishedCount = data.matches.filter((match) => match.status === 'FINISHED').length
  const generatedAt = new Date(data.snapshot_at).toLocaleString('zh-CN')
  return <article className="order-book">
    <div className="order-toolbar"><Link to={`/?tid=${tid}`}>返回赛事</Link><button onClick={() => window.print()}>打印 / 保存 PDF</button></div>
    <header className="order-cover">
      <span>TOURNAMENT ORDER BOOK · 赛事运行快照</span><h1>{data.tournament.name}</h1>
      <p>{data.tournament.date} · {data.tournament.event_type === 'DOUBLES' ? '双打' : '单打'} · {competitionRule(data.tournament)}</p>
      <div className="order-cover-stats" aria-label="赛事进度">
        <b>{data.entries.length}<small>参赛位</small></b>
        <b>{data.matches.length}<small>全部场次</small></b>
        <b>{finishedCount}<small>已结束</small></b>
      </div>
    </header>
    <section><h2>01 赛事规程</h2><div className="order-facts">
      <p><b>{data.tournament.table_count}</b> 张球台</p><p><b>{data.tournament.group_count}</b> 个小组</p><p><b>{data.entries.length}</b> 个参赛位</p>
      <p><b>{data.tournament.bronze_mode === 'BRONZE_MATCH' ? '季军赛' : '并列季军'}</b> 季军方式</p>
    </div><dl className="order-rules"><div><dt>比赛规则</dt><dd>{competitionRule(data.tournament)}</dd></div><div><dt>名次产生</dt><dd>{placementModeLabel(data.tournament.placement_mode)}</dd></div><div><dt>小组出线</dt><dd>各组以分组设置为准</dd></div></dl></section>
    <section><h2>02 参赛名单</h2><table><thead><tr><th>编号</th><th>参赛单位</th><th>成员</th><th>积分</th></tr></thead><tbody>
      {data.entries.map((entry, index) => <tr key={entry.id}><td>{String(index + 1).padStart(2, '0')}</td><td>{entry.display_name}</td><td>{entry.members.map((m) => m.name).join(' / ')}</td><td>{entry.rating_points}</td></tr>)}
    </tbody></table></section>
    <section><h2>03 小组与排名</h2><div className="order-groups">{data.groups.groups.map((group) => {
      const ranking = data.rankings.rankings.find((item) => item.group_id === group.id)
      return <div key={group.id}><h3>{group.name} · 前 {group.qualify_count ?? data.tournament.qualify_per_group} 名出线</h3><ol>{(ranking?.entries ?? group.entries ?? []).map((entry) => <li key={'id' in entry ? entry.id : entry.player_id}>{'display_name' in entry ? entry.display_name : entry.name}</li>)}</ol></div>
    })}</div></section>
    <section className="order-schedule"><h2>04 完整赛程与球台</h2>{data.matches.length ? <table><thead><tr><th>场次</th><th>阶段</th><th>对阵</th><th>球台</th><th>状态</th></tr></thead><tbody>{data.matches.map((match) => <tr key={match.id}><td>M{match.id}</td><td>{match.stage === 'GROUP' ? '小组赛' : match.bracket === 'PLACEMENT' ? '名次排位' : `淘汰赛 R${match.round}`}</td><td>{sideName(match, 'a')} VS {sideName(match, 'b')}</td><td>{match.table_id ? tableNames[match.table_id] ?? `球台${match.table_id}` : '待安排'}</td><td><span className={`order-status order-status-${match.status.toLowerCase()}`}>{statusLabel(match.status)}</span></td></tr>)}</tbody></table> : <p>生成比赛后显示完整赛程与球台安排。</p>}</section>
    <section><h2>05 淘汰签表</h2>{data.tree.rounds.length ? <div className="order-bracket">{data.tree.rounds.map((round) => <div key={round.round}><h3>{round.label}</h3>{round.matches.map((match) => <p key={match.id}><span>M{match.id}</span>{match.player_a?.name ?? '待定'} <b>{knockoutResult(match)}</b> {match.player_b?.name ?? '待定'}</p>)}</div>)}</div> : <p>小组赛完成并生成淘汰赛后显示签表。</p>}</section>
    <section><h2>06 最终名次</h2>{(data.tree.placements ?? []).length ? <ol className="order-placements">{(data.tree.placements ?? []).map((item, index) => <li key={index}>{String(item.label ?? '')}　{String((item.entry as { name?: string } | undefined)?.name ?? '待定')}</li>)}</ol> : <p>比赛尚未结束，名次将在录分后自动生成。</p>}</section>
    <footer>生成时间：{generatedAt} · 数据状态：{finishedCount}/{data.matches.length} 场已结束 · 演示版秩序册，后续可替换为组委会官方模板</footer>
  </article>
}
