import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, GenerateMatchesResult, GroupingResult, ImportPlayersResult, ImportPreviewResult, Player, Tournament } from '../api'
import { getActiveTournamentId } from '../activeTournament'
import RosterLaunch from '../components/RosterLaunch'

export default function PlayersPage() {
  const [params] = useSearchParams()
  const tidParam = params.get('tid')
  const tid = tidParam ? Number(tidParam) : getActiveTournamentId()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [players, setPlayers] = useState<Player[]>([])
  const [groups, setGroups] = useState<GroupingResult>({ groups: [] })

  const [name, setName] = useState('')
  const [college, setCollege] = useState('')
  const [ratingPoints, setRatingPoints] = useState(1000)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editCollege, setEditCollege] = useState('')
  const [editRatingPoints, setEditRatingPoints] = useState(1000)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [matchSummary, setMatchSummary] = useState<GenerateMatchesResult | null>(null)
  const [matchCount, setMatchCount] = useState<number | null>(null)
  const [demoModal, setDemoModal] = useState<{ count: number; withSeeds: boolean } | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<ImportPlayersResult | null>(null)
  const [importPreview, setImportPreview] = useState<ImportPreviewResult | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (tid === null) return
    setError(null)
    const [t, ps, gs] = await Promise.all([
      api.getTournament(tid),
      api.listPlayers(tid),
      api.getGroups(tid),
    ])
    setTournament(t)
    setPlayers(ps)
    setGroups(gs)
    if (t.stage === 'GROUP_STAGE' || t.stage === 'KNOCKOUT' || t.stage === 'FINISHED') {
      // 已生成场数仅用于展示，失败不阻断整页（避免本页因该非关键请求报 500）
      try {
        const ms = await api.listMatches(tid, { stage: 'GROUP' })
        setMatchCount(ms.length)
      } catch {
        setMatchCount(null)
      }
    }
  }, [tid])

  useEffect(() => {
    if (tid !== null) {
      load().catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : '加载数据失败'),
      )
    }
  }, [tid, load])

  // 在线报名轻量轮询：REGISTRATION 阶段每 5s 静默刷新选手列表；编辑/操作/弹窗中暂停
  useEffect(() => {
    if (tid === null) return
    const interval = setInterval(() => {
      if (editingId !== null || busy || demoModal !== null || importOpen) return
      api
        .listPlayers(tid)
        .then(setPlayers)
        .catch(() => {
          /* 忽略瞬时失败，下轮恢复 */
        })
    }, 5000)
    return () => clearInterval(interval)
  }, [tid, editingId, busy, demoModal, importOpen])

  if (tid === null) {
    return (
      <div className="card">
        <h2>选手与分组</h2>
        <p className="muted">
          请先在<Link to="/">赛事首页</Link>创建并选择一场赛事。
        </p>
      </div>
    )
  }

  const refresh = async () => {
    setError(null)
    try {
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '刷新失败')
    }
  }

  const addPlayer = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api.addPlayer(tid, { name, college: college || null, rating_points: ratingPoints })
      setName('')
      setCollege('')
      setRatingPoints(1000)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加选手失败')
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (p: Player) => {
    setEditingId(p.id)
    setEditName(p.name)
    setEditCollege(p.college ?? '')
    setEditRatingPoints(p.rating_points)
  }

  const saveEdit = async (p: Player) => {
    setError(null)
    try {
      await api.updatePlayer(tid, p.id, {
        name: editName,
        college: editCollege || null,
        rating_points: editRatingPoints,
      })
      setEditingId(null)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    }
  }

  const removePlayer = async (p: Player) => {
    setError(null)
    if (!window.confirm(`确定删除选手「${p.name}」吗？`)) return
    try {
      await api.deletePlayer(tid, p.id)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const doAutoGroup = async () => {
    setError(null)
    setBusy(true)
    try {
      setGroups(await api.autoGroup(tid))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '自动分组失败')
    } finally {
      setBusy(false)
    }
  }

  const setGroupQualification = async (groupId: number, count: number) => {
    setError(null)
    try {
      await api.setGroupQualification(tid, groupId, count)
      setGroups(await api.getGroups(tid))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改出线人数失败')
    }
  }

  // ---------------- 种子选手 ----------------
  const persistSeeds = async (orderedIds: number[]) => {
    setError(null)
    setBusy(true)
    try {
      setPlayers(await api.setSeeds(tid, orderedIds))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '设置种子失败')
    } finally {
      setBusy(false)
    }
  }

  const addSeed = async (p: Player) => {
    if (tournament && seeds.length >= tournament.group_count) {
      setError(`当前赛事有 ${tournament.group_count} 个小组，最多可设置 ${tournament.group_count} 名种子选手。`)
      return
    }
    await persistSeeds([...seeds.map((s) => s.id), p.id])
  }

  const removeSeed = async (p: Player) => {
    await persistSeeds(seeds.filter((s) => s.id !== p.id).map((s) => s.id))
  }

  const moveSeed = async (p: Player, dir: -1 | 1) => {
    const idx = seeds.findIndex((s) => s.id === p.id)
    const j = idx + dir
    if (j < 0 || j >= seeds.length) return
    const arr = seeds.map((s) => s.id)
    ;[arr[idx], arr[j]] = [arr[j], arr[idx]]
    await persistSeeds(arr)
  }

  const confirmDemoPlayers = async () => {
    if (!demoModal) return
    setError(null)
    setBusy(true)
    try {
      await api.generateDemoPlayers(tid, demoModal.count, demoModal.withSeeds)
      setDemoModal(null)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '生成演示选手失败')
    } finally {
      setBusy(false)
    }
  }

  // ---------------- Excel / CSV 批量导入 ----------------
  const openImport = () => {
    setImportFile(null)
    setImportResult(null)
    setImportPreview(null)
    setImportError(null)
    setImportOpen(true)
  }

  const closeImport = () => {
    setImportOpen(false)
    setImportFile(null)
    setImportResult(null)
    setImportPreview(null)
    setImportError(null)
  }

  const downloadTemplate = () => {
    const csv =
      '\uFEFF姓名,学院/单位,运动员积分,种子序号\n张三,计算机学院,1450,1\n李四,自动化学院,1420,2\n王五,机械学院,1380,\n'
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '选手导入模板.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const doImport = async () => {
    if (!importFile) return
    setImportError(null)
    setImporting(true)
    try {
      const result = await api.importPlayers(tid, importFile)
      setImportResult(result)
      await refresh()
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '导入失败')
    } finally {
      setImporting(false)
    }
  }

  const previewImport = async () => {
    if (!importFile) return
    setImportError(null)
    setImporting(true)
    try {
      setImportPreview(await api.previewPlayersImport(tid, importFile))
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : '预览失败')
    } finally {
      setImporting(false)
    }
  }

  const doUngroup = async () => {
    setError(null)
    if (!window.confirm('确定清空当前分组吗？')) return
    setBusy(true)
    try {
      await api.ungroup(tid)
      setGroups({ groups: [] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '清空分组失败')
    } finally {
      setBusy(false)
    }
  }

  const doGenerateMatches = async () => {
    setError(null)
    setBusy(true)
    try {
      const result = await api.generateGroupMatches(tid)
      setMatchSummary(result)
      setTournament(result.tournament)
      setMatchCount(result.matches_generated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '生成小组比赛失败')
    } finally {
      setBusy(false)
    }
  }

  const groupedCount = players.filter((p) => p.group_id !== null).length
  const locked = tournament !== null && tournament.stage !== 'REGISTRATION'
  const seeds = players
    .filter((p) => p.seed_no !== null)
    .sort((a, b) => (a.seed_no ?? 0) - (b.seed_no ?? 0))

  return (
    <div className="page">
      <div className="card">
        <h2>
          {tournament ? tournament.name : '赛事'} · 选手与分组
          <Link className="btn small float-right" to="/">
            ← 返回首页
          </Link>
        </h2>
        {tournament && (
          <p className="muted">
            日期 {tournament.date} · 球台 {tournament.table_count} 张 · 小组{' '}
            {tournament.group_count} 个 · 每组晋级 {tournament.qualify_per_group} 人 · 选手{' '}
            {players.length} 人（已分组 {groupedCount} 人） · 阶段{' '}
            <span className="badge">{tournament.stage}</span>
          </p>
        )}
        {error && <p className="status-error">{error}</p>}
        {locked && (
          <p className="muted">⚠️ 赛事已进入比赛阶段，选手名单已锁定（不可增删改）。</p>
        )}
      </div>

      {tournament && (
        <RosterLaunch tournament={tournament} players={players} onComplete={refresh} />
      )}

      <div className="card">
        <h3>添加选手</h3>
        <form className="form-inline" onSubmit={addPlayer}>
          <input
            type="text"
            placeholder="姓名（必填）"
            value={name}
            required
            disabled={locked}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            type="text"
            placeholder="学院/单位（选填）"
            value={college}
            disabled={locked}
            onChange={(e) => setCollege(e.target.value)}
          />
          <input
            type="number"
            min={0}
            max={99999}
            placeholder="运动员积分"
            value={ratingPoints}
            disabled={locked}
            onChange={(e) => setRatingPoints(Number(e.target.value))}
          />
          <button type="submit" className="btn primary" disabled={locked || busy}>
            {busy ? '添加中…' : '添加'}
          </button>
        </form>
        {!locked && (
          <div className="button-row" style={{ marginTop: 14 }}>
            <button className="btn" onClick={() => setDemoModal({ count: 16, withSeeds: true })}>
              <span className="demo-tag">Demo</span> 生成演示选手
            </button>
            <button className="btn" onClick={openImport}>
              Excel / CSV 导入
            </button>
          </div>
        )}

        <h3>选手列表</h3>
        {players.length === 0 && <p className="muted">暂无选手，请先添加。</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>姓名</th>
              <th>学院/单位</th>
              <th>积分</th>
              <th>种子</th>
              <th>分组</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                {editingId === p.id ? (
                  <>
                    <td>
                      <input
                        type="text"
                        value={editName}
                        required
                        onChange={(e) => setEditName(e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={editCollege}
                        onChange={(e) => setEditCollege(e.target.value)}
                      />
                    </td>
                    <td><input type="number" min={0} value={editRatingPoints} onChange={(e) => setEditRatingPoints(Number(e.target.value))} /></td>
                    <td>{p.seed_no !== null ? `⭐ ${p.seed_no}号` : '—'}</td>
                    <td>{p.group_id !== null ? '已分组' : '—'}</td>
                    <td>
                      <button className="btn small primary" onClick={() => saveEdit(p)}>
                        保存
                      </button>{' '}
                      <button className="btn small" onClick={() => setEditingId(null)}>
                        取消
                      </button>
                    </td>
                  </>
                ) : (
                  <>
                    <td>{p.name}</td>
                    <td>{p.college || '—'}</td>
                    <td className="rating-cell">{p.rating_points}</td>
                    <td>
                      {p.seed_no !== null ? (
                        <span className="seed-badge">⭐ {p.seed_no}号</span>
                      ) : (
                        <button className="btn small" onClick={() => addSeed(p)} disabled={locked || busy}>
                          设为种子
                        </button>
                      )}
                    </td>
                    <td>{p.group_id !== null ? '已分组' : '—'}</td>
                    <td>
                      <button className="btn small" onClick={() => startEdit(p)} disabled={locked}>
                        修改
                      </button>{' '}
                      <button
                        className="btn small danger"
                        onClick={() => removePlayer(p)}
                        disabled={locked}
                      >
                        删除
                      </button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>种子选手</h3>
        {seeds.length === 0 ? (
          <p className="muted">尚未设置种子选手。种子选手将在自动分组时被分散到不同小组。</p>
        ) : (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>种子</th>
                  <th>姓名</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {seeds.map((p, i) => (
                  <tr key={p.id}>
                    <td>⭐ {p.seed_no}号</td>
                    <td>{p.name}</td>
                    <td>
                      <button className="btn small" onClick={() => moveSeed(p, -1)} disabled={i === 0 || locked || busy}>
                        ↑
                      </button>{' '}
                      <button
                        className="btn small"
                        onClick={() => moveSeed(p, 1)}
                        disabled={i === seeds.length - 1 || locked || busy}
                      >
                        ↓
                      </button>{' '}
                      <button className="btn small danger" onClick={() => removeSeed(p)} disabled={locked || busy}>
                        取消
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              已设置 {seeds.length} / {tournament?.group_count ?? 0} 名种子（自动分组时分散到不同小组）
            </p>
          </>
        )}
      </div>

      <div className="card">
        <h3>抽签与分组</h3>
        <p className="muted">
          {tournament?.roster_confirmed
            ? `名单已确认，可将参赛位重新抽入 ${tournament.group_count} 个小组。`
            : '请先在上方确认参赛名单；确认后会播放抽签过场并自动生成分组。'}
        </p>
        <div className="button-row">
          <button
            className="btn primary"
            onClick={doAutoGroup}
            disabled={busy || players.length === 0 || locked || !tournament?.roster_confirmed}
          >
            {busy ? '处理中…' : groups.groups.length ? '重新抽签分组' : '抽签分组'}
          </button>
          {groups.groups.length > 0 && (
            <button className="btn" onClick={doUngroup} disabled={busy || locked}>
              清空分组
            </button>
          )}
        </div>

        {groups.groups.length > 0 && (
          <div className="group-grid">
            {groups.groups.map((g) => (
              <div className="group-card" key={g.id}>
                <div className="group-card-head">
                  <h4>{g.name}</h4>
                  <label className="qualification-control">
                    出线
                    <select
                      value={g.qualify_count ?? tournament?.qualify_per_group ?? 2}
                      disabled={locked}
                      onChange={(e) => setGroupQualification(g.id, Number(e.target.value))}
                    >
                      {Array.from(
                        { length: Math.max(1, (g.entries.length || g.players.length) - 1) },
                        (_, i) => i + 1,
                      ).map((n) => <option key={n} value={n}>{n} 名</option>)}
                    </select>
                  </label>
                </div>
                <ul>
                  {(g.entries.length > 0 ? g.entries : g.players).map((p) => {
                    const sp = players.find((x) => x.id === p.id)
                    return (
                      <li key={p.id}>
                        {sp?.seed_no != null && <span className="seed-badge">⭐{sp.seed_no}</span>}{' '}
                        {'display_name' in p ? p.display_name : p.name}
                        {'college' in p && p.college ? <span className="muted">（{p.college}）</span> : null}
                      </li>
                    )
                  })}
                </ul>
                <p className="muted">{g.entries.length || g.players.length} 个参赛位</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3>小组循环赛</h3>
        {tournament?.stage === 'REGISTRATION' ? (
          <>
            <p className="muted">
              为每个小组自动生成单循环比赛（同组每两人交手一次）。生成后赛事将进入小组赛阶段。
            </p>
            <div className="button-row">
              <button
                className="btn primary"
                onClick={doGenerateMatches}
                disabled={busy || groups.groups.length === 0 || !tournament?.roster_confirmed}
              >
                {busy ? '处理中…' : '生成小组比赛'}
              </button>
            </div>
          </>
        ) : (
          <p className="muted">
            小组赛已生成，共{' '}
            <strong>{matchSummary ? matchSummary.matches_generated : matchCount ?? '—'}</strong>{' '}
            场
            {matchSummary && (
              <>
                （{Object.entries(matchSummary.per_group).map(([g, n]) => `${g} ${n} 场`).join('，')}）
              </>
            )}
            。比赛控制台见「比赛控制台」页（任务 7）。
          </p>
        )}
      </div>

      {demoModal && (
        <div className="modal-overlay" onClick={() => setDemoModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>生成演示选手</h3>
            {players.length > 0 && (
              <p className="status-warn">
                当前已有 {players.length} 名选手。继续生成将在现有选手之后追加演示选手。
              </p>
            )}
            <div className="modal-pair">
              <div className="modal-label">数量</div>
              <div className="demo-count-row">
                {[8, 16, 24].map((n) => (
                  <button
                    key={n}
                    className={`btn ${demoModal.count === n ? 'primary' : ''}`}
                    onClick={() => setDemoModal({ ...demoModal, count: n })}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
            <label className="demo-check">
              <input
                type="checkbox"
                checked={demoModal.withSeeds}
                onChange={(e) => setDemoModal({ ...demoModal, withSeeds: e.target.checked })}
              />
              自动设置前 {Math.min(4, tournament?.group_count ?? 4)} 名为种子
            </label>
            <div className="modal-actions">
              <button className="btn" onClick={() => setDemoModal(null)}>
                取消
              </button>
              <button className="btn primary" onClick={confirmDemoPlayers} disabled={busy}>
                {busy ? '生成中…' : '生成'}
              </button>
            </div>
          </div>
        </div>
      )}

      {importOpen && (
        <div className="modal-overlay" onClick={closeImport}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <h3>批量导入选手</h3>
            <p className="muted">
              支持：Excel (.xlsx) / CSV (.csv)
              <br />• 第一行为表头，“姓名”为必填列
              <br />• “学院/单位”“种子序号”为可选列
            </p>
            <div className="button-row">
              <button className="btn small" onClick={downloadTemplate}>
                下载 CSV 模板
              </button>
            </div>
            {!importResult ? (
              <>
                <div className="import-file-row">
                  <input
                    type="file"
                    accept=".xlsx,.csv"
                    onChange={(e) => {
                      const f = e.target.files?.[0] ?? null
                      if (f && f.size > 5 * 1024 * 1024) {
                        setImportError('文件过大，当前 Demo 仅支持 5MB 以内的名单文件')
                        setImportFile(null)
                        return
                      }
                      setImportFile(f)
                      setImportPreview(null)
                      setImportError(null)
                    }}
                  />
                </div>
                {importFile && <p className="muted">已选择：{importFile.name}</p>}
                {importError && <p className="status-error">{importError}</p>}
                <div className="modal-actions">
                  <button className="btn" onClick={closeImport}>
                    取消
                  </button>
                  <button
                    className="btn primary"
                    onClick={importPreview ? doImport : previewImport}
                    disabled={!importFile || importing}
                  >
                    {importing ? '正在处理…' : importPreview ? `确认导入 ${importPreview.valid_rows} 人` : '预览并校验'}
                  </button>
                </div>
                {importPreview && <div className="import-preview">
                  <div className="import-preview-summary"><strong>{importPreview.valid_rows}</strong> 行可导入 <span>· {importPreview.skipped} 行跳过 · 请确认后再写入</span></div>
                  <div className="import-preview-table"><table className="data-table"><thead><tr><th>行</th><th>姓名</th><th>单位</th><th>积分</th><th>种子</th><th>校验</th></tr></thead><tbody>
                    {importPreview.rows.map((row) => <tr key={row.row}><td>{row.row}</td><td>{row.name || '—'}</td><td>{row.college || '—'}</td><td>{row.rating_points}</td><td>{row.seed_no ?? '—'}</td><td className={`preview-${row.status}`}>{row.message ?? '可导入'}</td></tr>)}
                  </tbody></table></div>
                  <p className="muted">已显示全部 {importPreview.total_rows} 行。</p>
                </div>}
              </>
            ) : (
              <>
                <div className="import-result">
                  <p className="status-ok">导入完成</p>
                  <p className="muted">
                    读取：{importResult.total_rows} 行 · 成功：{importResult.imported} 人 ·
                    跳过：{importResult.skipped} 行
                  </p>
                  {importResult.errors.length > 0 && (
                    <ul className="import-errors">
                      {importResult.errors.slice(0, 10).map((e, i) => (
                        <li key={i}>
                          第{e.row}行：{e.message}
                        </li>
                      ))}
                      {importResult.errors.length > 10 && (
                        <li className="muted">…共 {importResult.errors.length} 条问题</li>
                      )}
                    </ul>
                  )}
                </div>
                <div className="modal-actions">
                  <button className="btn primary" onClick={closeImport}>
                    完成
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
