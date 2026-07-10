import type { AnniversaryHit, MemoryDay } from '../../dashboard'
import { Tile } from './Tile'

/** Tile 6 — Memory strip (DESIGN §3.6), live since Phase 7: the last 7
 * day-dots on the liquid thread, sized by event_count, each tap opening that
 * day in the journal. The fig anniversary line renders when the dashboard
 * payload carries a lookback hit ("one year since …" — MEMORY §4). */

const DOT_SIZES = ['h-2 w-2', 'h-2.5 w-2.5', 'h-3.5 w-3.5', 'h-4.5 w-4.5']

function dotSize(count: number): string {
  if (count === 0) return DOT_SIZES[0]
  if (count <= 2) return DOT_SIZES[1]
  if (count <= 5) return DOT_SIZES[2]
  return DOT_SIZES[3]
}

export function MemoryStripTile({
  strip,
  anniversary,
  onOpenDay,
}: {
  strip?: MemoryDay[]
  anniversary?: AnniversaryHit[] | null
  onOpenDay?: (date: string) => void
}) {
  if (!strip) return null
  const total = strip.reduce((n, d) => n + d.event_count, 0)
  const first = anniversary?.[0]
  return (
    <Tile
      title="Memory"
      ariaLabel={`Memory, ${total} moment${total === 1 ? '' : 's'} recorded in the last 7 days`}
    >
      <div className="relative flex items-center justify-between py-1">
        {/* the liquid thread (DESIGN §1: liquid is the connector) */}
        <div className="absolute inset-x-1 top-1/2 h-0.5 -translate-y-1/2 rounded bg-liquid" aria-hidden />
        {strip.map((day) => {
          const weekday = new Date(`${day.date}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short' })
          const summary = `${weekday} ${day.date}: ${day.event_count} event${
            day.event_count === 1 ? '' : 's'
          } — open in the journal`
          return (
            <button
              key={day.date}
              type="button"
              onClick={onOpenDay ? () => onOpenDay(day.date) : undefined}
              aria-label={summary}
              title={summary}
              className="relative flex h-12 flex-1 flex-col items-center justify-center gap-1.5"
            >
              <span
                className={`rounded-full ${dotSize(day.event_count)} ${
                  day.event_count > 0 ? 'bg-fig' : 'border border-line-strong bg-paper'
                }`}
                aria-hidden
              />
              <span className="text-[10px] text-ink-soft" aria-hidden>
                {weekday[0]}
              </span>
            </button>
          )
        })}
      </div>
      {first && (
        <p className="mt-3 text-xs text-fig">
          {first.years_ago === 1 ? 'One year' : `${first.years_ago} years`} since{' '}
          {new Date(`${first.local_date}T12:00:00`).toLocaleDateString('en-GB', {
            day: 'numeric',
            month: 'long',
            year: 'numeric',
          })}
          .
        </p>
      )}
      <p className="mt-3 text-xs text-ink-soft">
        {total === 0
          ? 'A quiet week so far — tap a day to open the journal.'
          : `${total} moment${total === 1 ? '' : 's'} this week — tap a day to open it.`}
      </p>
    </Tile>
  )
}
