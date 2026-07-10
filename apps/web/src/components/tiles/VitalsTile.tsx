import type { Vitals } from '../../dashboard'
import { Sparkline } from '../Sparkline'
import { Tile, TileEmpty } from './Tile'

/** Tile 2 — Vitals (DESIGN §3.2): four stat chips, each with its 14-day
 * sparkline. Neutral display only — no targets, no colour judgement
 * (COACH §0: the coach never interprets health data). */

function StatChip({
  label,
  value,
  unit,
  series,
  color,
}: {
  label: string
  value: string
  unit?: string
  series: (number | null)[]
  color: string
}) {
  return (
    <div className="rounded-md border border-line bg-paper p-3">
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-soft">{label}</div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className="font-mono text-lg leading-none text-ink">
          {value}
          {unit && <span className="ml-0.5 text-[11px] text-ink-soft">{unit}</span>}
        </div>
        <Sparkline values={series} color={color} label={`${label}, last 14 days`} className="h-7 w-24 shrink-0" />
      </div>
    </div>
  )
}

const fmt = (v: number | null, digits = 0): string =>
  v == null ? '—' : v.toLocaleString('en-GB', { maximumFractionDigits: digits, minimumFractionDigits: 0 })

export function VitalsTile({ vitals }: { vitals?: Vitals }) {
  if (!vitals) return null
  const noData =
    vitals.steps.series.every((v) => v == null) &&
    vitals.sleep_hours.series.every((v) => v == null) &&
    vitals.active_kcal.series.every((v) => v == null) &&
    vitals.workouts.series.every((v) => v === 0)

  return (
    <Tile title="Vitals" ariaLabel="Vitals — steps, sleep, energy and workouts">
      {noData ? (
        <TileEmpty>Nothing from the phone yet — vitals appear once the health sync has run.</TileEmpty>
      ) : (
        <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-2 lg:grid-cols-4">
          <StatChip label="Steps" value={fmt(vitals.steps.today)} series={vitals.steps.series} color="var(--color-viz-1)" />
          <StatChip
            label="Sleep"
            value={fmt(vitals.sleep_hours.today, 1)}
            unit="h"
            series={vitals.sleep_hours.series}
            color="var(--color-viz-2)"
          />
          <StatChip
            label="Active"
            value={fmt(vitals.active_kcal.today)}
            unit="kcal"
            series={vitals.active_kcal.series}
            color="var(--color-viz-3)"
          />
          <StatChip
            label="Workouts"
            value={String(vitals.workouts.this_week)}
            unit="this wk"
            series={vitals.workouts.series}
            color="var(--color-viz-4)"
          />
        </div>
      )}
    </Tile>
  )
}
