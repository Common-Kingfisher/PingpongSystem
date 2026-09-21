/**
 * 当前选中赛事（activeTournamentId）的持久化。
 *
 * 单一来源：localStorage key = pingpong_active_tournament_id。
 * 页面优先读取 URL 的 ?tid=，回退到这里；首页在选择/新建/删除时同步写这里。
 */

const KEY = 'pingpong_active_tournament_id'

export function parseTournamentId(raw: string | null | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null
  const id = Number(raw)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

export function getActiveTournamentId(): number | null {
  try {
    return parseTournamentId(localStorage.getItem(KEY))
  } catch {
    return null
  }
}

export function setActiveTournamentId(id: number | null): void {
  try {
    if (id === null) localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, String(id))
  } catch {
    // localStorage 不可用（隐私模式等）时静默降级
  }
}
