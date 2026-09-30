import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  ApiError,
  Dashboard,
  Entry,
  GroupingResult,
  Organization,
  Player,
  PreflightResult,
  TableWithMatch,
  Venue,
} from '../api'
import { eventTypeLabel, tournamentFormatLabel, tournamentStageLabel } from '../format'
import './AdminDashboardPage.css'

const POLL_INTERVAL_MS = 10_000

interface DashboardSnapshot {
  dashboard: Dashboard
  preflight: PreflightResult
  players: Player[]
  entries: Entry[]
  groups: GroupingResult
  organization: Organization | null
  venue: Venue | null
}

export interface AdminDashboardPageProps {
  tournamentId: number
}

async function optionalConfiguration<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 404) return null
    throw reason
  }
}

function tableSort(a: TableWithMatch, b: TableWithMatch): number {
  return a.id - b.id || a.name.localeCompare(b.name, 'zh-CN')
}

export function selectDashboardTables(tables: TableWithMatch[]): TableWithMatch[] {
  const occupied = tables.filter((table) => table.status === 'OCCUPIED').sort(tableSort)
  const free = tables.filter((table) => table.status === 'FREE').sort(tableSort).slice(0, 2)
  return [...occupied, ...free]
}

function matchSide(name: string | null | undefined): string {
  return name?.trim() || '待定'
}

export default function AdminDashboardPage({ tournamentId }: AdminDashboardPageProps) {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)
  const [initialError, setInitialError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [stale, setStale] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null)
  const snapshotRef = useRef<DashboardSnapshot | null>(null)
  const requestInFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (requestInFlight.current) return
    requestInFlight.current = true
    try {
      const [dashboard, preflight, players, entries, groups, organization, venue] = await Promise.all([
        api.getDashboard(tournamentId),
        api.getPreflight(tournamentId),
        api.listPlayers(tournamentId),
        api.listEntries(tournamentId),
        api.getGroups(tournamentId),
        optionalConfiguration(api.getOrganization(tournamentId)),
        optionalConfiguration(api.getVenue(tournamentId)),
      ])
      const next = { dashboard, preflight, players, entries, groups, organization, venue }
      snapshotRef.current = next
      setSnapshot(next)
      setInitialError(null)
      setStale(false)
      setLastSyncedAt(new Date())
    } catch (reason) {
      if (snapshotRef.current) {
        setStale(true)
      } else {
        setInitialError(reason instanceof ApiError ? reason.message : '赛事总览加载失败')
      }
    } finally {
      requestInFlight.current = false
      setLoading(false)
    }
  }, [tournamentId])

  useEffect(() => {
    snapshotRef.current = null
    setSnapshot(null)
    setInitialError(null)
    setStale(false)
    setLastSyncedAt(null)
    setLoading(true)

    let timer: ReturnType<typeof setInterval> | null = null
    const stopPolling = () => {
      if (timer !== null) clearInterval(timer)
      timer = null
    }
    const startPolling = () => {
      stopPolling()
      if (!document.hidden) timer = setInterval(() => { void refresh() }, POLL_INTERVAL_MS)
    }
    const onVisibilityChange = () => {
      if (document.hidden) {
        stopPolling()
        return
      }
      void refresh()
      startPolling()
    }

    void refresh()
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [refresh])

  const visibleTables = useMemo(
    () => selectDashboardTables(snapshot?.dashboard.tables ?? []),
    [snapshot?.dashboard.tables],
  )

  if (loading && !snapshot) {
    return <section className="admin-dashboard admin-dashboard--empty"><h1>正在加载赛事总览…</h1></section>
  }

  if (!snapshot) {
    return (
      <section className="admin-dashboard admin-dashboard--empty" role="alert">
        <span className="admin-dashboard-kicker">赛事总览</span>
        <h1>现场数据加载失败</h1>
        <p>{initialError || '暂时无法读取赛事现场状态。'}</p>
        <button className="btn primary" onClick={() => void refresh()} type="button">重试</button>
      </section>
    )
  }

  const { dashboard, preflight, players, entries, groups, organization, venue } = snapshot
  const tournament = dashboard.tournament
  const percent = dashboard.stats.total === 0
    ? 0
    : Math.round((dashboard.stats.finished / dashboard.stats.total) * 100)
  const tournamentQuery = `?tid=${tournamentId}`

  return (
    <div className="admin-dashboard">
      <header className="admin-dashboard-heading">
        <div>
          <span className="admin-dashboard-kicker">赛事总览 · FIELD OVERVIEW</span>
          <h1>{tournament.name}</h1>
          <p className="admin-dashboard-meta">
            <span>{tournament.date}</span>
            <span>{eventTypeLabel(tournament.event_type)}</span>
            <span>{tournamentFormatLabel(tournament.format_code)}</span>
            {organization && <span>{organization.name}</span>}
            {venue && <span>{venue.name}</span>}
          </p>
        </div>
        <div className="admin-dashboard-statuses">
          <span className={`admin-mode-chip ${tournament.operation_mode.toLowerCase()}`}>
            {tournament.operation_mode === 'LIVE' ? '正式赛事' : '演示赛事'}
          </span>
          <span className="admin-stage-chip">{tournamentStageLabel(tournament.stage, tournament.format_code)}</span>
        </div>
      </header>

      <div className={`admin-sync-state${stale ? ' is-stale' : ''}`} role={stale ? 'alert' : 'status'}>
        <span>{stale ? '实时数据暂时无法更新，当前显示可能不是最新状态。' : '现场数据每 10 秒自动同步。'}</span>
        <small>最近同步：{lastSyncedAt ? lastSyncedAt.toLocaleTimeString('zh-CN', { hour12: false }) : '尚未同步'}</small>
      </div>

      <section className="admin-progress-panel" aria-label="比赛进度">
        <div className="admin-progress-copy">
          <span>比赛进度</span>
          <strong>{dashboard.stats.finished}<small> / {dashboard.stats.total}</small></strong>
          <p>进行中 {dashboard.stats.playing} 场 · 待比赛 {dashboard.stats.waiting} 场</p>
        </div>
        <div className="admin-progress-track" aria-label={`已完成 ${percent}%`}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <b>{percent}%</b>
      </section>

      <section className="admin-overview-grid">
        <article className="admin-overview-card">
          <header><span>参赛概况</span><small>ROSTER</small></header>
          <dl>
            <div><dt>运动员</dt><dd>{players.length}</dd></div>
            <div><dt>Entry</dt><dd>{entries.length}</dd></div>
            <div><dt>小组</dt><dd>{groups.groups.length}</dd></div>
          </dl>
        </article>

        <article className={`admin-overview-card admin-preflight-summary ${preflight.blocker_count > 0 ? 'has-blockers' : ''}`}>
          <header><span>赛前检查</span><small>PREFLIGHT</small></header>
          <div className="admin-preflight-counts">
            <span><b>{preflight.blocker_count}</b> 阻断</span>
            <span><b>{preflight.warning_count}</b> 注意</span>
            <span><b>{preflight.ready_count}</b> 通过</span>
          </div>
          {preflight.blocker_count > 0 && <p>有 {preflight.blocker_count} 项需要处理，正式开赛前建议处理阻断项。</p>}
          <Link to={`/preflight${tournamentQuery}`}>查看完整检查</Link>
        </article>
      </section>

      <section className="admin-overview-card admin-key-actions">
        <header><span>关键操作</span><small>QUICK ACCESS</small></header>
        <div className="admin-action-links">
          <Link to={`/preflight${tournamentQuery}`}>赛前检查</Link>
          <Link to={`/console${tournamentQuery}`}>比赛控制</Link>
          <Link to={`/orderbook${tournamentQuery}`}>赛程与秩序</Link>
          <Link to={`/rankings${tournamentQuery}`}>排名</Link>
          <Link to={`/knockout${tournamentQuery}`}>淘汰赛</Link>
        </div>
      </section>

      <section className="admin-overview-card admin-table-summary">
        <header>
          <span>现场球台</span>
          <small>TABLE STATUS · {dashboard.tables.filter((table) => table.status === 'OCCUPIED').length} 使用中</small>
        </header>
        {visibleTables.length === 0 ? (
          <p className="admin-dashboard-muted">当前没有可展示的球台状态。</p>
        ) : (
          <div className="admin-table-grid">
            {visibleTables.map((table) => (
              <article className={table.status === 'OCCUPIED' ? 'is-occupied' : 'is-free'} key={table.id}>
                <div><strong>{table.name}</strong><span>{table.status === 'OCCUPIED' ? '使用中' : '空闲'}</span></div>
                {table.status === 'OCCUPIED' && table.match ? (
                  <p>{matchSide(table.match.entry_a_name)} <i>VS</i> {matchSide(table.match.entry_b_name)}</p>
                ) : table.status === 'FREE' && table.recommended_match_id ? (
                  <p>推荐 M{table.recommended_match_id}</p>
                ) : (
                  <p>等待比赛安排</p>
                )}
              </article>
            ))}
          </div>
        )}
        <Link className="admin-section-link" to={`/console${tournamentQuery}`}>进入比赛控制</Link>
      </section>

      <section className="admin-public-shortcuts">
        <span>Public 快捷入口</span>
        <div>
          <a href={`/public/t/${tournamentId}/live`} target="_blank" rel="noreferrer">公开实况</a>
          <a href={`/public/t/${tournamentId}/schedule`} target="_blank" rel="noreferrer">公开赛程</a>
        </div>
      </section>
    </div>
  )
}
