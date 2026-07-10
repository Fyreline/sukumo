import { Tile, TileEmpty } from './Tile'

/** Tile 8 — Nudge inbox chip (DESIGN §3.8): pending/snoozed count, tap
 * through to the full NudgeInbox (Phase 5 — the coach itself lands Phase
 * 6, so the chip still reads honestly quiet at 0). */
export function NudgeTile({ count, onOpenNudges }: { count?: number; onOpenNudges?: () => void }) {
  if (count === undefined) return null
  const aside = onOpenNudges ? (
    <button type="button" onClick={onOpenNudges} className="min-h-6 text-[11px] font-medium text-sky underline-offset-2 hover:underline">
      open
    </button>
  ) : undefined
  return (
    <Tile title="Nudges" ariaLabel={`Nudges: ${count} waiting`} aside={aside}>
      {count === 0 ? (
        <TileEmpty>Nothing waiting right now.</TileEmpty>
      ) : (
        <button
          type="button"
          onClick={onOpenNudges}
          disabled={!onOpenNudges}
          className="flex min-h-11 w-full items-center gap-2 rounded-md border border-line bg-paper px-3 py-2 text-left transition hover:border-line-strong disabled:cursor-default"
        >
          <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full bg-clay px-2 font-mono text-sm font-medium text-paper">
            {count}
          </span>
          <span className="text-sm text-ink-mid">waiting for you</span>
        </button>
      )}
    </Tile>
  )
}
