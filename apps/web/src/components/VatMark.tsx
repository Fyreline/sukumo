/** The vat glyph — a minimal woodblock aigame (藍甕, indigo dye vat) seen
 * from above: a paper-white rim ring around a deep indigo pool, a small
 * clay hanko dot at its edge (docs/DESIGN.md §2). Doubles conceptually as
 * the PWA icon (public/icons/icon.svg is the maskable, full-bleed twin of
 * this mark). */
export function VatMark({ className = 'h-9 w-9' }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" aria-hidden className={className}>
      <circle cx="24" cy="24" r="22" fill="var(--color-paper)" stroke="var(--color-line-strong)" strokeWidth="1" />
      <circle cx="24" cy="24" r="16.5" fill="none" stroke="var(--color-line)" strokeWidth="1" />
      <circle cx="24" cy="24" r="15" fill="var(--color-ink)" />
      <circle cx="42.5" cy="24" r="2.6" fill="var(--color-clay)" />
    </svg>
  )
}
