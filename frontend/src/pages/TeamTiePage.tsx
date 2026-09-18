import { Link } from 'react-router-dom'
import TeamScorePanel from '../components/team/TeamScorePanel'

export default function TeamTiePage() {
  return <div className="page"><div className="card"><h2>团体赛</h2><p className="status-warn">团体赛后端核心与 Reviewer 排阵规则尚未冻结，入口暂不开放。</p><p className="muted">启用后这里将显示队伍名单确认、Team A vs Team B、合法阵容、盘次顺序和当前团体总比分。</p><TeamScorePanel /><Link className="btn" to="/">返回赛事首页</Link></div></div>
}
