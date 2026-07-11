import type { OccasionEntry } from '../../dashboard'
import { Tile, TileEmpty } from './Tile'

/** Tile 5 — People (DESIGN §3.5): occasions inside 45 days with the
 * gift-status pill (none / ideas / bought ✓ in olive). Tap → PeoplePage. */

function GiftPill({ status }: { status: OccasionEntry['gift_status'] }) {
  if (status === 'bought') {
    return (
      <span className="rounded-full bg-olive/15 px-2 py-0.5 text-[11px] font-medium text-olive">gift ✓</span>
    )
  }
  if (status === 'ideas') {
    return (
      <span className="rounded-full bg-sky/15 px-2 py-0.5 text-[11px] font-medium text-sky">ideas</span>
    )
  }
  return (
    <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-soft">no gift yet</span>
  )
}

function daysLabel(days: number): string {
  if (days === 0) return 'today'
  if (days === 1) return 'tomorrow'
  return `in ${days} days`
}

export function PeopleTile({
  occasions,
  onOpenPeople,
}: {
  occasions?: OccasionEntry[]
  onOpenPeople: () => void
}) {
  if (!occasions) return null
  return (
    <Tile
      title="People"
      aside={
        <button type="button" onClick={onOpenPeople} className="min-h-6 text-[11px] font-medium text-sky underline-offset-2 hover:underline">
          open
        </button>
      }
    >
      {occasions.length === 0 ? (
        <TileEmpty>Nothing on the horizon for the next 45 days.</TileEmpty>
      ) : (
        <ul className="space-y-1.5">
          {occasions.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                onClick={onOpenPeople}
                aria-label={
                  o.kind === 'birthday'
                    ? `${o.title}, ${daysLabel(o.days_to_go)}, gift status ${o.gift_status}`
                    : `${o.title}, ${daysLabel(o.days_to_go)}`
                }
                className="flex min-h-11 w-full items-center justify-between gap-3 rounded-md border border-line bg-paper px-3 py-2 text-left transition hover:border-line-strong"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {o.kind === 'birthday' && <span className="text-fig" aria-hidden>♥</span>}
                    <span className="truncate text-sm font-medium text-ink">{o.title}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-ink-soft">
                    {daysLabel(o.days_to_go)} · {new Date(`${o.date}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
                  </div>
                </div>
                {/* Gift status only makes sense for birthdays — a "no gift
                    yet" pill on e.g. a review occasion reads as nonsense. */}
                {o.kind === 'birthday' && <GiftPill status={o.gift_status} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  )
}
