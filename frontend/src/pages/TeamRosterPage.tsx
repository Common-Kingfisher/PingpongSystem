import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, TeamRosterSaveRequest, TeamRosterSheet } from '../api'
import { getActiveTournamentId } from '../activeTournament'

type Draft = Omit<TeamRosterSaveRequest, 'base_revision'>
type SortKey = 'official' | 'team' | 'name' | 'rating'
type Dialog = 'team' | 'player' | 'rename' | 'preview' | null

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const newKey = (prefix: string) => `${prefix}-${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`
const messageOf = (error: unknown) => error instanceof ApiError ? error.message : '名单操作失败，请稍后重试'

function draftFrom(sheet: TeamRosterSheet): Draft {
  const teamKeyOf = new Map<number, string>()
  const memberOrderOf = new Map<number, number>()
  const teams = sheet.teams.map((team) => {
    const key = `team-${team.id}`
    teamKeyOf.set(team.id, key)
    team.members.forEach((member) => memberOrderOf.set(member.player_id, member.member_order))
    return { key, id: team.id, display_name: team.display_name, rating_points: team.rating_points, sort_order: team.sort_order }
  })
  const memberTeamOf = new Map<number, number>()
  sheet.teams.forEach((team) => team.members.forEach((member) => memberTeamOf.set(member.player_id, team.id)))
  return {
    teams,
    players: sheet.players.map((player) => ({
      key: `player-${player.id}`, id: player.id, name: player.name, college: player.college,
      rating_points: player.rating_points, team_key: teamKeyOf.get(memberTeamOf.get(player.id) ?? -1) ?? null,
      member_order: memberOrderOf.get(player.id) ?? null,
    })),
    deleted_team_ids: [], deleted_player_ids: [],
  }
}

function normalizeOrders(draft: Draft): Draft {
  const next = clone(draft)
  next.teams.slice().sort((a, b) => a.sort_order - b.sort_order || a.display_name.localeCompare(b.display_name, 'zh-CN'))
    .forEach((team, index) => { const target = next.teams.find((item) => item.key === team.key); if (target) target.sort_order = index + 1 })
  for (const team of next.teams) {
    next.players.filter((player) => player.team_key === team.key)
      .sort((a, b) => (a.member_order ?? 9999) - (b.member_order ?? 9999) || a.name.localeCompare(b.name, 'zh-CN'))
      .forEach((player, index) => { player.member_order = index + 1 })
  }
  next.players.filter((player) => player.team_key === null).forEach((player) => { player.member_order = null })
  return next
}

function validation(draft: Draft, strict: boolean): string | null {
  const names = draft.teams.map((team) => team.display_name.trim())
  if (names.some((name) => !name)) return '队伍名称不能为空'
  if (new Set(names).size !== names.length) return '队伍名称不能重复'
  const emptyTeams = (draft?.teams ?? []).filter((team) => !(draft?.players ?? []).some((player) => player.team_key === team.key))
  if (emptyTeams.length) return `空队伍：${emptyTeams.map((team) => `「${team.display_name || '未命名队伍'}」`).join('、')}；每支队伍至少需要一名队员`
  if (draft.players.some((player) => !player.name.trim())) return '队员姓名不能为空'
  if (strict && draft.teams.length < 2) return '确认名单至少需要两支队伍'
  if (strict && draft.players.some((player) => player.team_key === null)) return '仍有队员未加入任何队伍'
  return null
}

export default function TeamRosterPage() {
  const [params] = useSearchParams()
  const rawTid = params.get('tid')
  const tid = rawTid ? Number(rawTid) : getActiveTournamentId()
  const [sheet, setSheet] = useState<TeamRosterSheet | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [history, setHistory] = useState<Draft[]>([])
  const [future, setFuture] = useState<Draft[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [anchor, setAnchor] = useState<string | null>(null)
  const [sort, setSort] = useState<SortKey>('official')
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [dialog, setDialog] = useState<Dialog>(null)
  const [teamName, setTeamName] = useState('')
  const [playerForm, setPlayerForm] = useState({ name: '', college: '', rating: '1000', team: '' })
  const dialogClose = useRef<HTMLButtonElement | null>(null)
  const dialogRoot = useRef<HTMLDivElement | null>(null)
  const restoreFocus = useRef<HTMLElement | null>(null)
  const draggingKey = useRef<string | null>(null)
  const openDialog = (next: Dialog) => { restoreFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setDialog(next) }
  const closeDialog = () => { setDialog(null); requestAnimationFrame(() => restoreFocus.current?.focus()) }

  const load = useCallback(async () => {
    if (tid === null || !Number.isInteger(tid)) return
    setLoading(true); setMessage('')
    try {
      const next = await api.getTeamRoster(tid)
      setSheet(next); setDraft(draftFrom(next)); setHistory([]); setFuture([]); setSelected(new Set())
    } catch (error) { setMessage(messageOf(error)) } finally { setLoading(false) }
  }, [tid])
  useEffect(() => { void load() }, [load])

  const stageLocked = sheet?.tournament.stage !== 'REGISTRATION'
  const locked = Boolean(sheet?.tournament.roster_confirmed) || stageLocked
  const dirty = Boolean(draft && sheet && JSON.stringify(draft) !== JSON.stringify(draftFrom(sheet)))
  const editable = !locked && !busy && !loading
  const mutate = (work: (current: Draft) => Draft) => {
    if (!draft || !editable) return
    setHistory((items) => [...items.slice(-49), clone(draft)])
    setFuture([])
    setDraft(normalizeOrders(work(clone(draft))))
    setMessage('')
  }
  const undo = () => {
    if (!draft || history.length === 0 || !editable) return
    const previous = history[history.length - 1]
    setHistory((items) => items.slice(0, -1)); setFuture((items) => [clone(draft), ...items]); setDraft(previous)
  }
  const redo = () => {
    if (!draft || future.length === 0 || !editable) return
    const next = future[0]
    setFuture((items) => items.slice(1)); setHistory((items) => [...items, clone(draft)]); setDraft(next)
  }
  const save = async (): Promise<boolean> => {
    if (!draft || !sheet || tid === null || !editable) return false
    const problem = validation(draft, false)
    if (problem) { setMessage(problem); return false }
    setBusy(true); setMessage('正在保存名单…')
    try {
      const next = await api.saveTeamRoster(tid, { base_revision: sheet.revision, ...draft })
      setSheet(next); setDraft(draftFrom(next)); setHistory([]); setFuture([]); setMessage('名单已保存')
      return true
    } catch (error) { setMessage(messageOf(error)); return false } finally { setBusy(false) }
  }

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      if (event.key.toLowerCase() === 's') { event.preventDefault(); void save() }
      if (event.key.toLowerCase() === 'z') { event.preventDefault(); undo() }
      if (event.key.toLowerCase() === 'y') { event.preventDefault(); redo() }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  })
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    if (!dialog) return
    dialogClose.current?.focus()
    const trap = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeDialog(); return }
      if (event.key !== 'Tab') return
      const focusable = dialogRoot.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), [href]')
      if (!focusable?.length) return
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', trap)
    return () => window.removeEventListener('keydown', trap)
  }, [dialog])

  const rows = useMemo(() => {
    if (!draft) return []
    const teamNameOf = new Map(draft.teams.map((team) => [team.key, team.display_name]))
    const lower = filter.trim().toLocaleLowerCase()
    const result = draft.players.filter((player) => !lower || [player.name, player.college ?? '', teamNameOf.get(player.team_key ?? '') ?? '未分队'].join(' ').toLocaleLowerCase().includes(lower))
    return result.sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name, 'zh-CN')
      if (sort === 'rating') return b.rating_points - a.rating_points
      if (sort === 'team') return (teamNameOf.get(a.team_key ?? '') ?? '未分队').localeCompare(teamNameOf.get(b.team_key ?? '') ?? '未分队', 'zh-CN')
      const orderOf = new Map(draft.teams.map((team) => [team.key, team.sort_order]))
      return (orderOf.get(a.team_key ?? '') ?? 9999) - (orderOf.get(b.team_key ?? '') ?? 9999) || (a.member_order ?? 9999) - (b.member_order ?? 9999)
    })
  }, [draft, filter, sort])
  const selectedRows = rows.filter((row) => selected.has(row.key))
  const selectedTeamKey = selectedRows[0]?.team_key ?? null
  const reorderDisabled = sort !== 'official' || Boolean(filter)
  const emptyTeams = (draft?.teams ?? []).filter((team) => !(draft?.players ?? []).some((player) => player.team_key === team.key))
  const editTitle = stageLocked ? '赛事已进入比赛阶段，名单已锁定' : sheet.tournament.roster_confirmed ? '名单已冻结；请先撤销冻结' : undefined

  const selectRow = (key: string, event: React.MouseEvent) => {
    const next = new Set(selected)
    if (event.shiftKey && anchor) {
      const start = rows.findIndex((row) => row.key === anchor), end = rows.findIndex((row) => row.key === key)
      rows.slice(Math.min(start, end), Math.max(start, end) + 1).forEach((row) => next.add(row.key))
    } else if (event.ctrlKey || event.metaKey) {
      next.has(key) ? next.delete(key) : next.add(key)
      setAnchor(key)
    } else { next.clear(); next.add(key); setAnchor(key) }
    setSelected(next)
  }
  const selectOnly = (key: string, extend = false) => {
    setSelected((current) => extend ? new Set([...current, key]) : new Set([key]))
    setAnchor(key)
  }
  const gridKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>, index: number) => {
    if (event.target !== event.currentTarget) return
    if (event.key === 'Escape') { event.preventDefault(); setSelected(new Set()); return }
    if (event.key === 'Enter' || event.key === 'F2') {
      event.preventDefault()
      event.currentTarget.querySelector<HTMLElement>('select:not([disabled]), input:not([type="checkbox"]):not([disabled])')?.focus()
      return
    }
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
    event.preventDefault()
    const next = index + (event.key === 'ArrowUp' ? -1 : 1)
    if (next < 0 || next >= rows.length) return
    selectOnly(rows[next].key, event.shiftKey)
    ;(event.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus()
  }
  const dropRowsOnTeam = (teamKey: string | null) => {
    const source = draggingKey.current
    if (!source || !editable || reorderDisabled) return
    const keys = selected.has(source) ? selected : new Set([source])
    mutate((current) => ({ ...current, players: current.players.map((player) => keys.has(player.key) ? { ...player, team_key: teamKey } : player) }))
    draggingKey.current = null
  }
  const assignSelected = (teamKey: string | null) => mutate((current) => ({
    ...current, players: current.players.map((player) => selected.has(player.key) ? { ...player, team_key: teamKey } : player),
  }))
  const moveMember = (direction: -1 | 1) => {
    if (!selectedTeamKey || selectedRows.length !== 1 || reorderDisabled) return
    mutate((current) => {
      const teamRows = current.players.filter((player) => player.team_key === selectedTeamKey).sort((a, b) => (a.member_order ?? 0) - (b.member_order ?? 0))
      const index = teamRows.findIndex((player) => player.key === selectedRows[0].key)
      const target = index + direction
      if (target < 0 || target >= teamRows.length) return current
      const a = teamRows[index], b = teamRows[target]
      const players = current.players.map((player) => player.key === a.key ? { ...player, member_order: b.member_order } : player.key === b.key ? { ...player, member_order: a.member_order } : player)
      return { ...current, players }
    })
  }
  const moveTeam = (direction: -1 | 1) => {
    if (!selectedTeamKey || reorderDisabled) return
    mutate((current) => {
      const ordered = [...current.teams].sort((a, b) => a.sort_order - b.sort_order)
      const index = ordered.findIndex((team) => team.key === selectedTeamKey), target = index + direction
      if (target < 0 || target >= ordered.length) return current
      const a = ordered[index], b = ordered[target]
      return { ...current, teams: current.teams.map((team) => team.key === a.key ? { ...team, sort_order: b.sort_order } : team.key === b.key ? { ...team, sort_order: a.sort_order } : team) }
    })
  }
  const deleteTeam = () => {
    if (!draft || !selectedTeamKey || !editable) return
    const team = draft.teams.find((item) => item.key === selectedTeamKey)
    if (!team || !window.confirm(`删除「${team.display_name}」？队员会保留为未分队。`)) return
    mutate((current) => ({
      ...current,
      teams: current.teams.filter((item) => item.key !== team.key),
      players: current.players.map((player) => player.team_key === team.key ? { ...player, team_key: null, member_order: null } : player),
      deleted_team_ids: team.id ? [...current.deleted_team_ids, team.id] : current.deleted_team_ids,
    }))
  }
  const deleteEmptyTeam = (teamKey: string) => mutate((current) => {
    const team = current.teams.find((item) => item.key === teamKey)
    if (!team) return current
    return {
      ...current,
      teams: current.teams.filter((item) => item.key !== teamKey),
      deleted_team_ids: team.id ? [...current.deleted_team_ids, team.id] : current.deleted_team_ids,
    }
  })
  const deletePlayers = () => {
    if (!selected.size || !editable || !window.confirm('永久删除选中的队员？此操作不可恢复。')) return
    mutate((current) => ({ ...current, players: current.players.filter((player) => !selected.has(player.key)), deleted_player_ids: [...current.deleted_player_ids, ...current.players.filter((player) => selected.has(player.key) && player.id).map((player) => player.id!)] }))
    setSelected(new Set())
  }
  const openPreview = async () => {
    if (!draft) return
    if (dirty && !(await save())) return
    openDialog('preview')
  }
  const confirmRoster = async () => {
    if (!draft || tid === null || locked) return
    const problem = validation(draft, true)
    if (problem) { setMessage(problem); return }
    setBusy(true); setMessage('正在确认名单…')
    try { await api.confirmRoster(tid); await load(); closeDialog(); setMessage('名单已确认并冻结') } catch (error) { setMessage(messageOf(error)) } finally { setBusy(false) }
  }
  const unconfirm = async () => {
    if (tid === null || !sheet?.tournament.roster_confirmed || stageLocked || !window.confirm('撤销冻结后可以修改名单，是否继续？')) return
    setBusy(true); setMessage('正在撤销冻结…')
    try { const next = await api.unconfirmTeamRoster(tid); setSheet(next); setDraft(draftFrom(next)); setMessage('名单已撤销冻结，可以继续编辑') } catch (error) { setMessage(messageOf(error)) } finally { setBusy(false) }
  }

  if (tid === null || !Number.isInteger(tid)) return <div className="card"><h2>队伍与名单</h2><p>请提供有效的 <code>tid</code> 参数。</p><Link className="btn" to="/">返回赛事首页</Link></div>
  if (loading) return <div className="card"><p aria-live="polite">正在加载队伍名单工作表…</p></div>
  if (!sheet || !draft) return <div className="card"><p className="status-error">{message || '无法加载队伍名单'}</p><button className="btn" onClick={() => void load()}>重试</button></div>

  return <div className="team-roster-page">
    <header className="roster-titlebar"><div><span className="eyebrow">TEAM ROSTER WORKBOOK</span><h1>{sheet.tournament.name} · 队伍与名单</h1></div><div className={`roster-lock ${locked ? 'locked' : ''}`}>{stageLocked ? '赛事已进入比赛阶段 · 名单锁定' : locked ? `已冻结${sheet.tournament.confirmed_at ? ` · ${sheet.tournament.confirmed_at}` : ''}` : dirty ? '有未保存更改' : '已保存'}</div></header>
    <section className="roster-ribbon" aria-label="名单工具">
      <div className="ribbon-group"><strong>队伍</strong><button className="ribbon-btn" title={editTitle} disabled={!editable} onClick={() => { setTeamName(''); openDialog('team') }}>＋ 新建</button><button className="ribbon-btn" title={editTitle} disabled={!editable || !selectedTeamKey} onClick={() => { const team = draft.teams.find((item) => item.key === selectedTeamKey); setTeamName(team?.display_name ?? ''); openDialog('rename') }}>重命名</button><button className="ribbon-btn danger" title={editTitle} disabled={!editable || !selectedTeamKey} onClick={deleteTeam}>删除</button><button className="ribbon-btn" disabled={!editable || reorderDisabled || !selectedTeamKey} title={reorderDisabled ? '请先恢复正式顺序' : editTitle} onClick={() => moveTeam(-1)}>队伍↑</button><button className="ribbon-btn" disabled={!editable || reorderDisabled || !selectedTeamKey} title={reorderDisabled ? '请先恢复正式顺序' : editTitle} onClick={() => moveTeam(1)}>队伍↓</button></div>
      <div className="ribbon-group"><strong>队员</strong><button className="ribbon-btn" title={editTitle} disabled={!editable} onClick={() => { setPlayerForm({ name: '', college: '', rating: '1000', team: selectedTeamKey ?? '' }); openDialog('player') }}>＋ 新建队员</button><select aria-label="将选中队员分配到队伍" disabled={!editable || selected.size === 0} value="" onChange={(event) => { if (event.target.value) assignSelected(event.target.value) }}><option value="">分配到队伍…</option>{draft.teams.map((team) => <option key={team.key} value={team.key}>{team.display_name}</option>)}</select><button className="ribbon-btn" title={editTitle} disabled={!editable || selected.size === 0} onClick={() => assignSelected(null)}>移出队伍</button><button className="ribbon-btn danger" title={editTitle} disabled={!editable || selected.size === 0} onClick={deletePlayers}>永久删除</button></div>
      <div className="ribbon-group"><strong>排列</strong><select aria-label="工作表排序" value={sort} onChange={(event) => setSort(event.target.value as SortKey)}><option value="official">正式顺序</option><option value="team">按队伍</option><option value="name">按姓名</option><option value="rating">按积分</option></select><button className="ribbon-btn" disabled={!editable || reorderDisabled || selectedRows.length !== 1 || !selectedTeamKey} title={reorderDisabled ? '请先恢复正式顺序' : editTitle} onClick={() => moveMember(-1)}>队员↑</button><button className="ribbon-btn" disabled={!editable || reorderDisabled || selectedRows.length !== 1 || !selectedTeamKey} title={reorderDisabled ? '请先恢复正式顺序' : editTitle} onClick={() => moveMember(1)}>队员↓</button><button className="ribbon-btn" onClick={() => { setSort('official'); setFilter('') }}>恢复正式顺序</button></div>
      <div className="ribbon-group"><strong>名单</strong><button className="ribbon-btn" title={editTitle} disabled={!editable || history.length === 0} onClick={undo}>↶ 撤销</button><button className="ribbon-btn" title={editTitle} disabled={!editable || future.length === 0} onClick={redo}>↷ 重做</button><button className="ribbon-btn primary" title={editTitle} disabled={!editable || !dirty} onClick={() => void save()}>保存更改</button><button className={`ribbon-btn ${locked ? '' : 'primary'}`} disabled={busy} onClick={() => void openPreview()}>{locked ? '预览名单' : '预览确认'}</button><button className="ribbon-btn" title={stageLocked ? '赛事已进入比赛阶段，不能撤销冻结' : !sheet.tournament.roster_confirmed ? '名单尚未冻结，无需撤销' : undefined} disabled={!sheet.tournament.roster_confirmed || stageLocked || busy} onClick={() => void unconfirm()}>撤销冻结</button></div>
    </section>
    <div className="roster-toolbar"><label>筛选 <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="姓名、单位或队伍" /></label><span>{draft.teams.length} 支队伍 · {draft.players.length} 名队员 · 未分队 {draft.players.filter((player) => !player.team_key).length} 名</span></div>
    {message && <p className={message.includes('已') || message.includes('正在') ? 'status-info' : 'status-error'} role="status" aria-live="polite">{message}</p>}
    {emptyTeams.length > 0 && <aside className="roster-issues" role="alert"><strong>发现 {emptyTeams.length} 支空队伍</strong><span>空队伍不会出现在队员表格中，因此请在这里处理：</span>{emptyTeams.map((team) => <div key={team.key}><b>{team.display_name || '未命名队伍'}</b><button className="ribbon-btn" disabled={!editable || selected.size === 0} onClick={() => assignSelected(team.key)}>将选中队员加入</button><button className="ribbon-btn danger" disabled={!editable} onClick={() => deleteEmptyTeam(team.key)}>删除空队</button></div>)}</aside>}
    <div className="roster-grid-wrap"><table className="roster-grid"><thead><tr><th><input aria-label="全选当前行" type="checkbox" checked={rows.length > 0 && rows.every((row) => selected.has(row.key))} onChange={(event) => setSelected((current) => { const next = new Set(current); rows.forEach((row) => event.target.checked ? next.add(row.key) : next.delete(row.key)); return next })} /></th><th>#</th><th>队伍</th><th>队内序号</th><th>姓名</th><th>单位 / 学院</th><th>积分</th><th>状态</th></tr></thead><tbody>{rows.map((player, index) => <tr key={player.key} tabIndex={0} draggable={editable && !reorderDisabled} aria-selected={selected.has(player.key)} className={selected.has(player.key) ? 'selected' : ''} onClick={(event) => selectRow(player.key, event)} onKeyDown={(event) => gridKeyDown(event, index)} onDragStart={() => { draggingKey.current = player.key }} onDragOver={(event) => { if (editable && !reorderDisabled) event.preventDefault() }} onDrop={() => dropRowsOnTeam(player.team_key ?? null)}><td><input aria-label={`选择 ${player.name}`} type="checkbox" checked={selected.has(player.key)} onClick={(event) => event.stopPropagation()} onChange={() => { const next = new Set(selected); next.has(player.key) ? next.delete(player.key) : next.add(player.key); setSelected(next); setAnchor(player.key) }} /></td><td>{index + 1}</td><td><select aria-label={`${player.name} 所属队伍`} disabled={!editable} value={player.team_key ?? ''} onChange={(event) => mutate((current) => ({ ...current, players: current.players.map((item) => item.key === player.key ? { ...item, team_key: event.target.value || null } : item) }))}><option value="">未分队</option>{draft.teams.map((team) => <option key={team.key} value={team.key}>{team.display_name}</option>)}</select></td><td>{player.member_order ?? '—'}</td><td><input aria-label={`${player.name} 姓名`} disabled={!editable} value={player.name} onChange={(event) => mutate((current) => ({ ...current, players: current.players.map((item) => item.key === player.key ? { ...item, name: event.target.value } : item) }))} /></td><td><input aria-label={`${player.name} 单位`} disabled={!editable} value={player.college ?? ''} onChange={(event) => mutate((current) => ({ ...current, players: current.players.map((item) => item.key === player.key ? { ...item, college: event.target.value || null } : item) }))} /></td><td><input aria-label={`${player.name} 积分`} disabled={!editable} type="number" min="0" value={player.rating_points} onChange={(event) => mutate((current) => ({ ...current, players: current.players.map((item) => item.key === player.key ? { ...item, rating_points: Number(event.target.value) } : item) }))} /></td><td>{player.team_key ? '已分队' : '待分队'}</td></tr>)}</tbody></table>{rows.length === 0 && <p className="roster-empty">暂无符合筛选条件的队员。</p>}</div>
    <footer className="roster-statusbar">{locked ? '浏览模式：名单已冻结，修改工具不可用。' : dirty ? '编辑模式：按 Ctrl+S 保存，确认前可继续调整。' : '编辑模式：当前数据已保存。'}<span>选中 {selected.size} 行</span></footer>

    {dialog && <div ref={dialogRoot} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="roster-dialog-title"><div className="modal roster-modal"><button ref={dialogClose} className="modal-close" aria-label="关闭" onClick={closeDialog}>×</button>{dialog === 'team' && <><h3 id="roster-dialog-title">新建队伍</h3><label>队伍名称<input value={teamName} onChange={(event) => setTeamName(event.target.value)} /></label><div className="modal-actions"><button className="btn" onClick={closeDialog}>取消</button><button className="btn primary" onClick={() => { if (!teamName.trim()) return setMessage('请输入队伍名称'); mutate((current) => ({ ...current, teams: [...current.teams, { key: newKey('team'), id: null, display_name: teamName.trim(), rating_points: 0, sort_order: current.teams.length + 1 }] })); closeDialog() }}>创建</button></div></>}{dialog === 'rename' && <><h3 id="roster-dialog-title">重命名队伍</h3><label>队伍名称<input value={teamName} onChange={(event) => setTeamName(event.target.value)} /></label><div className="modal-actions"><button className="btn" onClick={closeDialog}>取消</button><button className="btn primary" onClick={() => { if (!selectedTeamKey || !teamName.trim()) return; mutate((current) => ({ ...current, teams: current.teams.map((team) => team.key === selectedTeamKey ? { ...team, display_name: teamName.trim() } : team) })); closeDialog() }}>保存</button></div></>}{dialog === 'player' && <><h3 id="roster-dialog-title">新建队员</h3><label>姓名<input value={playerForm.name} onChange={(event) => setPlayerForm({ ...playerForm, name: event.target.value })} /></label><label>单位 / 学院<input value={playerForm.college} onChange={(event) => setPlayerForm({ ...playerForm, college: event.target.value })} /></label><label>积分<input type="number" min="0" value={playerForm.rating} onChange={(event) => setPlayerForm({ ...playerForm, rating: event.target.value })} /></label><label>加入队伍<select value={playerForm.team} onChange={(event) => setPlayerForm({ ...playerForm, team: event.target.value })}><option value="">暂不分队</option>{draft.teams.map((team) => <option key={team.key} value={team.key}>{team.display_name}</option>)}</select></label><div className="modal-actions"><button className="btn" onClick={closeDialog}>取消</button><button className="btn primary" onClick={() => { if (!playerForm.name.trim()) return setMessage('请输入队员姓名'); mutate((current) => ({ ...current, players: [...current.players, { key: newKey('player'), id: null, name: playerForm.name.trim(), college: playerForm.college.trim() || null, rating_points: Number(playerForm.rating) || 0, team_key: playerForm.team || null, member_order: playerForm.team ? current.players.filter((player) => player.team_key === playerForm.team).length + 1 : null }] })); closeDialog() }}>加入名单</button></div></>}{dialog === 'preview' && <><h3 id="roster-dialog-title">{locked ? '名单预览' : '名单预览确认'}</h3><p className="muted">{draft.teams.length} 支队伍 · {draft.players.length} 名队员 · 未分队 {draft.players.filter((player) => !player.team_key).length} 名</p><div className="roster-preview">{draft.teams.slice().sort((a, b) => a.sort_order - b.sort_order).map((team) => <section key={team.key}><strong>{team.sort_order}. {team.display_name}</strong><ol>{draft.players.filter((player) => player.team_key === team.key).sort((a, b) => (a.member_order ?? 0) - (b.member_order ?? 0)).map((player) => <li key={player.key}>{player.name}{player.college ? ` · ${player.college}` : ''}</li>)}</ol></section>)}</div>{locked ? <p className="status-info">名单已冻结，当前为只读预览。</p> : <p className="status-error">{validation(draft, true) ?? ''}</p>}<div className="modal-actions"><button className="btn" onClick={closeDialog}>{locked ? '关闭预览' : '返回编辑'}</button><button className="btn primary" disabled={locked || busy || Boolean(validation(draft, true))} onClick={() => void confirmRoster()}>{locked ? '名单已冻结' : '确认并冻结'}</button></div></>}</div></div>}
  </div>
}
