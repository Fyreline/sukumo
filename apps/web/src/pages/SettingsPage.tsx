import { logout } from '../auth'

/** Settings shell (docs/phases/PHASE-4-dashboard.md build item 5): quiet
 * hours + caps are placeholders until the coach arrives in Phase 6 — the
 * page says so quietly rather than pretending. The install row is DESIGN
 * §5's "quiet Settings row, not a nag banner". */

const rowCls = 'rounded-lg border border-line bg-paper-mid p-4'

export function SettingsPage() {
  return (
    <div className="space-y-3">
      <section className={rowCls} aria-label="Quiet hours">
        <h2 className="font-display text-sm font-medium text-ink-mid">Quiet hours</h2>
        <div className="mt-2 flex items-center gap-2">
          <input
            type="time"
            value="22:30"
            disabled
            readOnly
            aria-label="Quiet hours start"
            className="min-h-11 rounded-md border border-line bg-paper px-3 text-sm text-ink-soft"
          />
          <span className="text-ink-soft">to</span>
          <input
            type="time"
            value="07:30"
            disabled
            readOnly
            aria-label="Quiet hours end"
            className="min-h-11 rounded-md border border-line bg-paper px-3 text-sm text-ink-soft"
          />
        </div>
        <p className="mt-2 text-xs text-ink-soft">Nothing pushes inside these. Editable once the coach moves in.</p>
      </section>

      <section className={rowCls} aria-label="Daily nudge cap">
        <h2 className="font-display text-sm font-medium text-ink-mid">Daily nudge cap</h2>
        <div className="mt-2 font-mono text-lg text-ink-soft">5</div>
        <p className="mt-1 text-xs text-ink-soft">Beyond it, nudges land inbox-only. Also arrives with the coach.</p>
      </section>

      <section className={rowCls} aria-label="Install">
        <h2 className="font-display text-sm font-medium text-ink-mid">On your home screen</h2>
        <p className="mt-2 text-xs text-ink-soft">
          Sukumo installs as an app: open it in Safari, tap Share, then “Add to Home Screen”. The bridge keeps
          working offline from the last good view.
        </p>
      </section>

      <section className={rowCls} aria-label="Session">
        <h2 className="font-display text-sm font-medium text-ink-mid">Session</h2>
        <button
          type="button"
          onClick={() => logout()}
          className="mt-2 min-h-11 rounded-md border border-line-strong px-4 text-sm font-medium text-ink-mid transition hover:border-clay hover:text-clay"
        >
          Sign out
        </button>
      </section>
    </div>
  )
}
