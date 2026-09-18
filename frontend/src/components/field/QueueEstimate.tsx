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
  // A2 timing 契约的 UTC 值可为 `YYYY-MM-DD HH:MM:SS`（无 Z）。
  // 浏览器会把该形式当成本地时间，故先转换为空格替换为 T、并显式标记 UTC 的 ISO 8601。
  const normalizedUtc = estimatedStartAt && !/(?:Z|[+-]\d{2}:\d{2})$/i.test(estimatedStartAt)
    ? `${estimatedStartAt.replace(' ', 'T')}Z`
    : estimatedStartAt?.replace(' ', 'T')
  const date = normalizedUtc ? new Date(normalizedUtc) : null
  if (estimatedStartAt && (!date || Number.isNaN(date.getTime()))) {
    return <p className="queue-estimate muted">预计上场：{unavailableReason || '预测数据暂未提供'}</p>
  }
  const time = date ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null
  return <p className="queue-estimate">预计上场：前方 {ahead ?? '—'} 场{time ? ` · 约 ${time}` : ''}<small>会随现场进度变化</small></p>
}
