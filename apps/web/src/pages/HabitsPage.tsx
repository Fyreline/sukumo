import { useCallback, useEffect, useState } from 'react'
import { get, patch, post } from '../api'

/** Habit config over Phase 2's endpoints + the current-book control
 * (docs/phases/PHASE-4-dashboard.md build item 5, DATA_MODEL §2).
 * Auto habits never show a log control here either — the
 * material-difference law holds everywhere, not just on the bridge. */

interface HabitRow {
  id: number
  key: string
  title: string
  kind: 'auto' | 'tap' | 'hybrid'
  target_json: { per_week?: number; per_day?: number }
  evidence: string | null
  active: boolean
  config_json: { wtypes?: string[] }
}

interface BookRow {
  id: number
  title: string
  author: string | null
  status: 'reading' | 'finished' | 'abandoned'
  started_on: string | null
  finished_on: string | null
}

const inputCls =
  'min-h-11 w-full rounded-md border border-line-strong bg-white px-3 py-2 text-sm text-ink placeholder:text-cloud outline-none focus:border-clay dark:bg-paper-mid'
const quietButtonCls =
  'min-h-8 rounded-full border border-line-strong px-2.5 text-xs font-medium text-ink-mid transition hover:border-clay hover:text-clay disabled:opacity-50'

function targetLabel(h: HabitRow): string {
  if (h.target_json.per_day) return `${h.target_json.per_day}× / day`
  if (h.target_json.per_week) return `${h.target_json.per_week}× / week`
  return 'no target'
}

function HabitCard({ habit, onChanged }: { habit: HabitRow; onChanged: () => void }) {
  const [perWeek, setPerWeek] = useState(habit.target_json.per_week?.toString() ?? '')
  const [saving, setSaving] = useState(false)

  async function saveTarget() {
    setSaving(true)
    try {
      const n = parseInt(perWeek, 10)
      await patch(`/api/habits/${habit.id}`, {
        target_json: Number.isFinite(n) && n > 0 ? { per_week: n } : habit.target_json,
      })
      onChanged()
    } catch {
      /* quiet */
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className={`rounded-lg border border-line bg-paper-mid p-4 ${habit.active ? '' : 'opacity-60'}`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <span className="font-display text-base font-medium text-ink">{habit.title}</span>
          <span className="ml-2 rounded-full bg-oat px-2 py-0.5 text-[11px] text-ink-mid">{habit.kind}</span>
          <div className="mt-1 text-xs text-ink-soft">
            {targetLabel(habit)}
            {habit.evidence && <span className="ml-2 font-mono text-[10px]">evidence: {habit.evidence}</span>}
            {habit.kind === 'auto' && habit.config_json.wtypes && (
              <span className="ml-2 font-mono text-[10px]">counts: {habit.config_json.wtypes.join(', ')}</span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={() => patch(`/api/habits/${habit.id}`, { active: !habit.active }).then(onChanged, () => undefined)}
          className={quietButtonCls}
        >
          {habit.active ? 'pause' : 'resume'}
        </button>
      </div>

      {habit.target_json.per_week != null && (
        <div className="mt-3 flex items-end gap-2 border-t border-line pt-3">
          <div className="w-24">
            <label htmlFor={`t-${habit.id}`} className="text-[11px] font-medium text-ink-soft">
              per week
            </label>
            <input
              id={`t-${habit.id}`}
              type="number"
              min="1"
              max="14"
              value={perWeek}
              onChange={(e) => setPerWeek(e.target.value)}
              className={inputCls}
            />
          </div>
          <button type="button" disabled={saving} onClick={saveTarget} className={quietButtonCls}>
            {saving ? '…' : 'save'}
          </button>
        </div>
      )}
    </li>
  )
}

function CurrentBookCard({ books, onChanged }: { books: BookRow[]; onChanged: () => void }) {
  const current = books.find((b) => b.status === 'reading') ?? null
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [busy, setBusy] = useState(false)

  return (
    <section className="rounded-lg border border-line bg-paper-mid p-4">
      <h2 className="font-display text-sm font-medium text-ink-mid">Current book</h2>
      {current ? (
        <div className="mt-2 flex items-center justify-between gap-3">
          <div>
            <div className="font-serif text-base italic text-ink">{current.title}</div>
            {current.author && <div className="text-xs text-ink-soft">{current.author}</div>}
            {current.started_on && <div className="mt-0.5 font-mono text-[11px] text-ink-soft">since {current.started_on}</div>}
          </div>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={() => patch(`/api/books/${current.id}`, { status: 'finished' }).then(onChanged, () => undefined)}
              className={quietButtonCls}
            >
              finished
            </button>
            <button
              type="button"
              onClick={() => patch(`/api/books/${current.id}`, { status: 'abandoned' }).then(onChanged, () => undefined)}
              className="min-h-8 px-1.5 text-xs text-ink-soft hover:text-ink"
            >
              set aside
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-soft">Nothing on the go.</p>
      )}

      <form
        className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!title.trim()) return
          setBusy(true)
          try {
            await post('/api/books', { title: title.trim(), author: author.trim() || null })
            setTitle('')
            setAuthor('')
            onChanged()
          } catch {
            /* quiet */
          } finally {
            setBusy(false)
          }
        }}
      >
        <div className="min-w-40 flex-1">
          <label htmlFor="b-title" className="text-[11px] font-medium text-ink-soft">Start a new one</label>
          <input id="b-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="title" className={inputCls} />
        </div>
        <div className="min-w-32 flex-1">
          <label htmlFor="b-author" className="text-[11px] font-medium text-ink-soft">Author</label>
          <input id="b-author" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="optional" className={inputCls} />
        </div>
        <button type="submit" disabled={busy || !title.trim()} className={quietButtonCls}>
          {busy ? '…' : 'start'}
        </button>
      </form>

      {books.some((b) => b.status !== 'reading') && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-ink-soft">shelf history</summary>
          <ul className="mt-2 space-y-1">
            {books
              .filter((b) => b.status !== 'reading')
              .map((b) => (
                <li key={b.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate font-serif italic text-ink-mid">{b.title}</span>
                  <span className="font-mono text-[11px] text-ink-soft">
                    {b.status === 'finished' ? `finished ${b.finished_on ?? ''}` : 'set aside'}
                  </span>
                </li>
              ))}
          </ul>
        </details>
      )}
    </section>
  )
}

export function HabitsPage() {
  const [habits, setHabits] = useState<HabitRow[] | null>(null)
  const [books, setBooks] = useState<BookRow[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    get<HabitRow[]>('/api/habits').then(setHabits, (err) => setError(err instanceof Error ? err.message : 'failed'))
    get<BookRow[]>('/api/books').then(setBooks, () => setBooks([]))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (error) {
    return <p className="rounded-lg border border-line bg-paper-mid p-5 text-sm text-ink-soft">Couldn’t load habits — {error}</p>
  }
  if (habits === null) {
    return <div className="h-40 animate-pulse rounded-lg border border-line bg-paper-mid" role="status" aria-label="Loading habits" />
  }

  return (
    <div className="space-y-4">
      <CurrentBookCard books={books} onChanged={load} />
      {habits.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong px-5 py-8 text-center text-sm text-ink-soft">
          No habits configured yet.
        </p>
      ) : (
        <ul className="space-y-3">
          {habits.map((h) => (
            <HabitCard key={h.id} habit={h} onChanged={load} />
          ))}
        </ul>
      )}
    </div>
  )
}
