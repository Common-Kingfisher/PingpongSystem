import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, BronzeMode, EventType, PlacementMode, Tournament, TournamentMode } from '../api'
import { getActiveTournamentId, setActiveTournamentId } from '../activeTournament'
import { eventTypeLabel, formatName, formatOptions } from '../format'

interface FormState {
  name: string
  date: string
  table_count: number
  group_count: number
  qualify_per_group: number
  event_type: EventType
  bronze_mode: BronzeMode
  placement_mode: PlacementMode
  operation_mode: TournamentMode
  games_to_win: number
  points_to_win: number
}

const emptyForm: FormState = {
  name: '',
  date: new Date().toISOString().slice(0, 10),
  table_count: 6,
  group_count: 4,
  qualify_per_group: 2,
  event_type: 'SINGLES',
  bronze_mode: 'JOINT_BRONZE',
  placement_mode: 'COMPLETE',
  operation_mode: 'LIVE',
  games_to_win: 2,
  points_to_win: 11,
}

export default function HomePage() {
  const navigate = useNavigate()
  const [backendStatus, setBackendStatus] = useState<'checking' | 'ok' | 'error'>('checking')
  const [tournaments, setTournaments] = useState<Tournament[]>([])
  const [form, setForm] = useState<FormState>(emptyForm)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<number | null>(() => getActiveTournamentId())

  const selectTournament = useCallback((id: number) => {
    setActiveTournamentId(id)
    setActiveId(id)
  }, [])

  const loadTournaments = useCallback(() => {
    api
      .listTournaments()
      .then((ts) => {
        setTournaments(ts)
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : '加载赛事失败'))
  }, [])

  useEffect(() => {
    api
      .health()
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('error'))
    loadTournaments()
  }, [loadTournaments])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      const created = await api.createTournament(form)
      setForm(emptyForm)
      loadTournaments()
      selectTournament(created.id) // 新建后自动成为当前赛事
      navigate(created.event_type === 'TEAM' ? `/team-roster?tid=${created.id}` : `/?tid=${created.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建赛事失败')
    }
  }

  const removeTournament = async (t: Tournament) => {
    setError(null)
    const msg =
      `确定删除赛事“${t.name}”吗？\n\n` +
      `该操作将同时删除：\n- 分组\n- 比赛\n- 比分\n- 淘汰赛\n- 球台分配\n- 其他该赛事关联数据\n\n` +
      `此操作不可恢复。`
    if (!window.confirm(msg)) return
    let confirmName: string | undefined
    if (t.operation_mode === 'LIVE') {
      const entered = window.prompt(`正式赛事受到保护。请输入完整赛事名称以确认删除：\n${t.name}`)
      if (entered === null) return
      if (entered !== t.name) {
        setError('赛事名称不一致，已取消删除。')
        return
      }
      confirmName = entered
    }
    try {
      await api.deleteTournament(t.id, confirmName)
      if (activeId === t.id) {
        setActiveTournamentId(null)
        setActiveId(null)
      }
      loadTournaments()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除赛事失败')
    }
  }

  return (
    <div className="page">
      <section className="home-hero">
        <div>
          <span className="eyebrow">TOURNAMENT ADMIN · V0.3</span>
          <h1>创建赛事，<br />或进入已有赛事。</h1>
          <p>这里负责赛事创建与选择；进入赛事后，现场状态与关键操作会集中显示在赛事总览。</p>
        </div>
        <div className="hero-ball" aria-hidden="true"><span /></div>
      </section>
      <div className="card">
        <h2>创建赛事</h2>
        <p className="muted">
          后端连接状态：
          {backendStatus === 'checking' && '检测中…'}
          {backendStatus === 'ok' && <span className="status-ok">正常 ✅</span>}
          {backendStatus === 'error' && (
            <span className="status-error">失败 ❌（请确认后端已启动）</span>
          )}
        </p>
        <form className="form-grid" onSubmit={submit}>
          <label>
            赛事名称
            <input
              type="text"
              required
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="如：2025 秋季乒乓球赛"
            />
          </label>
          <label>
            比赛日期
            <input
              type="date"
              required
              value={form.date}
              onChange={(e) => set('date', e.target.value)}
            />
          </label>
          <label>
            球台数量 (1~15)
            <input
              type="number"
              min={1}
              max={15}
              required
              value={form.table_count}
              onChange={(e) => set('table_count', Number(e.target.value))}
            />
          </label>
          <label>
            小组数量 (1~26)
            <input
              type="number"
              min={1}
              max={26}
              required
              value={form.group_count}
              onChange={(e) => set('group_count', Number(e.target.value))}
            />
          </label>
          <label>
            运行模式
            <select value={form.operation_mode} onChange={(e) => set('operation_mode', e.target.value as TournamentMode)}>
              <option value="LIVE">正式赛事 · 禁用模拟数据</option>
              <option value="DEMO">演示赛事 · 允许一键模拟</option>
            </select>
          </label>
          <label>
            比赛项目
            <select value={form.event_type} onChange={(e) => set('event_type', e.target.value as EventType)}>
              <option value="SINGLES">单打</option>
              <option value="DOUBLES">双打 · 相近积分随机配对</option>
              <option value="TEAM">团体</option>
            </select>
            {form.event_type === 'TEAM' && <small className="muted">队伍、分组、对抗、晋级及淘汰签均由后端校验；不支持的配置会在提交后提示。</small>}
          </label>
          <label>
            季军产生方式
            <select value={form.bronze_mode} onChange={(e) => set('bronze_mode', e.target.value as BronzeMode)}>
              <option value="JOINT_BRONZE">三、四名并列季军</option>
              <option value="BRONZE_MATCH">增加季军赛</option>
            </select>
          </label>
          <label>
            名次排位赛
            <select value={form.placement_mode} onChange={(e) => set('placement_mode', e.target.value as PlacementMode)}>
              <option value="COMPLETE">4 / 8 / 16 人标准签完整排位</option>
              <option value="TIERED" disabled>16 人以上按名次分档（后续版本）</option>
              <option value="OFF">不增加排位赛</option>
            </select>
          </label>
          <label>
            比赛局制
            <select
              value={form.games_to_win}
              onChange={(e) => set('games_to_win', Number(e.target.value))}
            >
              {formatOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            每局目标分
            <input
              type="number"
              min={1}
              max={99}
              required
              value={form.points_to_win}
              onChange={(e) => set('points_to_win', Number(e.target.value))}
            />
          </label>
          <div className="rule-summary">
            <strong>当前规则</strong>
            <span>
              {formatName(form.games_to_win)} · 每局 {form.points_to_win} 分 · 胜 2 / 负 1 / 未赛弃权 0
            </span>
          </div>
          <label>
            每组晋级人数
            <input
              type="number"
              min={1}
              required
              value={form.qualify_per_group}
              onChange={(e) => set('qualify_per_group', Number(e.target.value))}
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn primary">
              创建赛事
            </button>
          </div>
        </form>
        {error && <p className="status-error">{error}</p>}
      </div>

      <div className="card">
        <h2>赛事列表</h2>
        {tournaments.length === 0 && <p className="muted">还没有赛事，请先创建。</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>日期</th>
              <th>球台</th>
              <th>小组</th>
              <th>晋级/组</th>
              <th>项目</th>
              <th>阶段</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tournaments.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>
                  {t.name}
                  <span className={`badge mode-badge ${t.operation_mode === 'LIVE' ? 'live' : 'demo'}`} style={{ marginLeft: 6 }}>
                    {t.operation_mode === 'LIVE' ? '正式' : '演示'}
                  </span>
                  {activeId === t.id && (
                    <span className="badge current-badge" style={{ marginLeft: 6 }}>
                      当前赛事
                    </span>
                  )}
                </td>
                <td>{t.date}</td>
                <td>{t.table_count}</td>
                <td>{t.group_count}</td>
                <td>{t.qualify_per_group}</td>
                <td>{eventTypeLabel(t.event_type)}</td>
                <td>
                  <span className="badge">{t.stage}</span>
                </td>
                <td>
                  <Link
                    className="btn small"
                    to={t.event_type === 'TEAM' ? `/team-roster?tid=${t.id}` : `/?tid=${t.id}`}
                    onClick={() => selectTournament(t.id)}
                  >
                    {t.event_type === 'TEAM' ? '进入队伍与名单' : '进入赛事'}
                  </Link>{' '}
                  <button className="btn small danger" onClick={() => removeTournament(t)}>
                    删除赛事
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
