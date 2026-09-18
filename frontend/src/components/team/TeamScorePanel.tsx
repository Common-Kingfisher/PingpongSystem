/**
 * 团体赛 UI 边界。实际盘次、可选阵容和结束状态必须由后端契约提供；
 * 当前不承载任何排阵或胜负规则，避免前端抢跑固化规则。
 */
export default function TeamScorePanel() {
  return (
    <section className="team-score-panel" aria-label="团体赛比分面板">
      <h3>团体比分面板</h3>
      <p className="muted">等待后端提供合法阵容、盘次顺序、目标胜场与结束状态后启用。</p>
    </section>
  )
}
