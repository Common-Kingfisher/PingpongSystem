import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  api,
  ApiError,
  ImportPlayersResult,
  ImportPreviewResult,
  Player,
  Registration,
  Tournament,
} from '../api'
import { getActiveTournamentId } from '../activeTournament'
import RosterLaunch from '../components/RosterLaunch'

type RosterTab = 'official' | 'pending'

export default function PlayersPage() {
  const [params] = useSearchParams()
  const fromUrl = params.get('tid')
  const tid = fromUrl && /^\d+$/.test(fromUrl) ? Number(fromUrl) : getActiveTournamentId()
  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [registrations, setRegistrations] = useState<Registration[]>([])
  const [tab, setTab] = useState<RosterTab>('official')
  const [name, setName] = useState('')
  const [college, setCollege] = useState('')
  const [ratingPoints, setRatingPoints] = useState(1000)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editCollege, setEditCollege] = useState('')
  const [editRating, setEditRating] = useState(1000)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<ImportPreviewResult | null>(null)
  const [importResult, setImportResult] = useState<ImportPlayersResult | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    const [nextTournament, nextPlayers, nextRegistrations] = await Promise.all([
      api.getTournament(tid),
      api.listPlayers(tid),
      api.listRegistrations(tid),
    ])
    setTournament(nextTournament)
    setPlayers(nextPlayers)
    setRegistrations(nextRegistrations)
  }, [tid])

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof ApiError ? err.message : '参赛名单加载失败'))
  }, [load])

  useEffect(() => {
    if (tid === null || tournament?.stage !== 'REGISTRATION') return
    const timer = window.setInterval(() => {
      if (busy || editingId !== null || importOpen) return
      Promise.all([api.listPlayers(tid), api.listRegistrations(tid)]).then(([ps, rs]) => {
        setPlayers(ps); setRegistrations(rs)
      }).catch(() => undefined)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [tid, tournament?.stage, busy, editingId, importOpen])

  if (tid === null) return <div className="card"><h2>参赛名单</h2><p className="muted">请先在<Link to="/">赛事首页</Link>选择赛事。</p></div>

  // confirm-roster 会建立比赛实际使用的 Entry 快照；在后端提供原子撤销确认前，
  // roster_confirmed 必须与赛事开赛同样构成写边界，避免 Player 与 Entry 静默失配。
  const locked = tournament?.stage !== 'REGISTRATION' || Boolean(tournament?.roster_confirmed)
  const pending = registrations.filter((item) => item.status === 'PENDING')

  const run = async (work: () => Promise<void>, fallback: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { await work(); await load() }
    catch (err) { setError(err instanceof ApiError ? err.message : fallback) }
    finally { setBusy(false) }
  }

  const addPlayer = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      await api.addPlayer(tid, { name: name.trim(), college: college.trim() || null, rating_points: ratingPoints })
      setName(''); setCollege(''); setRatingPoints(1000); setNotice('运动员已加入正式名单。')
    }, '添加运动员失败')
  }

  const startEdit = (player: Player) => {
    setEditingId(player.id); setEditName(player.name); setEditCollege(player.college ?? ''); setEditRating(player.rating_points)
  }

  const saveEdit = (player: Player) => void run(async () => {
    await api.updatePlayer(tid, player.id, { name: editName.trim(), college: editCollege.trim() || null, rating_points: editRating })
    setEditingId(null); setNotice('名单信息已保存。')
  }, '保存运动员失败')

  const removePlayer = (player: Player) => {
    if (!window.confirm(`确定从正式名单删除「${player.name}」吗？`)) return
    void run(async () => { await api.deletePlayer(tid, player.id); setNotice('运动员已删除。') }, '删除运动员失败')
  }

  const confirmRegistration = (registration: Registration) => void run(async () => {
    await api.confirmRegistration(tid, registration.id)
    setNotice(`已确认 ${registration.name}，并写入正式名单。`)
  }, '确认报名失败')

  const downloadTemplate = () => {
    const csv = '\uFEFF姓名,所属单位,运动员积分\n张三,信息学院,1200\n李四,,\n'
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = '参赛名单模板.csv'; link.click(); URL.revokeObjectURL(url)
  }

  const previewImport = () => {
    if (!importFile) return
    void run(async () => { setImportPreview(await api.previewPlayersImport(tid, importFile)) }, '导入文件校验失败')
  }

  const importPlayers = () => {
    if (!importFile) return
    void run(async () => { setImportResult(await api.importPlayers(tid, importFile)); setImportPreview(null) }, '导入名单失败')
  }

  const generateDemo = () => {
    if (!window.confirm('将追加 16 名演示运动员，仅用于 DEMO 赛事。继续吗？')) return
    void run(async () => { await api.generateDemoPlayers(tid, 16, false); setNotice('演示名单已生成。') }, '生成演示名单失败')
  }

  return <div className="players-page">
    <div className="page-title-row">
      <div><span className="eyebrow">ROSTER</span><h2>参赛名单</h2><p className="muted">只管理谁参赛；种子、抽签和赛程生成已移至“抽签与编排”。</p></div>
      <Link className="btn primary" to={`/draw?tid=${tid}`}>下一步：抽签与编排 →</Link>
    </div>
    {error && <p className="status-error" role="alert">{error}</p>}
    {notice && <p className="status-ok" role="status">{notice}</p>}

    <div className="settings-tabs roster-tabs" role="tablist" aria-label="名单分类">
      <button role="tab" aria-selected={tab === 'official'} className={tab === 'official' ? 'is-active' : ''} onClick={() => setTab('official')} type="button">正式名单 <b>{players.length}</b></button>
      <button role="tab" aria-selected={tab === 'pending'} className={tab === 'pending' ? 'is-active' : ''} onClick={() => setTab('pending')} type="button">待确认报名 <b>{pending.length}</b></button>
    </div>

    {tab === 'official' ? <>
      <section className="card roster-entry-card">
        <div className="section-heading"><div><span className="eyebrow">DIRECT ENTRY</span><h3>录入运动员</h3></div><span className={`readiness ${locked ? '' : 'ready'}`}>{locked ? '名单已锁定' : '可编辑'}</span></div>
        <form className="inline-form" onSubmit={addPlayer}>
          <input required value={name} disabled={locked || busy} onChange={(e) => setName(e.target.value)} placeholder="姓名（必填）" />
          <input value={college} disabled={locked || busy} onChange={(e) => setCollege(e.target.value)} placeholder="所属单位（选填）" />
          <input type="number" min={0} value={ratingPoints} disabled={locked || busy} onChange={(e) => setRatingPoints(Number(e.target.value))} aria-label="运动员积分" />
          <button className="btn primary" disabled={locked || busy || !name.trim()} type="submit">添加到名单</button>
        </form>
        <p className="muted">运动员积分是可选参考数据。后端会为未填写值使用兼容默认值 1000，它不代表真实水平。</p>
        {!locked && <div className="button-row"><button className="btn" type="button" onClick={() => setImportOpen(true)}>Excel / CSV 导入</button>{tournament?.operation_mode === 'DEMO' && <button className="btn" type="button" onClick={generateDemo}>生成演示名单</button>}</div>}
      </section>

      <section className="card">
        <div className="section-heading"><div><span className="eyebrow">OFFICIAL ROSTER</span><h3>正式参赛名单</h3></div><span>{players.length} 人</span></div>
        {players.length === 0 ? <p className="muted">暂无正式运动员。可以手工录入、导入文件或确认线上报名。</p> : <table className="data-table"><thead><tr><th>姓名</th><th>所属单位</th><th>运动员积分</th><th>状态</th><th>操作</th></tr></thead><tbody>{players.map((player) => <tr key={player.id}>{editingId === player.id ? <>
          <td><input value={editName} onChange={(e) => setEditName(e.target.value)} /></td>
          <td><input value={editCollege} onChange={(e) => setEditCollege(e.target.value)} /></td>
          <td><input type="number" min={0} value={editRating} onChange={(e) => setEditRating(Number(e.target.value))} /></td>
          <td><span className="roster-status">正式名单</span></td>
          <td><button className="btn small primary" onClick={() => saveEdit(player)} disabled={busy}>保存</button> <button className="btn small" onClick={() => setEditingId(null)}>取消</button></td>
        </> : <>
          <td><strong>{player.name}</strong></td><td>{player.college || <span className="missing-value">未填写</span>}</td><td>{player.rating_points}</td><td><span className="roster-status">正式名单</span></td>
          <td><button className="btn small" onClick={() => startEdit(player)} disabled={locked || busy}>修改</button> <button className="btn small danger" onClick={() => removePlayer(player)} disabled={locked || busy}>删除</button></td>
        </>}</tr>)}</tbody></table>}
      </section>
      {tournament && <RosterLaunch tournament={tournament} players={players} onComplete={load} />}
    </> : <section className="card">
      <div className="section-heading"><div><span className="eyebrow">ONLINE REGISTRATION</span><h3>待确认报名</h3></div><span>{pending.length} 条</span></div>
      <p className="muted">线上提交只会进入 PENDING。主裁确认后，系统才创建正式运动员记录；当前契约没有“拒绝报名”状态。</p>
      {pending.length === 0 ? <p className="empty-invite">暂无待确认报名。</p> : <table className="data-table"><thead><tr><th>姓名</th><th>所属单位</th><th>联系方式</th><th>积分</th><th>提交时间</th><th>操作</th></tr></thead><tbody>{pending.map((item) => <tr key={item.id}><td><strong>{item.name}</strong></td><td>{item.affiliation || <span className="missing-value">未填写</span>}</td><td>{item.contact || '—'}</td><td>{item.rating_points}</td><td>{new Date(item.created_at).toLocaleString()}</td><td><button className="btn small primary" disabled={busy || locked} onClick={() => confirmRegistration(item)}>确认并加入名单</button></td></tr>)}</tbody></table>}
    </section>}

    {importOpen && <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="批量导入名单"><div className="modal modal-wide">
      <button className="modal-close" onClick={() => { setImportOpen(false); setImportPreview(null); setImportResult(null); setImportFile(null) }} aria-label="关闭">×</button>
      <h3>批量导入参赛名单</h3><p className="muted">推荐表头：姓名、所属单位、运动员积分。姓名必填，其他列可选。旧版解析器仍兼容“种子序号”，但本页面不推荐在名单阶段设置种子。</p>
      <button className="btn small" onClick={downloadTemplate}>下载推荐 CSV 模板</button>
      <input className="import-file-input" type="file" accept=".xlsx,.csv" onChange={(e) => { setImportFile(e.target.files?.[0] ?? null); setImportPreview(null); setImportResult(null) }} />
      {importPreview && <><p><strong>{importPreview.valid_rows}</strong> 行可导入，{importPreview.skipped} 行跳过。</p><div className="import-preview-table"><table className="data-table"><thead><tr><th>行</th><th>姓名</th><th>单位</th><th>积分</th><th>校验</th></tr></thead><tbody>{importPreview.rows.map((row) => <tr key={row.row}><td>{row.row}</td><td>{row.name || '—'}</td><td>{row.college || '未填写'}</td><td>{row.rating_points}</td><td>{row.message || '可导入'}</td></tr>)}</tbody></table></div></>}
      {importResult && <p className="status-ok">导入完成：成功 {importResult.imported} 人，跳过 {importResult.skipped} 行。</p>}
      <div className="modal-actions"><button className="btn" onClick={() => setImportOpen(false)}>关闭</button>{!importPreview && !importResult && <button className="btn primary" disabled={!importFile || busy} onClick={previewImport}>预览并校验</button>}{importPreview && <button className="btn primary" disabled={busy} onClick={importPlayers}>确认导入 {importPreview.valid_rows} 人</button>}</div>
    </div></div>}
  </div>
}
