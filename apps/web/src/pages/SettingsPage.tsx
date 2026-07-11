import { useEffect, useState } from 'react'
import { logout } from '../auth'
import {
  getCoachSettings,
  patchCoachSettings,
  RULE_LABELS,
  type CoachSettings,
} from '../settings'

/** Settings (docs/COACH.md §2, docs/phases/PHASE-6-coach.md build item 6): the
 * coach's household knobs, live now that the coach has moved in — quiet hours,
 * the daily push cap, and a per-rule on/off. Primary-only server-side
 * (routers/settings.py); the partner shell shows the install + session rows
 * only, since these calls 403 for them. */

const rowCls = 'rounded-lg border border-line bg-paper-mid p-4'

export function SettingsPage() {
  const [settings, setSettings] = useState<CoachSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getCoachSettings()
      .then(setSettings)
      .catch((e) => setError(e?.code === 'forbidden' ? 'forbidden' : e?.message ?? 'Could not load settings'))
  }, [])

  async function save(patch: Parameters<typeof patchCoachSettings>[0]) {
    setSaving(true)
    setError(null)
    try {
      setSettings(await patchCoachSettings(patch))
    } catch (e) {
      setError((e as { message?: string })?.message ?? 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  const [start, end] = settings?.quiet_hours?.split('-') ?? ['22:30', '07:30']

  return (
    <div className="space-y-3">
      {settings && error !== 'forbidden' && (
        <>
          <section className={rowCls} aria-label="Quiet hours">
            <h2 className="font-display text-sm font-medium text-ink-mid">Quiet hours</h2>
            <div className="mt-2 flex items-center gap-2">
              <input
                type="time"
                defaultValue={start}
                aria-label="Quiet hours start"
                onBlur={(e) => save({ quiet_hours: `${e.target.value}-${end}` })}
                className="min-h-11 rounded-md border border-line bg-paper px-3 text-sm text-ink"
              />
              <span className="text-ink-soft">to</span>
              <input
                type="time"
                defaultValue={end}
                aria-label="Quiet hours end"
                onBlur={(e) => save({ quiet_hours: `${start}-${e.target.value}` })}
                className="min-h-11 rounded-md border border-line bg-paper px-3 text-sm text-ink"
              />
            </div>
            <p className="mt-2 text-xs text-ink-soft">Nothing pushes inside these — held until the morning window.</p>
          </section>

          <section className={rowCls} aria-label="Daily nudge cap">
            <h2 className="font-display text-sm font-medium text-ink-mid">Daily nudge cap</h2>
            <div className="mt-2 flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={20}
                defaultValue={settings.daily_cap}
                aria-label="Daily nudge cap"
                onBlur={(e) => save({ daily_cap: Number(e.target.value) })}
                className="min-h-11 w-20 rounded-md border border-line bg-paper px-3 text-sm text-ink"
              />
            </div>
            <p className="mt-1 text-xs text-ink-soft">Beyond it, nudges land inbox-only.</p>
          </section>

          <section className={rowCls} aria-label="Coach rules">
            <h2 className="font-display text-sm font-medium text-ink-mid">Coach rules</h2>
            <ul className="mt-2 divide-y divide-line">
              {settings.rules.map((r) => (
                <li key={r.key} className="flex items-center justify-between py-2">
                  <span className="text-sm text-ink">{RULE_LABELS[r.key] ?? r.key}</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={r.enabled}
                    aria-label={`${RULE_LABELS[r.key] ?? r.key} ${r.enabled ? 'on' : 'off'}`}
                    disabled={saving}
                    onClick={() => save({ rules: { [r.key]: !r.enabled } })}
                    className={`relative h-6 w-11 shrink-0 rounded-full transition ${
                      r.enabled ? 'bg-clay' : 'bg-line-strong'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-5 w-5 rounded-full bg-paper transition-all ${
                        r.enabled ? 'left-[22px]' : 'left-0.5'
                      }`}
                    />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      {error && error !== 'forbidden' && <p className="px-1 text-xs text-fig">{error}</p>}

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
