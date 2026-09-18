export default function QueueEstimate({ ahead, estimatedStartAt, unavailableReason }: {
  ahead?: number | null
  estimatedStartAt?: string | null
  unavailableReason?: string | null
}) {
  // FastAPI 可将“尚不可估算”的 optional 字段显式序列化为 null；
  // null 和缺字段都应走同一明确降级，不显示“前方 — 场”。
  if (ahead == null && estimatedStartAt == null) {
    return <p className="queue-estimate muted">预计上场：{unavailableReason || '预测数据暂未提供'}</p>
  }
  // A2 timing 契约的 UTC 值可为 `YYYY-MM-DD HH:MM:SS`（无 Z）。浏览器会把该形式
  // 当成本地时间；且 Date 会把 2 月 30 日等非法日期自动进位，故先严格校验再标准化。
  const matched = estimatedStartAt?.match(
    /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?(Z|[+-]\d{2}:\d{2})?$/i,
  )
  const values = matched?.slice(1, 7).map(Number)
  const [year, month, day, hour, minute, second] = values ?? []
  const validCalendar = year !== undefined && month !== undefined && day !== undefined
    && hour !== undefined && minute !== undefined && second !== undefined
    && month >= 1 && month <= 12 && day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate()
    && hour <= 23 && minute <= 59 && second <= 59
  const suffix = matched?.[7]
  const validOffset = !suffix || suffix.toUpperCase() === 'Z'
    || (Number(suffix.slice(1, 3)) <= 23 && Number(suffix.slice(4, 6)) <= 59)
  const normalizedUtc = validCalendar && validOffset && estimatedStartAt
    ? `${estimatedStartAt.replace(' ', 'T')}${suffix ? '' : 'Z'}`
    : null
  const date = normalizedUtc ? new Date(normalizedUtc) : null
  if (estimatedStartAt && (!date || Number.isNaN(date.getTime()))) {
    return <p className="queue-estimate muted">预计上场：{unavailableReason || '预测数据暂未提供'}</p>
  }
  const time = date ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null
  return <p className="queue-estimate">预计上场：前方 {ahead ?? '—'} 场{time ? ` · 约 ${time}` : ''}<small>会随现场进度变化</small></p>
}
