/** Shared tiny-chart SVG primitive (docs/ARCHITECTURE.md §1, DESIGN §1) —
 * data-viz colours come ONLY from the viz ramp tokens. Nulls (sparse days)
 * break the line rather than reading as zero. Every sparkline carries a
 * text equivalent via aria-label (DESIGN §6); the drawing itself is
 * presentation-only. */

const W = 96
const H = 28
const PAD = 2

export function Sparkline({
  values,
  color = 'var(--color-viz-1)',
  label,
  className = '',
}: {
  values: (number | null)[]
  color?: string
  label: string
  className?: string
}) {
  const present = values.filter((v): v is number => v != null)
  if (present.length === 0) {
    return (
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}: no data yet`} className={className}>
        <line x1={PAD} y1={H / 2} x2={W - PAD} y2={H / 2} stroke="var(--color-line)" strokeWidth="1" strokeDasharray="2 3" />
      </svg>
    )
  }

  const min = Math.min(...present, 0)
  const max = Math.max(...present)
  const span = max - min || 1
  const stepX = (W - PAD * 2) / Math.max(values.length - 1, 1)
  const y = (v: number) => H - PAD - ((v - min) / span) * (H - PAD * 2)
  const x = (i: number) => PAD + i * stepX

  // Split into contiguous runs so nulls break the line instead of bridging.
  const runs: { i: number; v: number }[][] = []
  let current: { i: number; v: number }[] = []
  values.forEach((v, i) => {
    if (v == null) {
      if (current.length) runs.push(current)
      current = []
    } else {
      current.push({ i, v })
    }
  })
  if (current.length) runs.push(current)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className={className}>
      {runs.map((run, r) =>
        run.length === 1 ? (
          <circle key={r} cx={x(run[0].i)} cy={y(run[0].v)} r="1.6" fill={color} />
        ) : (
          <polyline
            key={r}
            points={run.map((p) => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')}
            fill="none"
            stroke={color}
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ),
      )}
      {/* today's point, emphasised */}
      {values[values.length - 1] != null && (
        <circle cx={x(values.length - 1)} cy={y(values[values.length - 1] as number)} r="2.2" fill={color} />
      )}
    </svg>
  )
}
