import { Tile, TileEmpty } from './Tile'

/** Tile 8 — Nudge inbox chip (DESIGN §3.8): pending/snoozed count. The
 * inbox itself arrives with the coach (Phase 5/6); until then the chip
 * reads honestly quiet. */
export function NudgeTile({ count }: { count?: number }) {
  if (count === undefined) return null
  return (
    <Tile title="Nudges" ariaLabel={`Nudges: ${count} waiting`}>
      {count === 0 ? (
        <TileEmpty>Nothing waiting. The coach moves in during a later phase.</TileEmpty>
      ) : (
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full bg-clay px-2 font-mono text-sm font-medium text-paper">
            {count}
          </span>
          <span className="text-sm text-ink-mid">waiting for you</span>
        </div>
      )}
    </Tile>
  )
}
