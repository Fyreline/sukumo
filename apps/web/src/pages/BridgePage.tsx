/** The Bridge — the morning tab, one scroll of tiles in priority order
 * (docs/DESIGN.md §3): Today, Vitals, Streaks, House goal, People, Memory
 * strip, Dyehouse status, Nudge inbox — painted from one GET /api/dashboard
 * call. Fable-built; Phase 1 only wires the auth-gated empty stub behind
 * which that work lands (docs/phases/PHASE-1-scaffold.md,
 * docs/phases/PHASE-4-dashboard.md). */
export function BridgePage() {
  return (
    <div className="rounded-lg border border-dashed border-line-strong px-5 py-10 text-center text-sm text-ink-soft">
      The bridge is being built — tiles arrive in Phase 4.
    </div>
  )
}
