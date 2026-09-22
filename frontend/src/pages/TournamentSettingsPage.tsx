import { useState } from 'react'
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
      </> : <section className="settings-pending"><h2>{activeTab}</h2><p>此分类已预留页面位置；等待对应的后端数据与权限契约后接入，不显示模拟设置。</p></section>}
    </div>
  </div>
}
