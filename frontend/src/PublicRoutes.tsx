/**
 * Public 路由与 route adapter（D 轨 Day 2）。
 *
 * 设计原则：**route adapter > 小范围 prop 适配 > 重写页面**
 *
 * - 成熟页面（BigScreen / Schedule / Rankings / Knockout / ChampionJourney / Register）
 *   一律复用，不重写、不复制任何排名 / 淘汰赛推进 / 比分 / 阶段判断算法；
 * - `tid` 来自 URL path param（`useTidFromPath`），旧页面不再依赖 `localStorage.activeTournamentId`；
 * - `readOnly` 只屏蔽“写操作控件”（录分 / 补小分 / 人工裁定 / 生成签表 / Demo 模拟），
 *   只读展示逻辑仍由原页面承担。
 *
 * 本文件独立于 `App.tsx`，把 Public 路由接线收在一个地方，减少与 A/C 轨的冲突面。
 */

import { Navigate, Route, Routes } from 'react-router-dom'
import PublicLayout from './layouts/PublicLayout'
import { useTidFromPath } from './publicTournament'
import BigScreenPage from './pages/BigScreenPage'
import SchedulePage from './pages/SchedulePage'
import RankingsPage from './pages/RankingsPage'
import KnockoutPage from './pages/KnockoutPage'
import ChampionJourneyPage from './pages/ChampionJourneyPage'
import RegisterPage from './pages/RegisterPage'

/**
 * `/public/t/:tid`（index）与未知 Public 子路径都归到实况页。
 *
 * 用 `replace` 避免在浏览器历史里留下一条无内容的中间记录。
 */
function PublicIndexRedirect() {
  const tid = useTidFromPath()
  if (tid === null) return null
  return <Navigate replace to={`/public/t/${tid}/live`} />
}

/**
 * Public 报名页 adapter。
 *
 * ⚠️ legacy：当前复用 V0.2 `RegisterPage`，其行为是**直接创建正式 Player**
 * （`api.addPlayer`），与 V0.3 冻结的 `Registration(pending) → EVENT_ADMIN 确认入赛`
 * 契约不一致。
 *
 * 因此这里显式标记为 legacy 兼容页面，并明确告知用户当前行为：
 * - 不自行设计 Registration schema / API；
 * - 不把“直接 addPlayer”包装成 V0.3 最终报名方案；
 * - 不使用尚未存在的 `registration_enabled` 字段做显隐或校验；
 * - 等 A 轨正式 Registration contract 落地后再切换本 adapter。
 */
function PublicRegisterAdapter() {
  const tid = useTidFromPath()
  return (
    <>
      <div className="pub-note" role="status">
        <strong>兼容模式（legacy）</strong>
        <span>
          当前报名入口仍是 V0.2 行为：提交后直接进入正式参赛名单，<b>没有</b>
          “待审核 → 管理员确认入赛”流程。V0.3 正式报名契约（Registration pending）由 A 轨提供后切换。
        </span>
      </div>
      <RegisterPage tid={tid ?? undefined} />
    </>
  )
}

export default function PublicRoutes() {
  // 单一来源：路由 path param。PublicLayout 与各页面共用同一个解析结果。
  const tid = useTidFromPath() ?? undefined

  return (
    <Routes>
      <Route element={<PublicLayout />} path="/public/t/:tid">
        <Route element={<PublicIndexRedirect />} index />
        <Route element={<BigScreenPage tid={tid} />} path="live" />
        <Route element={<SchedulePage tid={tid} />} path="schedule" />
        <Route element={<RankingsPage readOnly tid={tid} />} path="rankings" />
        <Route element={<KnockoutPage readOnly tid={tid} />} path="bracket" />
        <Route element={<ChampionJourneyPage tid={tid} />} path="champion" />
        <Route element={<PublicRegisterAdapter />} path="register" />
        {/* 未知 Public 子路径 -> 回到该赛事的实况页，而不是白屏 */}
        <Route element={<PublicIndexRedirect />} path="*" />
      </Route>
    </Routes>
  )
}
