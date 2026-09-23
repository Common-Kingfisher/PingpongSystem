import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { Tournament } from '../api'
import './TournamentSettingsPage.css'

const tabs = ['基本信息', '赛制与规则', '报名设置', '公开与展示', '高级操作'] as const
type SettingsTab = typeof tabs[number]

const eventNames: Record<Tournament['event_type'], string> = {
  SINGLES: '单打', DOUBLES: '双打', TEAM: '团体',
}
const bronzeNames: Record<Tournament['bronze_mode'], string> = {
  BRONZE_MATCH: '举行季军赛', JOINT_BRONZE: '并列季军',
}
const placementNames: Record<Tournament['placement_mode'], string> = {
  OFF: '不举行名次赛', COMPLETE: '完整名次赛', TIERED: '分层名次赛',
}

export interface TournamentSettingsPageProps {
  tournament?: Tournament | null
}

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="settings-fact"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>
}

type SaveState = 'idle' | 'saving' | 'error'

/**
 * 「报名设置」= 管理端**唯一**的赛事级报名开关控制面（D 轨 Day5D + PR #58 review 返工）。
 *
 * ## 为什么这一块必须存在
 *
 * PR #58 review 的唯一 P1：Public 端已经能读 `TournamentOut.registration_enabled`，
 * 但 EVENT_ADMIN 没有任何 UI 能真正开启 / 关闭报名 —— 只能手工调
 * `PUT /api/tournaments/{tid}/registration`，于是 Public 永远停在「报名已关闭」。
 * 本组件把这条写入通道接上正式契约。
 *
 * ## 边界（刻意很窄）
 *
 * - 只做**开关**：报名列表 / 确认 / 拒绝 / 批量操作属于 C5，不在这里实现；
 * - 状态**只认服务端**：`PUT` 的响应 `TournamentOut.registration_enabled` 是唯一事实源，
 *   不做「点击后先本地置位」的乐观更新（失败会留下假状态）；
 * - 失败时保持原状态并展示服务端可读 message（401 / 403 / 404 / 409 的语义由后端决定，
 *   前端不按 status code 自己复制业务判断）；
 * - 不新增页面 / 路由 / API：`api.setRegistrationEnabled()` 就是既有的
 *   `PUT /api/tournaments/{tid}/registration`。
 */
function RegistrationSettings({ tournament }: { tournament: Tournament | null }) {
  const tid = tournament?.id ?? null
  const [enabled, setEnabled] = useState(tournament?.registration_enabled ?? false)
  const [state, setState] = useState<SaveState>('idle')
  const [errorText, setErrorText] = useState<string | null>(null)
  /** 同步锁：同一事件循环内的连续点击只放行一次（与 Public 报名页 / MobileScorePage 同一模式）。 */
  const savingRef = useRef(false)

  // 赛事切换（或父级重新拉取赛事）时同步本地状态：
  // 旧赛事 A 的报名状态绝不能残留到赛事 B。
  useEffect(() => {
    setEnabled(tournament?.registration_enabled ?? false)
    setState('idle')
    setErrorText(null)
    savingRef.current = false
  }, [tid, tournament?.registration_enabled])

  const apply = useCallback(
    async (next: boolean) => {
      if (tid === null || savingRef.current) return
      savingRef.current = true
      setState('saving')
      setErrorText(null)
      try {
        const updated = await api.setRegistrationEnabled(tid, { enabled: next })
        setEnabled(updated.registration_enabled)
        setState('idle')
      } catch (err) {
        // 失败：保持原状态，只展示服务端统一解析出的可读 message
        setState('error')
        setErrorText(err instanceof ApiError ? err.message : '报名设置保存失败，请稍后重试')
      } finally {
        savingRef.current = false
      }
    },
    [tid],
  )

  if (tournament === null) {
    return (
      <section className="settings-registration">
        <div className="settings-registration-status">
          <span className="settings-status-dot" aria-hidden="true" />
          <div>
            <small>公开报名</small>
            <strong>等待赛事数据</strong>
          </div>
        </div>
        <p className="settings-registration-note">
          选择一场赛事后才能开启或关闭公开报名。
        </p>
      </section>
    )
  }

  const saving = state === 'saving'

  return (
    <section className="settings-registration">
      <div className={enabled ? 'settings-registration-status is-open' : 'settings-registration-status'}>
        <span className="settings-status-dot" aria-hidden="true" />
        <div>
          <small>公开报名</small>
          <strong>{enabled ? '报名中' : '已关闭'}</strong>
        </div>
      </div>

      <p className="settings-registration-note">
        {enabled
          ? '选手可以通过公开报名页面提交报名。报名记录将进入待确认列表。'
          : '选手当前无法通过公开报名页面提交报名。'}
      </p>

      <div className="settings-registration-actions">
        <button
          className={enabled ? 'settings-toggle is-close' : 'settings-toggle is-open'}
          disabled={saving}
          onClick={() => apply(!enabled)}
          type="button"
        >
          {saving ? (enabled ? '正在关闭…' : '正在开启…') : enabled ? '关闭报名' : '开启报名'}
        </button>
        <span className="settings-toggle-hint">
          {enabled
            ? '关闭后公开报名页立即变为只读，选手无法再提交报名。'
            : '报名开启后，公开报名页面将允许选手提交报名申请。提交后不会直接成为正式参赛选手，仍需赛事管理员确认。'}
        </span>
      </div>

      {errorText && (
        <p className="settings-registration-error" role="alert">{errorText}</p>
      )}
    </section>
  )
}

export default function TournamentSettingsPage({ tournament = null }: TournamentSettingsPageProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('赛制与规则')

  return <div className="tournament-settings">
    <header className="settings-heading">
      <div><span>TOURNAMENT SETTINGS</span><h1>赛事设置</h1><p>核对当前规则。编辑能力将在后端规则契约就绪后开放。</p></div>
      <div className="settings-heading-mark" aria-hidden="true">TT<span>规则档案</span></div>
    </header>
    <div className="settings-tabs" role="tablist" aria-label="赛事设置分类">
      {tabs.map((tab) => <button
        id={`settings-tab-${tabs.indexOf(tab)}`}
        key={tab}
        type="button"
        role="tab"
        aria-selected={activeTab === tab}
        aria-controls="settings-panel"
        className={activeTab === tab ? 'is-active' : ''}
        onClick={() => setActiveTab(tab)}
      >{tab}</button>)}
    </div>

    <div id="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${tabs.indexOf(activeTab)}`}>
      {activeTab === '赛制与规则' ? <>
        <div className="settings-notice">当前只读 · 等待规则更新接口。所有规则以服务端保存的数据为准。</div>
        <div className="settings-rule-grid">
          <section className="settings-section">
            <header><span>01 / STRUCTURE</span><h2>赛事结构</h2></header>
            <div className="settings-facts">
              <Fact label="赛事类型" value={tournament ? eventNames[tournament.event_type] : '等待赛事数据'} />
              <Fact label="小组数量" value={tournament ? `${tournament.group_count} 组` : '等待赛事数据'} />
              <Fact label="当前赛制" value="等待赛制接口" note="当前版本由系统规则决定；不从赛事阶段推测赛制。" />
            </div>
          </section>
          <section className="settings-section">
            <header><span>02 / SCORE</span><h2>比分规则</h2></header>
            <div className="settings-facts">
              <Fact label="比赛局制" value={tournament ? `先胜 ${tournament.games_to_win} 局` : '等待赛事数据'} />
              <Fact label="每局目标分" value={tournament ? `${tournament.points_to_win} 分` : '等待赛事数据'} />
            </div>
          </section>
          <section className="settings-section">
            <header><span>03 / ADVANCEMENT</span><h2>晋级与名次</h2></header>
            <div className="settings-facts">
              <Fact label="每组晋级" value={tournament ? `前 ${tournament.qualify_per_group} 名` : '等待赛事数据'} />
              <Fact label="季军规则" value={tournament ? bronzeNames[tournament.bronze_mode] : '等待赛事数据'} />
              <Fact label="名次赛" value={tournament ? placementNames[tournament.placement_mode] : '等待赛事数据'} />
            </div>
          </section>
          <section className="settings-section settings-section--draw">
            <header><span>04 / DRAW</span><h2>抽签规则</h2></header>
            <p>种子保护、同单位规避：等待规则接口。正式抽签由后端权威执行。</p>
            <div className="settings-priority">赛制合法性 <b>›</b> 种子保护 <b>›</b> 同单位／同队伍规避 <b>›</b> 均衡 <b>›</b> 随机性</div>
          </section>
        </div>
        <footer className="settings-actions"><span>等待规则更新接口</span><button disabled type="button">取消修改</button><button className="primary" disabled type="button">保存设置</button></footer>
      </> : activeTab === '报名设置' ? <RegistrationSettings tournament={tournament} />
        : <section className="settings-pending"><h2>{activeTab}</h2><p>此分类已预留页面位置；等待对应的后端数据与权限契约后接入，不显示模拟设置。</p></section>}
    </div>
  </div>
}
