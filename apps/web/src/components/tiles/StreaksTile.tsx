import { useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { post } from '../../api'
import { gapLabel, type HabitState } from '../../dashboard'
import { Tile, TileEmpty } from './Tile'

/** Tile 3 — Streaks (DESIGN §3.3): one card per habit — state, gap phrasing,
 * evidence-source icon for auto habits, and the big one-tap log with the
 * hanko-stamp press animation (DESIGN §4 — the app's single signature
 * flourish) for tap habits. Auto habits never show a checkbox anywhere
 * (the material-difference law). */

function EvidenceIcon({ evidence }: { evidence: string | null }) {
  const cls = 'h-3.5 w-3.5'
  if (evidence?.startsWith('workouts')) {
    // dumbbell
    return (
      <svg viewBox="0 0 20 20" aria-hidden className={cls}>
        <g stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <line x1="6" y1="10" x2="14" y2="10" />
          <line x1="5" y1="6.5" x2="5" y2="13.5" />
          <line x1="15" y1="6.5" x2="15" y2="13.5" />
          <line x1="2.5" y1="8" x2="2.5" y2="12" />
          <line x1="17.5" y1="8" x2="17.5" y2="12" />
        </g>
      </svg>
    )
  }
  if (evidence?.startsWith('michi')) {
    // paw print — Michi supplies the evidence
    return (
      <svg viewBox="0 0 20 20" aria-hidden className={cls}>
        <ellipse cx="10" cy="13.5" rx="4" ry="3.2" fill="currentColor" />
        <ellipse cx="5.4" cy="7.5" rx="1.5" ry="2" fill="currentColor" />
        <ellipse cx="10" cy="5.8" rx="1.5" ry="2" fill="currentColor" />
        <ellipse cx="14.6" cy="7.5" rx="1.5" ry="2" fill="currentColor" />
      </svg>
    )
  }
  // generic event feed
  return (
    <svg viewBox="0 0 20 20" aria-hidden className={cls}>
      <path d="M3 10h4l2-5 3 10 2-5h3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const STATE_STYLE: Record<HabitState['state'], { dot: string; label: string }> = {
  done_today: { dot: 'bg-olive', label: 'done today' },
  ok: { dot: 'bg-olive', label: 'on track' },
  due: { dot: 'bg-kraft', label: 'due' },
  empty: { dot: 'bg-cloud', label: 'no entries yet' },
}

function HankoButton({ habit, onLogged }: { habit: HabitState; onLogged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [stamped, setStamped] = useState(habit.done_today)
  const reduce = useReducedMotion()

  async function stamp() {
    if (busy || stamped) return
    setBusy(true)
    try {
      await post(`/api/habits/${habit.id}/events`, {})
      setStamped(true)
      onLogged()
    } catch {
      /* quiet failure — the card state simply doesn't change */
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.button
      type="button"
      onClick={stamp}
      disabled={busy || stamped}
      whileTap={reduce || stamped ? undefined : { scale: 0.88 }}
      aria-label={stamped ? `${habit.title} logged for today` : `Log ${habit.title} for today`}
      className={`relative inline-flex h-11 min-w-11 items-center justify-center overflow-hidden rounded-full border px-4 text-sm font-medium transition ${
        stamped
          ? 'border-clay/40 bg-clay/10 text-clay'
          : 'border-clay bg-clay text-paper hover:bg-clay-deep'
      }`}
    >
      {/* the ink-spread: a clay wash blooming from the press */}
      <AnimatePresence>
        {stamped && !reduce && (
          <motion.span
            key="ink"
            aria-hidden
            initial={{ scale: 0, opacity: 0.6 }}
            animate={{ scale: 2.4, opacity: 0 }}
            transition={{ duration: 0.55, ease: 'easeOut' }}
            className="absolute inset-0 m-auto h-full w-full rounded-full bg-clay"
          />
        )}
      </AnimatePresence>
      <span className="relative">{stamped ? '✓ logged' : 'Log today'}</span>
    </motion.button>
  )
}

export function StreaksTile({ habits, onLogged }: { habits?: HabitState[]; onLogged: () => void }) {
  if (!habits) return null
  return (
    <Tile title="Streaks" ariaLabel="Habit streaks">
      {habits.length === 0 ? (
        <TileEmpty>No habits configured yet — set them up on the Habits tab.</TileEmpty>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {habits.map((h) => {
            const style = STATE_STYLE[h.state]
            const summary = `${h.title}: ${style.label}, last ${gapLabel(h.gap_days)}${
              h.target.per_week ? `, ${h.week_count} of ${h.target.per_week} this week` : ''
            }`
            return (
              <li
                key={h.id}
                aria-label={summary}
                className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper p-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} aria-hidden />
                    <span className="truncate text-sm font-medium text-ink">{h.title}</span>
                    {h.kind === 'auto' && (
                      <span className="text-ink-soft" title={`evidence: ${h.evidence ?? 'auto'}`} aria-hidden>
                        <EvidenceIcon evidence={h.evidence} />
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-ink-soft">
                    last: {gapLabel(h.gap_days)}
                    {h.target.per_week != null && (
                      <span className="ml-2 font-mono text-[11px]">
                        {h.week_count}/{h.target.per_week} wk
                      </span>
                    )}
                  </div>
                  {h.key === 'reading' && (
                    <div className="mt-1 truncate font-serif text-xs text-ink-mid">
                      {h.current_book ? (
                        <>
                          reading <span className="italic">{h.current_book.title}</span>
                        </>
                      ) : (
                        'no book on the go'
                      )}
                    </div>
                  )}
                </div>
                {(h.kind === 'tap' || h.kind === 'hybrid') && <HankoButton habit={h} onLogged={onLogged} />}
              </li>
            )
          })}
        </ul>
      )}
    </Tile>
  )
}
