/**
 * Public 路由与 route adapter（D 轨 Day 2）。
 *
 * 设计原则：**route adapter > 小范围 prop 适配 > 重写页面**
 *
 * - 成熟页面（BigScreen / Schedule / Rankings / Knockout / ChampionJourney / Register）
 *   一律复用，不重写、不复制任何排名 / 淘汰赛推进 / 比分 / 阶段判断算法；
 * - `tid` 来自 URL path param，由**已匹配的 child route adapter** 读取后显式传给旧页面，
 *   旧页面在 Public 路由下不会退回 `localStorage.activeTournamentId`；
 * - `readOnly` 只屏蔽“写操作控件”（录分 / 补小分 / 人工裁定 / 生成签表 / Demo 模拟），
 *   只读展示逻辑仍由原页面承担。
 *
 * ## ⚠️ 关键约束：`useTidFromPath()` 的调用位置
 *
 * React Router 的 `useParams()` 只能读取**当前组件已经处于的**匹配 Route 及祖先 Route 的参数，
 * **看不到 descendant（后代）Route 的 param**。
 *
 * `/public/t/:tid` 是本文件内 `<Routes>` 声明的一条 Route，因此：
 *
 * - ❌ 在 `PublicRoutes()` 顶层调用 `useTidFromPath()` 会得到 `null`
 *   （此时组件在 `<Routes>` 之外，尚未匹配 `/public/t/:tid`）；
 *   早期实现正是这么写的，导致 `tid` 为 `undefined`、旧页面回退到 localStorage（PR #44 P1）。
 * - ✅ 只有作为该 Route 的 element，或其 child Route 的 element 渲染的组件
 *   （`PublicLayout`、下面的各个 adapter）才真正处于匹配上下文内。
 *
 * ## 非法 tid 语义
 *
 * 非法 / 缺失的 path param **不等于**“换一场赛事”：
 * adapter 一律不渲染 legacy 页面，避免它回退到 `?tid=` 或 localStorage 而显示另一场比赛。
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
 * 非法 / 缺失 `:tid` 时的轻量提示。
 *
 * 此时**不能**渲染任何 legacy 页面 —— 那会让它们回退到 `?tid=` / localStorage，
 * 变成“打开别人的赛事”。Public URL 必须自解释。
 */
function PublicInvalidTid() {
  return (
    <div className="pub-message" role="alert">
      <h1>链接不可用</h1>
      <p>这个公开地址里没有有效的赛事编号。</p>
      <p className="pub-message-hint">
        正确格式形如 <code>/public/t/12/live</code>，请向赛事组织者索取完整链接。
      </p>
    </div>
  )
}

/**
 * 在**已匹配**的 route context 内解析 `:tid`，仅当 tid 合法时才渲染页面。
 *
 * 这是 Public 页面唯一允许的 tid 传递路径：不会把 `undefined` 传给旧页面，
 * 因此旧页面的 `prop > ?tid= > localStorage` 兼容链在 Public 路由下永远不会生效。
 */
function PublicTidBoundary({ children }: { children: (tid: number) => JSX.Element }) {
  const tid = useTidFromPath()
  if (tid === null) return <PublicInvalidTid />
  return children(tid)
}

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

// ---------------------------------------------------------------- 各页面 adapter
//
// 每个 adapter 都是本文件内 `<Routes>` 的 child Route element，因此渲染时
// `/public/t/:tid` 已经匹配完成，`useTidFromPath()` 可以正确读到 `:tid`。

/** 实况（复用 BigScreenPage，含轮询） */
function PublicLiveAdapter() {
  return <PublicTidBoundary>{(tid) => <BigScreenPage tid={tid} />}</PublicTidBoundary>
}

/** 选手赛程（复用 SchedulePage） */
function PublicScheduleAdapter() {
  return <PublicTidBoundary>{(tid) => <SchedulePage tid={tid} />}</PublicTidBoundary>
}

/** 小组排名（复用 RankingsPage，只读） */
function PublicRankingsAdapter() {
  return <PublicTidBoundary>{(tid) => <RankingsPage readOnly tid={tid} />}</PublicTidBoundary>
}

/** 淘汰赛签表（复用 KnockoutPage，只读） */
function PublicBracketAdapter() {
  return <PublicTidBoundary>{(tid) => <KnockoutPage readOnly tid={tid} />}</PublicTidBoundary>
}

/** 冠军之路（复用 ChampionJourneyPage） */
function PublicChampionAdapter() {
  return <PublicTidBoundary>{(tid) => <ChampionJourneyPage tid={tid} />}</PublicTidBoundary>
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
  return (
    <PublicTidBoundary>
      {(tid) => (
        <>
          <div className="pub-note" role="status">
            <strong>兼容模式（legacy）</strong>
            <span>
              当前报名入口仍是 V0.2 行为：提交后直接进入正式参赛名单，<b>没有</b>
              “待审核 → 管理员确认入赛”流程。V0.3 正式报名契约（Registration pending）由 A 轨提供后切换。
            </span>
          </div>
          <RegisterPage tid={tid} />
        </>
      )}
    </PublicTidBoundary>
  )
}

/**
 * Public 路由表。
 *
 * 注意：本组件**不读取** `:tid` —— `/public/t/:tid` 是它下面声明的 descendant Route，
 * 在此处调用 `useParams()` 拿不到该 param。tid 一律由上面的 adapter 在匹配后解析。
 */
export default function PublicRoutes() {
  return (
    <Routes>
      <Route element={<PublicLayout />} path="/public/t/:tid">
        <Route element={<PublicIndexRedirect />} index />
        <Route element={<PublicLiveAdapter />} path="live" />
        <Route element={<PublicScheduleAdapter />} path="schedule" />
        <Route element={<PublicRankingsAdapter />} path="rankings" />
        <Route element={<PublicBracketAdapter />} path="bracket" />
        <Route element={<PublicChampionAdapter />} path="champion" />
        <Route element={<PublicRegisterAdapter />} path="register" />
        {/* 未知 Public 子路径 -> 回到该赛事的实况页，而不是白屏 */}
        <Route element={<PublicIndexRedirect />} path="*" />
      </Route>
    </Routes>
  )
}
