import { ChangeEvent, FocusEvent } from 'react'

export default function TouchScoreInput({ label, value, max, onChange, side }: {
  label: string
  value: string
  max: number
  onChange: (value: string) => void
  side: 'a' | 'b'
}) {
  const numeric = Number(value) || 0
  const setBounded = (next: number) => onChange(String(Math.max(0, Math.min(max, next))))
  const selectDefaultZero = (event: FocusEvent<HTMLInputElement>) => {
    if (event.currentTarget.value === '0') event.currentTarget.select()
  }
  const update = (event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)

  return (
    <div className={`touch-score-control touch-score-${side}`}>
      <span>{label}</span>
      <div className="touch-score-actions">
        <button type="button" aria-label={`${label} 减一分`} onClick={() => setBounded(numeric - 1)} disabled={numeric <= 0}>−</button>
        <input aria-label={`${label}大比分`} type="number" min={0} max={max} value={value} onFocus={selectDefaultZero} onChange={update} />
        <button type="button" aria-label={`${label} 加一分`} onClick={() => setBounded(numeric + 1)} disabled={numeric >= max}>+</button>
      </div>
    </div>
  )
}
