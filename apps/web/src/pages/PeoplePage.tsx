import { useCallback, useEffect, useState } from 'react'
import { get, patch, post } from '../api'

/** People / occasions / gift vault + the calendar birthday import review
 * (docs/DATA_MODEL.md §3, docs/phases/PHASE-4-dashboard.md build item 4).
 * Primary-only — the server 403s any partner request, so this page is only
 * ever routed for the primary role (App.tsx). Candidates are suggestions:
 * confirming by hand is the only thing that creates a person (HANDOFF Q8). */

interface OccasionRow {
  id: number
  person_id: number | null
  title: string
  month_day: string | null
  date: string | null
  recurrence: string
  lead_days: number
  kind: string
}

interface GiftRow {
  id: number
  person_id: number
  idea: string
  url: string | null
  price_pence: number | null
  status: 'idea' | 'bought' | 'given'
  occasion_id: number | null
}

interface PersonRow {
  id: number
  name: string
  relation: string | null
  birthday: string | null
  notes: string | null
  archived: boolean
  occasions: OccasionRow[]
  gift_ideas: GiftRow[]
}

interface Candidate {
  name: string
  month_day: string
  next_date: string
  source_title: string
  calendar_name: string | null
}

const inputCls =
  'min-h-11 w-full rounded-md border border-line-strong bg-white px-3 py-2 text-sm text-ink placeholder:text-cloud outline-none focus:border-clay dark:bg-paper-mid'
const buttonCls =
  'min-h-11 rounded-md bg-clay px-4 text-sm font-medium text-paper transition hover:bg-clay-deep disabled:opacity-50'
const quietButtonCls =
  'min-h-11 rounded-full border border-line-strong px-2.5 text-xs font-medium text-ink-mid transition hover:border-clay hover:text-clay'

const GIFT_NEXT: Record<GiftRow['status'], GiftRow['status']> = { idea: 'bought', bought: 'given', given: 'idea' }

function GiftStatusPill({ gift, onCycle }: { gift: GiftRow; onCycle: () => void }) {
  const style =
    gift.status === 'bought'
      ? 'bg-olive/15 text-olive'
      : gift.status === 'given'
        ? 'bg-oat text-ink-mid'
        : 'bg-sky/15 text-sky'
  return (
    <button
      type="button"
      onClick={onCycle}
      title={`Tap to mark ${GIFT_NEXT[gift.status]}`}
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${style}`}
    >
      {gift.status}
      {gift.status === 'bought' && ' ✓'}
    </button>
  )
}

function CandidateReview({ candidates, onConfirmed }: { candidates: Candidate[]; onConfirmed: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const visible = candidates.filter((c) => !dismissed.has(`${c.name}:${c.month_day}`))
  if (visible.length === 0) return null

  return (
    <section className="rounded-lg border border-sky/40 bg-sky/5 p-4">
      <h2 className="font-display text-sm font-medium text-ink-mid">From the calendar</h2>
      <p className="mt-1 text-xs text-ink-soft">
        These look like birthdays. Confirm the ones worth tracking — nothing is added on its own.
      </p>
      <ul className="mt-3 space-y-2">
        {visible.map((c) => {
          const key = `${c.name}:${c.month_day}`
          return (
            <li key={key} className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper px-3 py-2">
              <div className="min-w-0">
                <span className="text-sm font-medium text-ink">{c.name}</span>
                <span className="ml-2 font-mono text-[11px] text-ink-soft">{c.month_day}</span>
                <div className="truncate text-[11px] text-ink-soft">“{c.source_title}”</div>
              </div>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  disabled={busy === key}
                  onClick={async () => {
                    setBusy(key)
                    try {
                      await post('/api/people/candidates/confirm', { name: c.name, month_day: c.month_day })
                      onConfirmed()
                    } catch {
                      /* stays in the list */
                    } finally {
                      setBusy(null)
                    }
                  }}
                  className={quietButtonCls}
                >
                  {busy === key ? '…' : 'Add'}
                </button>
                <button
                  type="button"
                  onClick={() => setDismissed(new Set([...dismissed, key]))}
                  className="min-h-8 px-1.5 text-xs text-ink-soft hover:text-ink"
                  aria-label={`Skip ${c.name}`}
                >
                  skip
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function AddPersonForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState('')
  const [relation, setRelation] = useState('')
  const [birthday, setBirthday] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setError(null)
        try {
          await post('/api/people', {
            name: name.trim(),
            relation: relation.trim() || null,
            birthday: birthday || null,
          })
          setName('')
          setRelation('')
          setBirthday('')
          onAdded()
        } catch (err) {
          setError(err instanceof Error ? err.message : 'could not save')
        } finally {
          setBusy(false)
        }
      }}
    >
      <div className="min-w-36 flex-1">
        <label className="text-[11px] font-medium text-ink-soft" htmlFor="p-name">Name</label>
        <input id="p-name" required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
      </div>
      <div className="min-w-28 flex-1">
        <label className="text-[11px] font-medium text-ink-soft" htmlFor="p-rel">Relation</label>
        <input id="p-rel" value={relation} onChange={(e) => setRelation(e.target.value)} placeholder="friend, family…" className={inputCls} />
      </div>
      <div>
        <label className="text-[11px] font-medium text-ink-soft" htmlFor="p-bday">Birthday</label>
        <input id="p-bday" type="date" value={birthday} onChange={(e) => setBirthday(e.target.value)} className={inputCls} />
      </div>
      <button type="submit" disabled={busy || !name.trim()} className={buttonCls}>
        {busy ? 'Adding…' : 'Add person'}
      </button>
      {error && <p className="w-full text-xs text-fig">{error}</p>}
    </form>
  )
}

function PersonCard({ person, onChanged }: { person: PersonRow; onChanged: () => void }) {
  const [giftIdea, setGiftIdea] = useState('')
  const [addingGift, setAddingGift] = useState(false)

  return (
    <li className="rounded-lg border border-line bg-paper-mid p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="font-display text-base font-medium text-ink">{person.name}</span>
          {person.relation && <span className="ml-2 text-xs text-ink-soft">{person.relation}</span>}
          {person.birthday && (
            <div className="mt-0.5 font-mono text-[11px] text-ink-soft">birthday {person.birthday}</div>
          )}
        </div>
        <button
          type="button"
          onClick={() => patch(`/api/people/${person.id}`, { archived: true }).then(onChanged, () => undefined)}
          className="min-h-8 text-xs text-ink-soft hover:text-ink"
        >
          archive
        </button>
      </div>

      {person.occasions.length > 0 && (
        <ul className="mt-3 space-y-1">
          {person.occasions.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-2 text-sm text-ink-mid">
              <span>
                {o.kind === 'birthday' && <span className="mr-1 text-fig" aria-hidden>♥</span>}
                {o.title}
              </span>
              <span className="font-mono text-[11px] text-ink-soft">
                {o.month_day ? `every ${o.month_day}` : o.date} · {o.lead_days}d lead
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 border-t border-line pt-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-soft">Gift vault</div>
        {person.gift_ideas.length > 0 && (
          <ul className="mt-1.5 space-y-1">
            {person.gift_ideas.map((g) => (
              <li key={g.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-ink">
                  {g.url ? (
                    <a href={g.url} target="_blank" rel="noreferrer" className="text-sky underline-offset-2 hover:underline">
                      {g.idea}
                    </a>
                  ) : (
                    g.idea
                  )}
                  {g.price_pence != null && (
                    <span className="ml-1.5 font-mono text-[11px] text-ink-soft">£{(g.price_pence / 100).toFixed(2)}</span>
                  )}
                </span>
                <GiftStatusPill
                  gift={g}
                  onCycle={() => patch(`/api/gifts/${g.id}`, { status: GIFT_NEXT[g.status] }).then(onChanged, () => undefined)}
                />
              </li>
            ))}
          </ul>
        )}
        <form
          className="mt-2 flex gap-2"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!giftIdea.trim()) return
            setAddingGift(true)
            try {
              await post('/api/gifts', { person_id: person.id, idea: giftIdea.trim() })
              setGiftIdea('')
              onChanged()
            } catch {
              /* quiet */
            } finally {
              setAddingGift(false)
            }
          }}
        >
          <input
            value={giftIdea}
            onChange={(e) => setGiftIdea(e.target.value)}
            placeholder="an idea…"
            aria-label={`Gift idea for ${person.name}`}
            className={inputCls}
          />
          <button type="submit" disabled={addingGift || !giftIdea.trim()} className={quietButtonCls}>
            keep
          </button>
        </form>
      </div>
    </li>
  )
}

export function PeoplePage() {
  const [people, setPeople] = useState<PersonRow[] | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    get<PersonRow[]>('/api/people').then(setPeople, (err) => setError(err instanceof Error ? err.message : 'failed'))
    get<Candidate[]>('/api/people/candidates').then(setCandidates, () => setCandidates([]))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (error) {
    return <p className="rounded-lg border border-line bg-paper-mid p-5 text-sm text-ink-soft">Couldn’t load people — {error}</p>
  }
  if (people === null) {
    return <div className="h-40 animate-pulse rounded-lg border border-line bg-paper-mid" role="status" aria-label="Loading people" />
  }

  return (
    <div className="space-y-4">
      <CandidateReview candidates={candidates} onConfirmed={load} />

      <section className="rounded-lg border border-line bg-paper-mid p-4">
        <h2 className="mb-3 font-display text-sm font-medium text-ink-mid">Someone new</h2>
        <AddPersonForm onAdded={load} />
      </section>

      {people.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong px-5 py-8 text-center text-sm text-ink-soft">
          No one here yet — add the people whose dates matter.
        </p>
      ) : (
        <ul className="space-y-3">
          {people.map((p) => (
            <PersonCard key={p.id} person={p} onChanged={load} />
          ))}
        </ul>
      )}
    </div>
  )
}
