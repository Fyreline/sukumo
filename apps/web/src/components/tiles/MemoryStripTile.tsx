import type { MemoryDay } from '../../dashboard'
import { Tile } from './Tile'

/** Tile 6 — Memory strip (DESIGN §3.6): the last 7 day-dots on the liquid
 * thread, sized by event_count. Sparse until the memory engine lands
 * (Phase 7) — the thread renders anyway. Day taps route to the journal
 * when it exists; until then the dots are display-only. */

const DOT_SIZES = ['h-2 w-2', 'h-2.5 w-2.5', 'h-3.5 w-3.5', 'h-4.5 w-4.5']

function dotSize(count: number): string {
  if (count === 0) return DOT_SIZES[0]
  if (count <= 2) return DOT_SIZES[1]
  if (count <= 5) return DOT_SIZES[2]
  return DOT_SIZES[3]
}

export function MemoryStripTile({ strip }: { strip?: MemoryDay[] }) {
  if (!strip) return null
  const total = strip.reduce((n, d) => n + d.event_count, 0)
  return (
    <Tile
      title="Memory"
      ariaLabel={`Memory, ${total} moment${total === 1 ? '' : 's'} recorded in the last 7 days`}
    >
      <div className="relative flex items-center justify-between px-1 py-3">
        {/* the liquid thread (DESIGN §1: liquid is the connector) */}
        <div className="absolute inset-x-1 top-1/2 h-0.5 -translate-y-1/2 rounded bg-liquid" aria-hidden />
        {strip.map((day) => {
          const label = new Date(`${day.date}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short' })
          return (
            <div key={day.date} className="relative flex flex-col items-center gap-1.5">
              <span
                title={`${day.date}: ${day.event_count} event${day.event_count === 1 ? '' : 's'}`}
                className={`rounded-full ${dotSize(day.event_count)} ${
                  day.event_count > 0 ? 'bg-fig' : 'border border-line-strong bg-paper'
                }`}
                aria-hidden
              />
              <span className="absolute top-full pt-1 text-[10px] text-ink-soft">{label[0]}</span>
            </div>
          )
        })}
      </div>
      <p className="mt-4 text-xs text-ink-soft">
        {total === 0 ? 'The journal starts filling in a later phase — the thread is ready.' : `${total} moment${total === 1 ? '' : 's'} this week.`}
      </p>
    </Tile>
  )
}
