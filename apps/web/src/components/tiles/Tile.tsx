import type { ReactNode } from 'react'

/** Shared bridge-tile frame (docs/DESIGN.md §3): a calm card on the paper
 * ground. Tiles degrade independently — pass `empty` copy and the tile
 * renders a quiet placeholder instead of blanking (ARCHITECTURE §5.6
 * honesty); `dimmed` greys a tile whose source has gone stale. */
export function Tile({
  title,
  aside,
  children,
  accent = false,
  dimmed = false,
  ariaLabel,
}: {
  title: string
  aside?: ReactNode
  children: ReactNode
  /** clay left border — the coach's tiles only (DESIGN §3.1) */
  accent?: boolean
  dimmed?: boolean
  ariaLabel?: string
}) {
  return (
    <section
      aria-label={ariaLabel ?? title}
      className={`rounded-lg border border-line bg-paper-mid p-4 sm:p-5 ${
        accent ? 'border-l-2 border-l-clay' : ''
      } ${dimmed ? 'opacity-60' : ''}`}
    >
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="font-display text-sm font-medium tracking-[0.02em] text-ink-mid">{title}</h2>
        {aside && <div className="shrink-0 text-[11px] text-ink-soft">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

/** The quiet empty state — never a blank card (DESIGN §3). */
export function TileEmpty({ children }: { children: ReactNode }) {
  return <p className="py-2 text-sm text-ink-soft">{children}</p>
}

/** kraft "stale" pill for tile corners and the offline banner. */
export function StaleChip({ label = 'stale' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-kraft/50 bg-kraft/10 px-2 py-0.5 text-[11px] font-medium text-kraft">
      <span className="h-1.5 w-1.5 rounded-full bg-kraft" aria-hidden />
      {label}
    </span>
  )
}
