import { ageLabel, type Goal } from '../../dashboard'
import { Tile, TileEmpty, StaleChip } from './Tile'

/** Tile 4 — House goal (DESIGN §3.4): Kakeibo pct ring + pace label +
 * "as of" age. Numbers are visible here (the authed app, not a push —
 * ARCHITECTURE §5.2 only gates outbound notifications). */

const R = 34
const CIRC = 2 * Math.PI * R

function GoalRing({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <svg viewBox="0 0 84 84" role="img" aria-label={`House goal ${clamped.toFixed(1)} percent saved`} className="h-24 w-24">
      <circle cx="42" cy="42" r={R} fill="none" stroke="var(--color-paper-deep)" strokeWidth="7" />
      <circle
        cx="42"
        cy="42"
        r={R}
        fill="none"
        stroke="var(--color-viz-1)"
        strokeWidth="7"
        strokeLinecap="round"
        strokeDasharray={CIRC}
        strokeDashoffset={CIRC * (1 - clamped / 100)}
        transform="rotate(-90 42 42)"
      />
      <text
        x="42"
        y="46"
        textAnchor="middle"
        className="font-mono"
        fontSize="16"
        fill="var(--color-ink)"
      >
        {clamped.toFixed(0)}%
      </text>
    </svg>
  )
}

const PACE_LABELS: Record<string, string> = {
  on_pace: 'on pace',
  ahead: 'ahead of pace',
  behind: 'a touch behind',
  // Kakeibo reports no_trend while the pot is too young to judge — say so in
  // words rather than leaking the raw enum onto the tile.
  no_trend: 'early days',
}

const pounds = (pence: number | null): string =>
  pence == null ? '—' : `£${(pence / 100).toLocaleString('en-GB', { maximumFractionDigits: 0 })}`

export function GoalTile({ goal }: { goal?: Goal | null }) {
  if (goal === undefined) return null
  const stale = goal != null && goal.age_seconds > 6 * 3600

  return (
    <Tile
      title="House goal"
      dimmed={stale}
      aside={goal ? <span>{stale && <StaleChip />} as of {goal.as_of ?? '—'} · {ageLabel(goal.age_seconds)}</span> : undefined}
    >
      {goal == null || goal.pct == null ? (
        <TileEmpty>Kakeibo isn’t connected yet — the ring fills in once it is.</TileEmpty>
      ) : (
        <div className="flex items-center gap-4">
          <GoalRing pct={goal.pct} />
          <div>
            <div className="font-mono text-lg text-ink">
              {pounds(goal.saved_pence)} <span className="text-sm text-ink-soft">of {pounds(goal.goal_pence)}</span>
            </div>
            <div className="mt-1 text-sm text-ink-mid">
              {PACE_LABELS[goal.pace_status ?? ''] ?? goal.pace_status ?? '—'}
            </div>
          </div>
        </div>
      )}
    </Tile>
  )
}
