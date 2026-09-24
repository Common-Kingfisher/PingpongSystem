import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, GroupInfo, OrganizationUpsert, Tournament, TournamentFormat, VenueUpsert } from '../api'
import { getActiveTournamentId, setActiveTournamentId } from '../activeTournament'
import './TournamentSettingsPage.css'

const tabs = ['基本信息', '赛制与规则', '报名设置', '公开与展示', '高级操作'] as const
type SettingsTab = typeof tabs[number]

const formats: Array<{ code: TournamentFormat; name: string; caption: string; flow: string }> = [
  { code: 'GROUP_KNOCKOUT', name: '小组赛 + 淘汰赛', caption: '先循环排名，再进入淘汰签。', flow: '名单 → 分组 → 小组赛 → 出线 → 淘汰赛' },
  { code: 'ROUND_ROBIN', name: '全体循环赛', caption: '所有参赛位相互交手，按最终排名结算。', flow: '名单 → 循环对阵 → 排名' },
  { code: 'SINGLE_ELIMINATION', name: '单淘汰', caption: '一场定去留，直接沿淘汰签晋级。', flow: '名单 → 淘汰签 → 冠军' },
]

const eventNames = { SINGLES: '单打', DOUBLES: '双打', TEAM: '团体' } as const
const operationNames = { LIVE: '正式赛事', DEMO: '演示赛事' } as const
const canOpenRegistration = (tournament: Tournament) => tournament.stage === 'REGISTRATION' && !tournament.roster_confirmed
const effectiveRegistrationEnabled = (tournament: Tournament) => tournament.registration_enabled && canOpenRegistration(tournament)

export interface TournamentSettingsPageProps { tournament?: Tournament | null }

const textOrNull = (value: string) => value.trim() || null

export default function TournamentSettingsPage({ tournament: suppliedTournament }: TournamentSettingsPageProps) {
  const queryTid = Number(new URLSearchParams(window.location.search).get('tid'))
  const tid = suppliedTournament?.id ?? (Number.isSafeInteger(queryTid) && queryTid > 0 ? queryTid : getActiveTournamentId())
  const [tournament, setTournament] = useState<Tournament | null>(suppliedTournament ?? null)
  const [activeTab, setActiveTab] = useState<SettingsTab>('赛制与规则')
  const [formatDraft, setFormatDraft] = useState<TournamentFormat | null>(suppliedTournament?.format_code ?? null)
  const [registrationDraft, setRegistrationDraft] = useState(suppliedTournament ? effectiveRegistrationEnabled(suppliedTournament) : false)
  const [organization, setOrganization] = useState<OrganizationUpsert>({ name: '', contact_name: null, contact: null, note: null })
  const [venue, setVenue] = useState<VenueUpsert>({ name: '', address: null, contact_name: null, contact: null, note: null })
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [qualificationDrafts, setQualificationDrafts] = useState<Record<number, number>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmFormat, setConfirmFormat] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteName, setDeleteName] = useState('')

  const applyTournament = (next: Tournament) => {
    setTournament(next); setFormatDraft(next.format_code ?? null); setRegistrationDraft(effectiveRegistrationEnabled(next))
  }

  const load = useCallback(async () => {
    if (tid === null) return
    if (suppliedTournament !== undefined) {
      if (suppliedTournament) applyTournament(suppliedTournament)
      return
    }
    const current = await api.getTournament(tid)
    applyTournament(current)
    const [orgResult, venueResult] = await Promise.allSettled([api.getOrganization(tid), api.getVenue(tid)])
    if (orgResult.status === 'fulfilled') setOrganization({ name: orgResult.value.name, contact_name: orgResult.value.contact_name, contact: orgResult.value.contact, note: orgResult.value.note })
    else if (!(orgResult.reason instanceof ApiError && orgResult.reason.status === 404)) throw orgResult.reason
    if (venueResult.status === 'fulfilled') setVenue({ name: venueResult.value.name, address: venueResult.value.address, contact_name: venueResult.value.contact_name, contact: venueResult.value.contact, note: venueResult.value.note })
    else if (!(venueResult.reason instanceof ApiError && venueResult.reason.status === 404)) throw venueResult.reason
  }, [tid, suppliedTournament])

  useEffect(() => { load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : '赛事设置加载失败')) }, [load])

  useEffect(() => {
    if (tid === null || tournament?.format_code !== 'GROUP_KNOCKOUT') {
      setGroups([]); setQualificationDrafts({}); return
    }
    api.getGroups(tid).then((result) => {
      setGroups(result.groups)
      setQualificationDrafts(Object.fromEntries(result.groups.map((group) => [group.id, group.qualify_count ?? tournament.qualify_per_group])))
    }).catch((err: unknown) => setError(err instanceof ApiError ? err.message : '小组晋级设置加载失败'))
  }, [tid, tournament?.format_code, tournament?.qualify_per_group])

  const run = async (work: () => Promise<void>, fallback: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { await work() } catch (err) { setError(err instanceof ApiError ? err.message : fallback) } finally { setBusy(false) }
  }

  const saveFormat = () => {
    if (!tournament || !formatDraft || formatDraft === tournament.format_code) return
    setConfirmFormat(true)
  }
  const confirmFormatChange = () => void run(async () => {
    if (!tournament || !formatDraft) return
    const next = await api.updateTournamentFormat(tournament.id, { format_code: formatDraft, rule_config: {} })
    applyTournament(next); setConfirmFormat(false); setNotice('赛制已保存。后续页面将按新赛制显示适用能力。')
  }, '保存赛制失败')
  const saveRegistration = () => void run(async () => {
    if (!tournament) return
    if (registrationDraft && !canOpenRegistration(tournament)) throw new Error('参赛名单已确认或赛事已开始，不能再开启报名。')
    const next = await api.updateTournamentRegistration(tournament.id, registrationDraft)
    applyTournament(next); setNotice(registrationDraft ? '线上报名已开启。' : '线上报名已关闭。')
  }, '保存报名设置失败')
  const saveOrganization = () => void run(async () => {
    if (!tournament || !organization.name.trim()) return
    await api.upsertOrganization(tournament.id, { ...organization, name: organization.name.trim(), contact_name: textOrNull(organization.contact_name ?? ''), contact: textOrNull(organization.contact ?? ''), note: textOrNull(organization.note ?? '') })
    setNotice('组织方信息已保存。')
  }, '保存组织方失败')
  const saveVenue = () => void run(async () => {
    if (!tournament || !venue.name.trim()) return
    await api.upsertVenue(tournament.id, { ...venue, name: venue.name.trim(), address: textOrNull(venue.address ?? ''), contact_name: textOrNull(venue.contact_name ?? ''), contact: textOrNull(venue.contact ?? ''), note: textOrNull(venue.note ?? '') })
    setNotice('场馆信息已保存。')
  }, '保存场馆失败')
  const saveGroupQualification = (group: GroupInfo) => void run(async () => {
    if (!tournament) return
    const qualifyCount = qualificationDrafts[group.id]
    const updated = await api.setGroupQualification(tournament.id, group.id, qualifyCount)
    setGroups((current) => current.map((item) => item.id === updated.id ? updated : item))
    setQualificationDrafts((current) => ({ ...current, [updated.id]: updated.qualify_count ?? qualifyCount }))
    setNotice(`${updated.name}晋级人数已保存。`)
  }, '保存小组晋级人数失败')
  const exportData = () => void run(async () => {
    if (!tournament) return
    const data = await api.exportTournament(tournament.id)
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `${tournament.name.replace(/[\\/:*?"<>|]/g, '_')}-export.json`; link.click(); URL.revokeObjectURL(url)
    setNotice('赛事 JSON 已导出。')
  }, '导出赛事失败')
  const deleteTournament = () => void run(async () => {
    if (!tournament) return
    await api.deleteTournament(tournament.id, tournament.operation_mode === 'LIVE' ? deleteName : undefined)
    setActiveTournamentId(null); window.location.assign('/')
  }, '删除赛事失败')

  if (tid === null && !tournament) return <div className="card"><h2>赛事设置</h2><p className="muted">请先选择一场赛事。</p></div>

  const changedFormat = Boolean(tournament && formatDraft && formatDraft !== tournament.format_code)
  const registrationChanged = Boolean(tournament && registrationDraft !== tournament.registration_enabled)
  const registrationCanOpen = Boolean(tournament && canOpenRegistration(tournament))
  const registrationIsEffective = Boolean(tournament && effectiveRegistrationEnabled(tournament))
  const registrationClosedReason = tournament?.roster_confirmed ? '参赛名单已确认，报名已关闭。' : tournament?.stage !== 'REGISTRATION' ? '赛事已开始，报名已关闭。' : null
  const publicUrl = tournament ? `${window.location.origin}/public/t/${tournament.id}/live` : ''

  return <div className="tournament-settings">
    <header className="settings-heading"><div><span>TOURNAMENT SETTINGS</span><h1>赛事设置</h1><p>只展示当前后端已经能够保存和执行的设置。</p></div><div className="settings-heading-mark" aria-hidden="true">TT<span>规则档案</span></div></header>
    {error && <p className="status-error" role="alert">{error}</p>}{notice && <p className="status-ok" role="status">{notice}</p>}
    <div className="settings-tabs" role="tablist" aria-label="赛事设置分类">{tabs.map((tab, index) => <button id={`settings-tab-${index}`} key={tab} type="button" role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? 'is-active' : ''} onClick={() => { setActiveTab(tab); setError(null); setNotice(null) }}>{tab}</button>)}</div>

    <div className="settings-panel" role="tabpanel">
      {activeTab === '基本信息' && <>
        <section className="settings-section"><header><span>01 / EVENT FACTS</span><h2>赛事事实</h2></header><div className="settings-fact-grid"><Fact label="赛事名称" value={tournament?.name ?? '—'} /><Fact label="比赛日期" value={tournament?.date ?? '—'} /><Fact label="项目" value={tournament ? eventNames[tournament.event_type] : '—'} /><Fact label="运行模式" value={tournament ? operationNames[tournament.operation_mode] : '—'} /></div><p className="muted">以上字段当前为只读；本阶段不伪造尚未存在的修改接口。</p></section>
        <div className="settings-two-column"><Editor title="组织方" kicker="ORGANIZATION" onSave={saveOrganization} disabled={busy || !organization.name.trim()}><TextField label="组织方名称" value={organization.name} onChange={(value) => setOrganization({ ...organization, name: value })} /><TextField label="联系人" value={organization.contact_name ?? ''} onChange={(value) => setOrganization({ ...organization, contact_name: value })} /><TextField label="联系方式" value={organization.contact ?? ''} onChange={(value) => setOrganization({ ...organization, contact: value })} /><TextField label="备注" value={organization.note ?? ''} onChange={(value) => setOrganization({ ...organization, note: value })} /></Editor>
        <Editor title="比赛场馆" kicker="VENUE" onSave={saveVenue} disabled={busy || !venue.name.trim()}><TextField label="场馆名称" value={venue.name} onChange={(value) => setVenue({ ...venue, name: value })} /><TextField label="地址" value={venue.address ?? ''} onChange={(value) => setVenue({ ...venue, address: value })} /><TextField label="联系人" value={venue.contact_name ?? ''} onChange={(value) => setVenue({ ...venue, contact_name: value })} /><TextField label="联系方式" value={venue.contact ?? ''} onChange={(value) => setVenue({ ...venue, contact: value })} /></Editor></div>
        <section className="settings-section contract-waiting"><h2>球台设置</h2><p>当前球台数量：<strong>{tournament?.table_count ?? '—'}</strong>。后端暂未提供本阶段可用的球台设置接口，因此保持只读。</p></section>
      </>}

      {activeTab === '赛制与规则' && <>
        {tournament?.event_type === 'TEAM' ? <section className="settings-section contract-waiting"><header><span>TEAM FORMAT</span><h2>团体赛使用独立赛制流程</h2></header><p>当前三个 format 均为个人赛处理器，后端会明确拒绝团体赛事保存。请在“队伍与名单 / 团体对抗 / 团体淘汰签”中管理团体流程。</p></section> : <>
          <section className="settings-section"><header><span>01 / FORMAT</span><h2>选择赛事赛制</h2></header><div className="format-card-grid">{formats.map((format) => <button key={format.code} type="button" className={`format-card${formatDraft === format.code ? ' is-selected' : ''}`} onClick={() => setFormatDraft(format.code)}><span>{format.code}</span><strong>{format.name}</strong><p>{format.caption}</p><small>{format.flow}</small></button>)}</div></section>
          <section className="settings-section"><header><span>02 / APPLICABLE RULES</span><h2>当前适用规则</h2></header>{formatDraft === 'GROUP_KNOCKOUT' ? <div className="settings-fact-grid"><Fact label="小组数量" value={`${tournament?.group_count ?? '—'} 组`} /><Fact label="默认每组晋级" value={`前 ${tournament?.qualify_per_group ?? '—'} 名`} /><Fact label="比赛局制" value={tournament ? `${tournament.games_to_win * 2 - 1} 局 ${tournament.games_to_win} 胜` : '—'} /><Fact label="每局目标分" value={`${tournament?.points_to_win ?? '—'} 分`} /></div> : formatDraft === 'ROUND_ROBIN' ? <div className="settings-fact-grid"><Fact label="排名范围" value="全部参赛位" /><Fact label="比赛局制" value={tournament ? `${tournament.games_to_win * 2 - 1} 局 ${tournament.games_to_win} 胜` : '—'} /></div> : formatDraft === 'SINGLE_ELIMINATION' ? <div className="settings-fact-grid"><Fact label="淘汰方式" value="单败淘汰" /><Fact label="比赛局制" value={tournament ? `${tournament.games_to_win * 2 - 1} 局 ${tournament.games_to_win} 胜` : '—'} /></div> : <p className="muted">尚未选择赛制。</p>}<p className="muted">不适用于当前赛制的规则不会显示。小组数、默认晋级数、局制和名次规则等待统一规则更新接口；已生成小组的逐组晋级人数使用现有真实接口保存。不提供原始 rule_config 编辑器。</p></section>
          {formatDraft === 'GROUP_KNOCKOUT' && tournament?.format_code === 'GROUP_KNOCKOUT' && <section className="settings-section group-qualification-settings"><header><span>03 / GROUP QUALIFICATION</span><h2>逐组晋级人数</h2></header><p className="muted">这里编辑已生成小组的实际晋级人数。保存后由后端持久化，并使该组已有人工晋级裁定失效。</p>{groups.length === 0 ? <p className="empty-invite">尚未生成分组。请先前往“抽签与编排”生成分组。</p> : <div className="group-qualification-grid">{groups.map((group) => { const current = group.qualify_count ?? tournament.qualify_per_group; const draft = qualificationDrafts[group.id] ?? current; return <div className="group-qualification-row" key={group.id}><div><strong>{group.name}</strong><small>{group.entries.length || group.players.length} 个参赛位 · 当前前 {current} 名晋级</small></div><label>晋级人数<input aria-label={`${group.name}晋级人数`} type="number" min={1} max={20} value={draft} disabled={busy || !['REGISTRATION', 'GROUP_STAGE'].includes(tournament.stage)} onChange={(event) => setQualificationDrafts((values) => ({ ...values, [group.id]: Number(event.target.value) }))} /></label><button className="btn primary" type="button" disabled={busy || draft === current || draft < 1 || draft > 20 || !['REGISTRATION', 'GROUP_STAGE'].includes(tournament.stage)} onClick={() => saveGroupQualification(group)}>保存{group.name}</button></div> })}</div>} {!['REGISTRATION', 'GROUP_STAGE'].includes(tournament.stage) && <p className="status-warn">淘汰赛开始后不能修改出线人数。</p>}</section>}
          <footer className="settings-actions"><span>{changedFormat ? '存在未保存的赛制变更' : '当前配置已保存'}</span><button type="button" disabled={!changedFormat || busy} onClick={() => setFormatDraft(tournament?.format_code ?? null)}>取消修改</button><button className="primary" disabled={!changedFormat || busy} type="button" onClick={saveFormat}>保存设置</button></footer>
        </>}
      </>}

      {activeTab === '报名设置' && <section className="settings-section registration-setting"><header><span>REGISTRATION</span><h2>线上报名</h2></header><label className="setting-switch"><input type="checkbox" checked={registrationDraft} disabled={!registrationCanOpen} onChange={(event) => setRegistrationDraft(event.target.checked)} /><span><strong>{registrationCanOpen ? (registrationDraft ? '允许提交报名' : '暂停接收报名') : '报名已关闭'}</strong><small>{registrationClosedReason ?? '提交后状态为 PENDING，主裁在“参赛名单”确认后才会创建运动员。'}</small></span></label>{!registrationCanOpen && tournament?.registration_enabled && <p className="status-warn">数据中保留了历史开启标记，但当前报名已实际关闭；保存可清理该标记。</p>}<p className="muted">当前状态机只有 PENDING → CONFIRMED，没有“拒绝”状态。</p><footer className="settings-actions"><button disabled={!registrationCanOpen || !registrationChanged || busy} onClick={() => setRegistrationDraft(tournament ? effectiveRegistrationEnabled(tournament) : false)}>取消修改</button><button className="primary" disabled={!registrationChanged || busy} onClick={saveRegistration}>保存报名设置</button></footer></section>}

      {activeTab === '公开与展示' && <section className="settings-section"><header><span>PUBLIC DISPLAY</span><h2>公开赛事页面</h2></header><div className="public-url"><code>{publicUrl || '等待赛事数据'}</code><button className="btn" disabled={!publicUrl} onClick={() => void navigator.clipboard.writeText(publicUrl)}>复制链接</button><a className="btn primary" href={publicUrl || undefined} target="_blank" rel="noreferrer" aria-disabled={!publicUrl}>打开页面</a></div><div className="settings-fact-grid"><Fact label="线上报名" value={registrationIsEffective ? '开放' : '关闭'} note={registrationClosedReason ?? undefined} /><Fact label="公开页面开关" value="尚无后端字段" note="Public 页面由稳定 URL 提供，不伪造 public_enabled。" /></div></section>}

      {activeTab === '高级操作' && <div className="settings-two-column"><section className="settings-section"><header><span>EXPORT</span><h2>导出赛事数据</h2></header><p>下载服务端生成的结构化 JSON，包含落库数据和可推导结果。</p><button className="btn primary" disabled={busy || !tournament} onClick={exportData}>导出 JSON</button></section><section className="settings-section danger-zone"><header><span>DANGER ZONE</span><h2>删除赛事</h2></header><p>删除不可恢复。正式赛事必须输入完整赛事名称；建议先导出。</p><button className="btn danger" disabled={busy || !tournament} onClick={() => setConfirmDelete(true)}>删除赛事</button></section></div>}
    </div>

    {confirmFormat && tournament && formatDraft && <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="确认切换赛制"><div className="modal"><span className="eyebrow">FORMAT CHANGE</span><h3>确认切换赛事赛制</h3><p>将从<strong>{formats.find((item) => item.code === tournament.format_code)?.name ?? '未设置'}</strong>切换为<strong>{formats.find((item) => item.code === formatDraft)?.name}</strong>。</p><p className="status-warn">赛制变化会影响后续抽签、编排、排名与公开展示。若赛事已有比赛，后端可能以 409/422 拒绝；页面会原样显示服务端原因。</p><div className="modal-actions"><button className="btn" onClick={() => setConfirmFormat(false)}>返回检查</button><button className="btn primary" disabled={busy} onClick={confirmFormatChange}>确认并保存</button></div></div></div>}
    {confirmDelete && tournament && <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="确认删除赛事"><div className="modal"><span className="eyebrow">IRREVERSIBLE</span><h3>删除 {tournament.name}</h3><p className="status-warn">此操作不可恢复。请先导出赛事数据。</p>{tournament.operation_mode === 'LIVE' && <label>输入完整赛事名称<input value={deleteName} onChange={(event) => setDeleteName(event.target.value)} placeholder={tournament.name} /></label>}<div className="modal-actions"><button className="btn" onClick={() => setConfirmDelete(false)}>取消</button><button className="btn" onClick={exportData}>先导出</button><button className="btn danger" disabled={busy || (tournament.operation_mode === 'LIVE' && deleteName !== tournament.name)} onClick={deleteTournament}>永久删除</button></div></div></div>}
  </div>
}

function Fact({ label, value, note }: { label: string; value: string; note?: string }) { return <div className="settings-fact"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div> }
function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label>{label}<input value={value} onChange={(event) => onChange(event.target.value)} /></label> }
function Editor({ title, kicker, children, onSave, disabled }: { title: string; kicker: string; children: React.ReactNode; onSave: () => void; disabled: boolean }) { return <section className="settings-section settings-editor"><header><span>{kicker}</span><h2>{title}</h2></header><div className="settings-form">{children}</div><button className="btn primary" disabled={disabled} onClick={onSave}>保存{title}</button></section> }
