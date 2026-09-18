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
  const time = estimatedStartAt ? new Date(estimatedStartAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null
  return <p className="queue-estimate">预计上场：前方 {ahead ?? '—'} 场{time ? ` · 约 ${time}` : ''}<small>会随现场进度变化</small></p>
}
