import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, Entry, GroupingResult, Player, Tournament, TournamentFormat } from '../api'
import { getActiveTournamentId } from '../activeTournament'

const formatNames: Record<TournamentFormat, string> = {
  GROUP_KNOCKOUT: '小组赛 + 淘汰赛',
  ROUND_ROBIN: '全体循环赛',
  SINGLE_ELIMINATION: '单淘汰',
}

export default function DrawPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid && /^\d+$/.test(rawTid) ? Number(rawTid) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [groups, setGroups] = useState<GroupingResult>({ groups: [] })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [withdrawTarget, setWithdrawTarget] = useState<Entry | null>(null)
  const [withdrawOperator, setWithdrawOperator] = useState(() => localStorage.getItem('pingpong_referee_name') ?? '')
  const [withdrawReason, setWithdrawReason] = useState('')

  const load = useCallback(async () => {
    if (tid === null) return
    const [nextTournament, nextPlayers] = await Promise.all([api.getTournament(tid), api.listPlayers(tid)])
    setTournament(nextTournament); setPlayers(nextPlayers)
    if (nextTournament.format_code === 'GROUP_KNOCKOUT') setGroups(await api.getGroups(tid))
    else setGroups({ groups: [] })
  }, [tid])

  useEffect(() => { load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : '抽签数据加载失败')) }, [load])

  const seeds = useMemo(() => players.filter((player) => player.seed_no !== null).sort((a, b) => (a.seed_no ?? 999) - (b.seed_no ?? 999)), [players])
  const candidates = useMemo(() => players.filter((player) => player.seed_no === null), [players])

  if (tid === null) return <div className="card"><h2>抽签与编排</h2><p className="muted">请先在<Link to="/">赛事首页</Link>选择赛事。</p></div>

  const run = async (work: () => Promise<void>, fallback: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { await work(); await load() }
    catch (err) { setError(err instanceof ApiError ? err.message : fallback) }
    finally { setBusy(false) }
  }

  const persistSeeds = (ids: number[]) => run(async () => { await api.setSeeds(tid, ids); setNotice('种子顺序已保存。') }, '保存种子失败')
  const addSeed = (player: Player) => void persistSeeds([...seeds.map((seed) => seed.id), player.id])
  const removeSeed = (player: Player) => void persistSeeds(seeds.filter((seed) => seed.id !== player.id).map((seed) => seed.id))
  const moveSeed = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= seeds.length) return
    const ids = seeds.map((seed) => seed.id); [ids[index], ids[target]] = [ids[target], ids[index]]; void persistSeeds(ids)
  }
  const autoGroup = () => void run(async () => { setGroups(await api.autoGroup(tid)); setNotice('分组抽签已由后端完成。') }, '抽签分组失败')
  const clearGroups = () => void run(async () => { await api.ungroup(tid); setNotice('现有分组已清空。') }, '清空分组失败')
  const generateGroupMatches = () => void run(async () => { const result = await api.generateGroupMatches(tid); setNotice(`已生成 ${result.matches_generated} 场小组比赛。`) }, '生成小组比赛失败')
  const updateQualification = (groupId: number, count: number) => void run(async () => { await api.setGroupQualification(tid, groupId, count); setNotice('该组出线人数已保存。') }, '修改出线人数失败')
  const confirmWithdrawal = () => {
    if (!withdrawTarget) return
    void run(async () => {
      await api.withdrawEntry(tid, withdrawTarget.id, { operator_name: withdrawOperator.trim(), reason: withdrawReason.trim() })
      localStorage.setItem('pingpong_referee_name', withdrawOperator.trim()); setWithdrawTarget(null); setWithdrawReason(''); setNotice('退赛已记录，相关未完赛场次将按后端规则处理。')
    }, '退赛处理失败')
  }

  const format = tournament?.format_code ?? null
  const locked = tournament?.stage !== 'REGISTRATION'
  const renderSeedPanel = () => <section className="card draw-section">
    <div className="section-heading"><div><span className="eyebrow">SEED ORDER</span><h3>种子设置</h3></div><span>{seeds.length} 名</span></div>
    <p className="muted">只提供人工顺序编辑。运动员积分仅作参考；合法数量与保存规则以服务端返回为准。</p>
    <div className="seed-workbench">
      <div><h4>当前种子顺序</h4>{seeds.length === 0 ? <p className="empty-invite">尚未设置种子。</p> : <ol className="seed-order">{seeds.map((player, index) => <li key={player.id}><span className="seed-index">{index + 1}</span><strong>{player.name}</strong><small>{player.college || '单位未填写'} · 积分 {player.rating_points}</small><div><button className="btn small" disabled={busy || locked || index === 0} onClick={() => moveSeed(index, -1)}>↑</button><button className="btn small" disabled={busy || locked || index === seeds.length - 1} onClick={() => moveSeed(index, 1)}>↓</button><button className="btn small danger" disabled={busy || locked} onClick={() => removeSeed(player)}>移除</button></div></li>)}</ol>}</div>
      <div><h4>候选运动员</h4><div className="seed-candidates">{candidates.map((player) => <button type="button" key={player.id} disabled={busy || locked} onClick={() => addSeed(player)}><strong>{player.name}</strong><span>{player.college || '单位未填写'} · {player.rating_points}</span><b>＋</b></button>)}</div></div>
    </div>
  </section>

  return <div className="draw-page">
    <div className="page-title-row"><div><span className="eyebrow">DRAW & SCHEDULING</span><h2>抽签与编排</h2><p className="muted">先确认真实赛制，再使用对应能力；页面不会从赛事阶段猜测赛制。</p></div><Link className="btn" to={`/settings?tid=${tid}`}>调整赛制与规则</Link></div>
    {error && <p className="status-error" role="alert">{error}</p>}{notice && <p className="status-ok" role="status">{notice}</p>}
    <section className="draw-summary">
      <div><span>正式名单</span><strong>{players.length}</strong><small>{tournament?.roster_confirmed ? '已确认' : '尚未确认'}</small></div>
      <div><span>当前赛制</span><strong>{format ? formatNames[format] : '尚未设置'}</strong><small>{tournament?.event_type ?? '—'}</small></div>
      <div><span>比赛规则</span><strong>{tournament ? `${tournament.games_to_win * 2 - 1} 局 ${tournament.games_to_win} 胜` : '—'}</strong><small>{tournament ? `每局 ${tournament.points_to_win} 分` : '—'}</small></div>
      <div><span>赛事阶段</span><strong>{tournament?.stage ?? '—'}</strong><small>{locked ? '结构已锁定' : '可编排'}</small></div>
    </section>

    {!format && <section className="card contract-waiting"><span className="eyebrow">FORMAT REQUIRED</span><h3>请先保存赛事赛制</h3><p>历史赛事允许赛制为空。本页面不会默认成“小组赛 + 淘汰赛”。</p><Link className="btn primary" to={`/settings?tid=${tid}`}>前往赛事设置</Link></section>}

    {format === 'ROUND_ROBIN' && <>
      <section className="card draw-section"><span className="eyebrow">ROUND ROBIN</span><h3>单循环编排</h3><p>全部参赛位互相交手，不需要种子、分组出线或淘汰签。</p><div className="settings-priority">名单确认 <b>›</b> 生成循环对阵 <b>›</b> 排台比赛 <b>›</b> 最终排名</div></section>
      <section className="card contract-waiting"><h3>等待单循环生成接口</h3><p>当前后端没有按 <code>ROUND_ROBIN</code> 赛制生成对阵的正式接口，因此此处只展示规则与准备状态，不会调用旧的小组赛生成接口。</p></section>
    </>}

    {format === 'SINGLE_ELIMINATION' && <>{renderSeedPanel()}<section className="card draw-section"><span className="eyebrow">KNOCKOUT DRAW</span><h3>单败淘汰签</h3><p>种子顺序已可使用真实接口保存；首轮淘汰签仍等待当前赛制专用的生成接口。</p><div className="contract-status"><span className="ready">可用 · 种子保存</span><span>等待 · 淘汰签生成</span></div></section></>}

    {format === 'GROUP_KNOCKOUT' && <>
      {renderSeedPanel()}
      <section className="card draw-section">
        <div className="section-heading"><div><span className="eyebrow">GROUP DRAW</span><h3>小组抽签结果</h3></div><span>{groups.groups.length} 组</span></div>
        <p className="muted">当前正式能力会把已确认参赛位抽入 {tournament?.group_count ?? '—'} 个小组，并由后端执行种子分散规则。</p>
        <div className="button-row"><button className="btn primary" disabled={busy || locked || !tournament?.roster_confirmed} onClick={autoGroup}>{groups.groups.length ? '重新抽签' : '开始小组抽签'}</button>{groups.groups.length > 0 && <button className="btn" disabled={busy || locked} onClick={clearGroups}>清空分组</button>}</div>
        {!tournament?.roster_confirmed && <p className="status-warn">请先在“参赛名单”确认正式名单。</p>}
        <div className="group-grid">{groups.groups.map((group) => <article className="group-card" key={group.id}><div className="group-card-head"><h4>{group.name}</h4><label>出线 <select value={group.qualify_count ?? tournament?.qualify_per_group ?? 1} disabled={busy || locked} onChange={(event) => updateQualification(group.id, Number(event.target.value))}>{Array.from({ length: Math.max(1, (group.entries.length || group.players.length) - 1) }, (_, index) => index + 1).map((count) => <option key={count} value={count}>{count} 名</option>)}</select></label></div><ol>{(group.entries.length ? group.entries : group.players).map((participant) => {
          const isEntry = 'display_name' in participant; const withdrawn = isEntry && participant.status === 'WITHDRAWN'
          return <li key={participant.id} className={withdrawn ? 'entry-withdrawn' : ''}><span>{'seed_no' in participant && participant.seed_no ? <b className="seed-badge">#{participant.seed_no}</b> : null}{isEntry ? participant.display_name : participant.name}{withdrawn && <i className="withdrawn-badge">已退赛</i>}</span>{locked && isEntry && !withdrawn && tournament?.stage !== 'FINISHED' && <button className="btn small danger" onClick={() => setWithdrawTarget(participant)}>退赛</button>}</li>
        })}</ol></article>)}</div>
      </section>
      <section className="card draw-section"><div className="section-heading"><div><span className="eyebrow">GROUP SCHEDULE</span><h3>生成小组循环赛</h3></div><span className={groups.groups.length ? 'readiness ready' : 'readiness'}>{groups.groups.length ? '准备完成' : '等待分组'}</span></div><p>这是现有 <code>GROUP_KNOCKOUT</code> 流程的真实生成入口，不会包装成其他赛制的统一接口。</p><button className="btn primary" disabled={busy || locked || groups.groups.length === 0 || !tournament?.roster_confirmed} onClick={generateGroupMatches}>生成小组比赛</button></section>
    </>}

    {withdrawTarget && <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="确认退赛"><div className="modal"><button className="modal-close" onClick={() => setWithdrawTarget(null)} aria-label="关闭">×</button><span className="eyebrow">WITHDRAWAL</span><h3>确认 {withdrawTarget.display_name} 退出整个赛事</h3><p className="status-warn">已结束结果保留；未完成比赛将按后端退赛规则处理。</p><label>主裁判<input value={withdrawOperator} onChange={(event) => setWithdrawOperator(event.target.value)} /></label><label>裁定理由<textarea value={withdrawReason} onChange={(event) => setWithdrawReason(event.target.value)} /></label><div className="modal-actions"><button className="btn" onClick={() => setWithdrawTarget(null)}>取消</button><button className="btn danger" disabled={busy || !withdrawOperator.trim() || withdrawReason.trim().length < 2} onClick={confirmWithdrawal}>确认退赛</button></div></div></div>}
  </div>
}
