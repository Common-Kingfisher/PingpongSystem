import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, KnockoutMatch, Match, OrderBookSnapshot, Tournament } from '../api'
import { getActiveTournamentId, parseTournamentId } from '../activeTournament'
import { eventTypeLabel, formatSummary, tournamentStageLabel } from '../format'

function competitionRule(tournament: Tournament) {
  return formatSummary(tournament)
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

/**
 * 赛程与秩序（C-D5 Phase 3）。
 *
 * ## 两个概念（Day5 第 12 / 14 节，不得混淆）
 *
 * - **实时赛程快照**：本页内容，来自运行数据库，是"某一时间点的系统实时状态"。
 * - **官方秩序册**：赛事组委会赛前发布 / 文件 / 快照 / 打印材料，**不是**运行数据库事实源，
 *   系统运行逻辑也不得反向读取它。
 *
 * 当前后端没有任何"官方秩序册文件"业务事实（`order-book-snapshot` 是实时聚合快照）。
 * 因此本页**明确显示"暂未关联官方秩序册"**，绝不把实时数据库页面冒充成官方发布版本，
 * 也不自动生成一个文件再声称它是赛事方发布版本。
 */
export default function OrderBookPage() {
  const [params] = useSearchParams()
  const tid = parseTournamentId(params.get('tid')) ?? getActiveTournamentId()
  const [data, setData] = useState<OrderBookSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)

  const load = useCallback(async () => {
    if (tid === null) return
    setData(await api.getOrderBookSnapshot(tid))
  }, [tid])

  useEffect(() => {
    if (tid === null) {
      setLoading(false)
      setData(null)
      setError(null)
      return
    }
    setLoading(true)
    load()
      .then(() => setError(null))
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : '秩序册数据加载失败')
      })
      .finally(() => setLoading(false))
  }, [tid, load, reloadKey])

  if (tid === null) {
    return (
      <div className="card">
        <h2>赛程与秩序</h2>
        <p className="muted">请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。</p>
      </div>
    )
  }

  if (loading && !data) {
    return <div className="card"><h2>赛程与秩序</h2><p className="muted">正在整理赛事资料…</p></div>
  }

  if (!data) {
    return (
      <div className="card" role="alert">
        <h2>赛程与秩序</h2>
        <p className="status-error">加载失败：{error || '无法读取赛事资料。'}</p>
        <div className="button-row">
          <button className="btn primary" onClick={() => setReloadKey((value) => value + 1)} type="button">重试</button>
          <Link className="btn" to={`/console?tid=${tid}`}>返回比赛控制台</Link>
        </div>
      </div>
    )
  }

  const tableNames = Object.fromEntries(data.dashboard.tables.map((table) => [table.id, table.name]))
  const sideName = (match: Match, side: 'a' | 'b') => side === 'a'
    ? match.entry_a_name ?? '待定'
    : match.entry_b_name ?? '待定'
  const finishedCount = data.matches.filter((match) => match.status === 'FINISHED').length
  const generatedAt = new Date(data.snapshot_at).toLocaleString('zh-CN', { hour12: false })
  const stageLabel = tournamentStageLabel(data.tournament.stage, data.tournament.format_code)

  return <article className="order-book">
    <div className="order-toolbar no-print">
      <Link to={`/console?tid=${tid}`}>返回比赛控制台</Link>
      <Link to={`/schedule?tid=${tid}`}>实时赛程</Link>
      <button onClick={() => window.print()}>打印 / 保存 PDF</button>
    </div>

    {/*
      官方秩序册状态：当前系统没有该业务事实，因此如实说明"暂未关联"。
      不显示"已生成"，也不把本页实时快照命名为官方秩序册。
    */}
    <section className="order-official-notice" role="status">
      <strong>官方秩序册：暂未关联官方秩序册</strong>
      <p>
        当前系统没有赛事组委会发布的官方秩序册文件。本页是<strong>实时赛程快照</strong>——
        由运行数据库在某一个时间点聚合而成，用于现场打印与核对，<strong>不是</strong>赛事方发布的正式秩序册。
      </p>
    </section>

    <header className="order-cover">
      <span>TOURNAMENT LIVE SNAPSHOT · 赛事实时运行快照</span><h1>{data.tournament.name}</h1>
      <p>{data.tournament.date} · {eventTypeLabel(data.tournament.event_type)} · {competitionRule(data.tournament)}</p>
      <p className="order-cover-stage">当前阶段：{stageLabel}</p>
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
      return <div key={group.id}><h3>{group.name} · 前 {group.qualify_count ?? data.tournament.qualify_per_group} 名出线</h3><ol>{(ranking?.entries ?? group.entries).map((entry) => <li key={'id' in entry ? entry.id : entry.player_id}>{'display_name' in entry ? entry.display_name : entry.name}</li>)}</ol></div>
    })}</div></section>
    <section className="order-schedule"><h2>04 完整赛程与球台</h2>{data.matches.length ? <table><thead><tr><th>场次</th><th>阶段</th><th>对阵</th><th>球台</th><th>状态</th></tr></thead><tbody>{data.matches.map((match) => <tr key={match.id}><td>M{match.id}</td><td>{match.stage === 'GROUP' ? '小组赛' : match.bracket === 'PLACEMENT' ? '名次排位' : `淘汰赛 R${match.round}`}</td><td>{sideName(match, 'a')} VS {sideName(match, 'b')}</td><td>{match.table_id ? tableNames[match.table_id] ?? `球台${match.table_id}` : '待安排'}</td><td><span className={`order-status order-status-${match.status.toLowerCase()}`}>{statusLabel(match.status)}</span></td></tr>)}</tbody></table> : <p>生成比赛后显示完整赛程与球台安排。</p>}</section>
    <section><h2>05 淘汰签表</h2>{data.tree.rounds.length ? <div className="order-bracket">{data.tree.rounds.map((round) => <div key={round.round}><h3>{round.label}</h3>{round.matches.map((match) => <p key={match.id}><span>M{match.id}</span>{match.player_a?.name ?? '待定'} <b>{knockoutResult(match)}</b> {match.player_b?.name ?? '待定'}</p>)}</div>)}</div> : <p>小组赛完成并生成淘汰赛后显示签表。</p>}</section>
    <section><h2>06 最终名次</h2>{data.tree.placements.length ? <ol className="order-placements">{data.tree.placements.map((item, index) => <li key={index}>{String(item.label ?? '')}　{String((item.entry as { name?: string } | undefined)?.name ?? '待定')}</li>)}</ol> : <p>比赛尚未结束，名次将在录分后自动生成。</p>}</section>
    <footer>
      生成时间：{generatedAt} · 赛事：{data.tournament.name} · 当前阶段：{stageLabel}
      <br />数据状态：实时系统快照（{finishedCount} / {data.matches.length} 场已结束）· 非官方秩序册
    </footer>
  </article>
}
