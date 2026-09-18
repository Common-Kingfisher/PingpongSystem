import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, Dashboard, Match, Tournament } from '../api'

const resultLabel: Record<string, string> = {
  NORMAL: '正常完赛', FORFEIT: '主动弃权', WALKOVER: '直接晋级', NO_SHOW: '未到场', DISQUALIFIED: '取消资格',
}

export default function MatchPrintPage() {
  const [params] = useSearchParams()
  const tid = Number(params.get('tid'))
  const mid = Number(params.get('mid'))
  const [data, setData] = useState<{ tournament: Tournament; match: Match; dashboard: Dashboard } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    if (!Number.isInteger(tid) || !Number.isInteger(mid) || tid < 1 || mid < 1) {
      throw new Error('无效比赛参数')
    }
    const [tournament, matches, dashboard] = await Promise.all([api.getTournament(tid), api.listMatches(tid), api.getDashboard(tid)])
    const match = matches.find((item) => item.id === mid)
    if (!match) throw new Error('比赛不存在')
    setData({ tournament, match, dashboard })
  }, [tid, mid])
  useEffect(() => { load().catch(() => setError('无法加载本场比赛，请返回控制台后重试。')) }, [load])
  if (error) return <div className="card"><p className="status-error">{error}</p></div>
  if (!data) return <div className="card"><p className="muted">正在生成单场成绩单…</p></div>
  const { tournament, match, dashboard } = data
  const table = dashboard.tables.find((item) => item.id === match.table_id)?.name ?? (match.table_id ? `球台${match.table_id}` : '待安排')
  return <article className="match-print-sheet">
    <div className="print-toolbar"><Link to={`/console?tid=${tid}`}>返回控制台</Link><button onClick={() => window.print()}>打印 / 保存 PDF</button></div>
    <header><span>比赛成绩单</span><h1>{tournament.name}</h1><p>场次 M{match.id} · {match.stage === 'GROUP' ? '小组赛' : '淘汰赛'} · {table}</p></header>
    <section className="match-print-versus"><strong>{match.entry_a_name ?? '待定'}</strong><b>{match.player_a_score ?? '—'} : {match.player_b_score ?? '—'}</b><strong>{match.entry_b_name ?? '待定'}</strong></section>
    <table><thead><tr><th>局数</th><th>{match.entry_a_name ?? 'A 方'}</th><th>{match.entry_b_name ?? 'B 方'}</th></tr></thead><tbody>
      {match.games.length ? match.games.map((game) => <tr key={game.id}><td>第 {game.game_no} 局</td><td>{game.side_a_score}</td><td>{game.side_b_score}</td></tr>) : <tr><td colSpan={3}>未录入逐局小分</td></tr>}
    </tbody></table>
    <p>结果：{resultLabel[match.result_type ?? 'NORMAL'] ?? match.result_type}</p>
    <p>裁判备注：{match.result_note || '—'}</p>
    <footer>打印时间：{new Date().toLocaleString('zh-CN')} · 规则：{tournament.games_to_win} 局胜出 · 每局 {tournament.points_to_win} 分</footer>
  </article>
}
