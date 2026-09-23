/**
 * Public 端布局（D 轨 Day 2，Day4D 接线赛制）。
 *
 * 与 C 轨 AdminLayout 完全分离：
 *
 * - AdminLayout  = 桌面管理控制台，固定侧栏 + 工作区，受保护（A/C 轨）
 * - PublicLayout = 公开只读视图，顶部紧凑 Header + 横向导航，免登录（D 轨）
 *
 * 关键约束：
 *
 * 1. 赛事 id 只来自 path param（`/public/t/:tid/...`），不读 localStorage；
 * 2. 不出现任何录分 / 删除 / 改规则 / 抽签 / 管理员操作入口；
 * 3. 手机优先：360 / 375 / 390 / 430px 无横向溢出，触摸目标足够大；
 * 4. 导航可见性由**后端返回的 `Tournament.format_code`** 决定（唯一来源），
 *    不按 stage / 有没有 group / 有没有 knockout tree 反推赛制。
 *
 * ## 赛制 → 导航（Day4D）
 *
 * - `GROUP_KNOCKOUT`：实况 / 赛程 / 排名 / 签表 / 冠军 / 报名
 * - `ROUND_ROBIN`：实况 / 赛程 / 排名 / 报名（不显示签表与冠军）
 * - `SINGLE_ELIMINATION`：实况 / 赛程 / 签表 / 冠军 / 报名（不显示排名）
 * - `format_code == null`（legacy）：全部保留，数据驱动，不做推断
 *
 * 权限判断只在这一处（`getPublicCapabilities`），不下沉到各个页面重复实现。
 */

import { useCallback, useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { Tournament } from '../api'
import { useTidFromPath } from '../publicTournament'
import { getPublicCapabilities, getPublicStageLabel } from '../publicFormat'
import './PublicLayout.css'

/** 阶段徽标：文案由 `getPublicStageLabel` 按赛制给出，颜色 class 仍按 stage（保持既有配色） */
function StageBadge({
  stage,
  formatCode,
}: {
  stage: Tournament['stage'] | null | undefined
  formatCode: Tournament['format_code']
}) {
  if (!stage) return null
  const label = getPublicStageLabel(formatCode, stage)
  if (!label) return null
  return <span className={`pub-stage pub-stage--${stage.toLowerCase()}`}>{label}</span>
}

/**
 * Public 主导航项（顺序即信息架构：实况 → 赛程 → 排名 → 签表 → 冠军 → 报名）。
 *
 * `capability` 为 null 表示「不受赛制控制，始终显示」（实况 / 赛程 / 报名）。
 */
const NAV_ITEMS = [
  { key: 'live', label: '实况', capability: null },
  { key: 'schedule', label: '赛程', capability: null },
  { key: 'rankings', label: '排名', capability: 'showRankings' },
  { key: 'bracket', label: '签表', capability: 'showBracket' },
  { key: 'champion', label: '冠军', capability: 'showChampion' },
  { key: 'register', label: '报名', capability: null },
] as const

export default function PublicLayout() {
  // path param 是唯一来源；非法 tid 直接在这里拦下，不进任何业务请求。
  const tid = useTidFromPath()

  const [tournament, setTournament] = useState<Tournament | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'notfound' | 'error'>('loading')
  const [errorText, setErrorText] = useState<string | null>(null)

  useEffect(() => {
    if (tid === null) {
      setStatus('notfound')
      return
    }
    let active = true
    setStatus('loading')
    setTournament(null)
    setErrorText(null)
    api
      .getTournament(tid)
      .then((data) => {
        if (!active) return
        setTournament(data)
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (!active) return
        if (err instanceof ApiError && err.status === 404) {
          setStatus('notfound')
          setErrorText('该赛事不存在，可能已被删除。')
        } else {
          setStatus('error')
          setErrorText(err instanceof ApiError ? err.message : '无法连接服务器')
        }
      })
    return () => {
      active = false
    }
  }, [tid])

  // 只委托给浏览器打印，不复制任何业务逻辑。
  const handlePrint = useCallback(() => window.print(), [])

  if (status === 'notfound' || status === 'error') {
    return (
      <div className="pub-shell">
        <main className="pub-main">
          <div className="pub-message" role="alert">
            <h1>{status === 'notfound' ? '赛事不可用' : '加载失败'}</h1>
            <p>{errorText}</p>
            {status === 'notfound' && (
              <p className="pub-message-hint">
                请确认链接里的赛事编号是否正确，例如 <code>/public/t/12/live</code>。
              </p>
            )}
            <button className="pub-btn" onClick={() => window.location.reload()} type="button">
              重新加载
            </button>
          </div>
        </main>
      </div>
    )
  }

  // 赛制未知（尚未加载到赛事 / 历史赛事 null）时按“全部可见”渲染，避免导航闪烁或误隐藏。
  const capabilities = getPublicCapabilities(tournament?.format_code)
  const visibleNavItems = NAV_ITEMS.filter(
    (item) => item.capability === null || capabilities[item.capability],
  )

  return (
    <div className="pub-shell">
      <header className="pub-header">
        <div className="pub-header-inner">
          <div className="pub-brand">
            <span className="pub-brand-mark" aria-hidden="true">
              TT
            </span>
            <span className="pub-brand-text">
              <small>公开赛事页面</small>
              <strong>{tournament?.name ?? (status === 'loading' ? '正在加载…' : '赛事')}</strong>
            </span>
          </div>

          <div className="pub-header-meta">
            <StageBadge formatCode={tournament?.format_code} stage={tournament?.stage} />
            {tid !== null && <span className="pub-event-id">#{tid}</span>}
            {/* 公开页面只提供“回赛事首页”的普通导航，不暴露任何管理功能或管理导航 */}
            <Link className="pub-home-link" to={tid !== null ? `/?tid=${tid}` : '/'}>
              赛事首页
            </Link>
          </div>
        </div>
      </header>

      <nav className="pub-nav" aria-label="公开赛事导航">
        <div className="pub-nav-inner">
          {visibleNavItems.map((item) => (
            <NavLink
              className={({ isActive }) => `pub-nav-item${isActive ? ' is-active' : ''}`}
              key={item.key}
              // 无 tid 时保持当前页面不变，避免生成非法 Public URL
              to={tid !== null ? `/public/t/${tid}/${item.key}` : '#'}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="pub-main">
        <Outlet />
      </main>

      <footer className="pub-footer">
        <span>公开只读页面 · 比分与排名由赛事系统统一发布</span>
        <button className="pub-btn pub-btn--ghost" onClick={handlePrint} type="button">
          打印 / 导出
        </button>
      </footer>
    </div>
  )
}
