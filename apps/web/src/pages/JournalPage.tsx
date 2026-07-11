import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Markdown, stripLeadingHeading } from '../components/Markdown'
import { Sparkline } from '../components/Sparkline'
import {
  KIND_LABEL,
  KIND_ORDER,
  eventTime,
  fetchDigests,
  fetchJournalDay,
  fetchJournalPhotos,
  fetchJournalRange,
  fetchPhotoThumb,
  patchMood,
  prettyDate,
  type DigestRow,
  type JournalDayDetail,
  type JournalDaySummary,
  type JournalEvent,
  type Mood,
  type PhotoGroup,
} from '../journal'

/** The journal (docs/MEMORY.md §5, PHASE-7 item 5): a vertical scroll of day
 * cards, newest first, on a continuous `--color-liquid` thread — the Michi
 * trail motif repurposed as a timeline. Event pearls sized by kind, thin days
 * visually quieter, month jump-nav, trip chapter headers (crimson torii for
 * Japan), inline day detail with sparkline stats + the mood one-tap.
 *
 * Read-only by design: mood is the ONLY input on the whole page (MEMORY §1 —
 * days assemble themselves). Primary-only — App.tsx never routes the tab for
 * role='partner' and the server 403s regardless. */

const RANGE_DAYS = 365 // one fetch covers the backfill + a year of history

function isoDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toLocaleDateString('en-CA') // YYYY-MM-DD, local
}

// ------------------------------------------------------------------ pearls --
/** Collapsed cards carry no events, but stats_json counts per kind — enough
 * to bead the thread. Sized by kind (milestones read loudest, in clay);
 * everything else is fig, the memory colour (DESIGN §1). */
const PEARL_STYLE: Record<string, string> = {
  milestone: 'h-3.5 w-3.5 bg-clay',
  photo: 'h-3 w-3 bg-fig',
  film: 'h-2.5 w-2.5 bg-fig',
  workout: 'h-2.5 w-2.5 bg-fig',
  study: 'h-2.5 w-2.5 bg-fig',
  calendar: 'h-2 w-2 bg-fig',
  place: 'h-2 w-2 bg-fig',
}
const MAX_PEARLS = 4

function pearlsFor(day: JournalDaySummary): { shown: string[]; overflow: number } {
  const s = day.stats
  const counts: [string, number][] = [
    ['workout', s.workouts ?? 0],
    ['study', s.study ? 1 : 0],
    ['calendar', s.calendar ?? 0],
    ['place', s.places ?? 0],
    ['film', s.films ?? 0],
    ['photo', (s.photos ?? 0) > 0 ? 1 : 0], // photos arrive as one per-day cluster
    ['milestone', s.milestones ?? 0],
  ]
  const all: string[] = []
  for (const [kind, n] of counts) for (let i = 0; i < n; i++) all.push(kind)
  const shown = all.slice(0, MAX_PEARLS)
  return { shown, overflow: Math.max(day.event_count - shown.length, 0) }
}

// ------------------------------------------------------------- mood stamps --
/** Five hanko-stamp dots (DESIGN §4 — the one-tap log flourish, reused).
 * A magnitude scale: the dot shrinks from great to rough. Tapping the
 * current mood clears it (PATCH mood: null). */
const MOODS: { value: Mood; dot: string }[] = [
  { value: 'great', dot: 'h-4 w-4' },
  { value: 'good', dot: 'h-3.5 w-3.5' },
  { value: 'ok', dot: 'h-3 w-3' },
  { value: 'low', dot: 'h-2.5 w-2.5' },
  { value: 'rough', dot: 'h-2 w-2' },
]

function MoodRow({
  date,
  mood,
  onSaved,
}: {
  date: string
  mood: Mood | null
  onSaved: (day: JournalDaySummary) => void
}) {
  const [busy, setBusy] = useState(false)
  const [justStamped, setJustStamped] = useState<Mood | null>(null)
  const reduce = useReducedMotion()

  async function tap(value: Mood) {
    if (busy) return
    setBusy(true)
    const next = value === mood ? null : value
    try {
      const updated = await patchMood(date, next)
      setJustStamped(next)
      onSaved(updated)
    } catch {
      /* quiet failure — the stamps simply don't change (household pattern) */
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <p className="mb-1.5 text-xs text-ink-soft">How was it? One tap — optional, clearable.</p>
      <div className="flex items-start gap-1" role="group" aria-label="Mood for this day">
        {MOODS.map((m) => {
          const selected = mood === m.value
          return (
            <motion.button
              key={m.value}
              type="button"
              disabled={busy}
              onClick={() => tap(m.value)}
              whileTap={reduce ? undefined : { scale: 0.88 }}
              aria-pressed={selected}
              aria-label={selected ? `Clear mood ${m.value}` : `Mood ${m.value}`}
              className="flex min-h-11 min-w-11 flex-col items-center justify-center gap-1"
            >
              <span
                className={`relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border transition ${
                  selected ? 'border-clay bg-clay/10' : 'border-line bg-paper'
                }`}
              >
                {/* the ink-spread bloom on a fresh stamp (DESIGN §4) */}
                <AnimatePresence>
                  {selected && justStamped === m.value && !reduce && (
                    <motion.span
                      key="ink"
                      aria-hidden
                      initial={{ scale: 0, opacity: 0.6 }}
                      animate={{ scale: 2.4, opacity: 0 }}
                      transition={{ duration: 0.55, ease: 'easeOut' }}
                      className="absolute inset-0 rounded-full bg-clay"
                    />
                  )}
                </AnimatePresence>
                <span
                  aria-hidden
                  className={`relative rounded-full ${m.dot} ${selected ? 'bg-clay' : 'bg-cloud'}`}
                />
              </span>
              <span className={`text-[10px] ${selected ? 'font-medium text-clay' : 'text-ink-soft'}`}>
                {m.value}
              </span>
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}

// -------------------------------------------------------------- photo strip --
/** The day's photos as a collapsible set of moment groups (MEMORY §5): the
 * server filters out screenshots/recordings/hidden/trash and buckets the rest
 * by Photos' own moments (time-gap clusters as fallback), so each group gets
 * a small label row — moment title, dominant place, or just the time range —
 * above its thumbnail row. Thumbs are authed fetches (a bare <img src> can't
 * carry the bearer header), so each one is blob → object URL, revoked on
 * collapse/unmount. The 24-thumb cap applies ACROSS groups ("+N more"). */
const MAX_THUMBS = 24

/** Cap the groups to a total thumb budget: later groups shrink, then drop. */
export function capGroups(groups: PhotoGroup[], budget: number): PhotoGroup[] {
  const capped: PhotoGroup[] = []
  let left = budget
  for (const g of groups) {
    if (left <= 0) break
    const photos = g.photos.slice(0, left)
    left -= photos.length
    capped.push({ ...g, photos })
  }
  return capped
}

function groupLabel(g: PhotoGroup): string {
  if (g.label) return g.label
  return g.start === g.end ? g.start : `${g.start}–${g.end}`
}

function PhotoStrip({ date, count }: { date: string; count: number }) {
  const [open, setOpen] = useState(false)
  const [groups, setGroups] = useState<PhotoGroup[] | 'loading' | 'error' | 'unconfigured' | null>(null)
  const [thumbs, setThumbs] = useState<Record<string, string>>({}) // uuid -> object URL
  const urls = useRef<string[]>([])

  const revokeAll = useCallback(() => {
    for (const u of urls.current) URL.revokeObjectURL(u)
    urls.current = []
    setThumbs({})
  }, [])

  // Unmount (day collapsed, page left): free every object URL.
  useEffect(
    () => () => {
      for (const u of urls.current) URL.revokeObjectURL(u)
    },
    [],
  )

  async function toggle() {
    if (open) {
      setOpen(false)
      revokeAll()
      setGroups(null) // refetched on next open — cheap, and never a stale strip
      return
    }
    setOpen(true)
    setGroups('loading')
    try {
      const res = await fetchJournalPhotos(date)
      if (!res.configured) {
        setGroups('unconfigured')
        return
      }
      setGroups(res.groups)
      // Lazy thumbs: fire the (small, cached-server-side) fetches in parallel;
      // each shimmer square fills in as its blob lands. Failures stay quiet —
      // the strip degrades to shimmers, never an error wall.
      for (const g of capGroups(res.groups, MAX_THUMBS)) {
        for (const p of g.photos) {
          fetchPhotoThumb(p.uuid).then(
            (blob) => {
              const url = URL.createObjectURL(blob)
              urls.current.push(url)
              setThumbs((m) => ({ ...m, [p.uuid]: url }))
            },
            () => undefined,
          )
        }
      }
    } catch {
      setGroups('error')
    }
  }

  const total = Array.isArray(groups) ? groups.reduce((n, g) => n + g.photos.length, 0) : 0
  const overflow = Math.max(0, total - MAX_THUMBS)
  const shown = Array.isArray(groups) ? capGroups(groups, MAX_THUMBS) : []

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex min-h-11 items-center gap-1.5 text-sm text-ink-mid"
      >
        <span>
          {count} photo{count === 1 ? '' : 's'} this day
        </span>
        <span aria-hidden className={`text-ink-soft transition-transform ${open ? 'rotate-90' : ''}`}>
          ›
        </span>
      </button>

      {open && groups === 'loading' && (
        <div className="mt-1 flex gap-2" role="status" aria-label="Loading photo previews">
          {[0, 1, 2].map((i) => (
            <span key={i} className="h-20 w-20 animate-pulse rounded-md bg-paper-deep motion-reduce:animate-none" />
          ))}
        </div>
      )}
      {open && groups === 'error' && (
        <p className="mt-1 text-xs text-ink-soft">Couldn’t load the previews just now.</p>
      )}
      {open && groups === 'unconfigured' && (
        <p className="mt-1 text-xs text-ink-soft">No photo library is wired up on the server yet.</p>
      )}
      {open && Array.isArray(groups) && (
        <div className="mt-1 space-y-2">
          {shown.map((g, gi) => (
            <div key={`${g.start}-${g.label ?? gi}`}>
              <p className="mb-1 text-xs text-ink-soft">
                {groupLabel(g)}
                {g.label && (
                  <span className="ml-1.5 font-mono text-[10px]">
                    {g.start === g.end ? g.start : `${g.start}–${g.end}`}
                  </span>
                )}
              </p>
              <ul
                className="flex gap-2 overflow-x-auto pb-1"
                aria-label={`Photo previews, ${date}, ${groupLabel(g)}`}
              >
                {g.photos.map((p) => (
                  <li key={p.uuid} className="shrink-0">
                    {thumbs[p.uuid] ? (
                      <img
                        src={thumbs[p.uuid]}
                        alt={`Photo at ${p.taken_at}${p.place ? `, ${p.place}` : ''}`}
                        className="h-20 w-20 rounded-md border border-line object-cover"
                      />
                    ) : (
                      <span
                        className="block h-20 w-20 animate-pulse rounded-md bg-paper-deep motion-reduce:animate-none"
                        aria-hidden
                      />
                    )}
                  </li>
                ))}
                {overflow > 0 && gi === shown.length - 1 && (
                  <li className="flex h-20 shrink-0 items-center px-1 font-mono text-[11px] text-ink-soft">
                    +{overflow} more
                  </li>
                )}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------------- route card --
/** The day's movement trace (MEMORY §5): the simplified [[lat, lon], …] from
 * stats_json drawn as a bare SVG polyline, auto-fitted to its bounding box
 * with a cos(lat) correction so distances aren't squashed. Deliberately NO
 * base map and NO external tile/geocoding requests — the coordinates never
 * leave the household (privacy IS the design). Sky ink at the liquid-thread
 * weight on paper; olive start dot, clay end dot; degrades to nothing when a
 * day has no trace. */
const ROUTE_W = 320
const ROUTE_H = 160
const ROUTE_PAD = 14

export function routeCaption(distanceM: number, awayMin: number | null | undefined): string {
  const km = `${(distanceM / 1000).toFixed(1)} km on foot`
  if (awayMin == null || awayMin <= 0) return km
  const h = Math.floor(awayMin / 60)
  const m = awayMin % 60
  const time = h > 0 ? (m > 0 ? `${h}h ${m}m` : `${h}h`) : `${m} min`
  return `${km} · ${time} out`
}

function RouteCard({
  trace,
  distanceM,
  awayMin,
}: {
  trace: [number, number][]
  distanceM: number
  awayMin: number | null | undefined
}) {
  const reduce = useReducedMotion()
  if (trace.length < 2) return null

  const lats = trace.map((p) => p[0])
  const lons = trace.map((p) => p[1])
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  // Metres-true aspect: one degree of longitude shrinks by cos(latitude).
  const kx = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180))
  const spanX = (maxLon - minLon) * kx || 1e-6
  const spanY = maxLat - minLat || 1e-6
  const scale = Math.min((ROUTE_W - ROUTE_PAD * 2) / spanX, (ROUTE_H - ROUTE_PAD * 2) / spanY)
  const offX = (ROUTE_W - spanX * scale) / 2
  const offY = (ROUTE_H - spanY * scale) / 2
  const x = (lon: number) => offX + (lon - minLon) * kx * scale
  const y = (lat: number) => ROUTE_H - offY - (lat - minLat) * scale // north up
  const pts = trace.map(([lat, lon]) => `${x(lon).toFixed(1)},${y(lat).toFixed(1)}`).join(' ')
  const [startLat, startLon] = trace[0]
  const [endLat, endLon] = trace[trace.length - 1]
  const caption = routeCaption(distanceM, awayMin)

  return (
    <div>
      <h4 className="mb-1.5 font-display text-xs font-medium tracking-[0.02em] text-ink-mid">Route</h4>
      <div className="rounded-lg border border-line bg-paper p-2">
        <svg
          viewBox={`0 0 ${ROUTE_W} ${ROUTE_H}`}
          role="img"
          aria-label={`Route for the day — ${caption}`}
          className="w-full max-w-sm"
        >
          {reduce ? (
            <polyline
              points={pts}
              fill="none"
              stroke="var(--color-sky)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : (
            <motion.polyline
              points={pts}
              fill="none"
              stroke="var(--color-sky)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              pathLength={1}
              strokeDasharray="1"
              initial={{ strokeDashoffset: 1 }}
              animate={{ strokeDashoffset: 0 }}
              transition={{ duration: 0.9, ease: 'easeInOut' }}
            />
          )}
          <circle cx={x(startLon)} cy={y(startLat)} r="3.5" fill="var(--color-olive)" />
          <circle cx={x(endLon)} cy={y(endLat)} r="3.5" fill="var(--color-clay)" />
        </svg>
        <p className="mt-1 px-1 font-mono text-[11px] text-ink-soft">{caption}</p>
      </div>
    </div>
  )
}

// -------------------------------------------------------------- day detail --
function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-full border border-line bg-paper px-2.5 py-1 text-xs text-ink-mid">
      <span className="font-mono text-[11px] text-ink">{value}</span>
      {label}
    </span>
  )
}

function DayDetail({
  detail,
  stepsSeries,
  onSaved,
}: {
  detail: JournalDayDetail
  stepsSeries: (number | null)[]
  onSaved: (day: JournalDaySummary) => void
}) {
  const s = detail.stats
  const chips: { label: string; value: string }[] = []
  if ((s.steps ?? 0) > 0) chips.push({ label: 'steps', value: (s.steps as number).toLocaleString('en-GB') })
  if ((s.workouts ?? 0) > 0)
    chips.push({ label: s.workouts === 1 ? 'workout' : 'workouts', value: String(s.workouts) })
  if (s.study)
    chips.push({ label: s.study_streak ? `study day (streak ${s.study_streak})` : 'study day', value: '✓' })
  if ((s.films ?? 0) > 0) chips.push({ label: s.films === 1 ? 'film' : 'films', value: String(s.films) })
  if ((s.places ?? 0) > 0) chips.push({ label: s.places === 1 ? 'place' : 'places', value: String(s.places) })

  const byKind = new Map<string, JournalEvent[]>()
  for (const e of detail.events) {
    const list = byKind.get(e.kind) ?? []
    list.push(e)
    byKind.set(e.kind, list)
  }
  const kinds = [
    ...KIND_ORDER.filter((k) => byKind.has(k)),
    ...[...byKind.keys()].filter((k) => !(KIND_ORDER as readonly string[]).includes(k)),
  ]
  const stepsPresent = stepsSeries.filter((v) => v != null).length
  const photoCount = s.photos ?? 0

  return (
    <div className="mt-3 space-y-4 border-t border-line pt-3">
      {(chips.length > 0 || stepsPresent >= 2) && (
        <div className="flex flex-wrap items-center gap-2">
          {chips.map((c) => (
            <StatChip key={c.label} label={c.label} value={c.value} />
          ))}
          {stepsPresent >= 2 && (
            <Sparkline
              values={stepsSeries}
              label={`Steps, the 14 days to ${prettyDate(detail.local_date)}`}
              className="h-7 w-24"
            />
          )}
        </div>
      )}

      {detail.anniversary.length > 0 && (
        <div className="space-y-1">
          {detail.anniversary.map((a) => (
            <p key={a.local_date} className="text-xs text-fig">
              {a.years_ago === 1 ? 'One year' : `${a.years_ago} years`} ago today —{' '}
              <span className="font-serif">{stripLeadingHeading(a.summary_md).split('\n')[0]}</span>
            </p>
          ))}
        </div>
      )}

      {kinds.map((kind) => (
        <div key={kind}>
          <h4 className="mb-1.5 font-display text-xs font-medium tracking-[0.02em] text-ink-mid">
            {KIND_LABEL[kind] ?? kind}
          </h4>
          <ul className="space-y-1">
            {(byKind.get(kind) ?? []).map((e, i) => {
              const allDay = e.detail.all_day === true
              const rating = typeof e.detail.rating === 'number' ? e.detail.rating : null
              const location =
                typeof e.detail.location === 'string' && e.detail.location ? e.detail.location : null
              return (
                <li key={i} className="flex items-baseline gap-2 text-sm">
                  <span className="w-12 shrink-0 font-mono text-[11px] text-ink-soft">
                    {allDay ? 'all day' : eventTime(e.ts)}
                  </span>
                  <span className="min-w-0">
                    <span className="font-serif text-ink">{e.title}</span>
                    {rating != null && (
                      <span className="ml-2 font-mono text-[11px] text-ink-soft">{rating}/5</span>
                    )}
                    {location && <span className="ml-2 text-xs text-ink-soft">{location}</span>}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      ))}

      {(s.trace?.length ?? 0) >= 2 && (
        <RouteCard trace={s.trace as [number, number][]} distanceM={s.distance_m ?? 0} awayMin={s.away_min} />
      )}

      {photoCount > 0 && <PhotoStrip date={detail.local_date} count={photoCount} />}

      <MoodRow date={detail.local_date} mood={detail.mood} onSaved={onSaved} />
    </div>
  )
}

// ----------------------------------------------------------------- day card --
function DayCard({
  day,
  expanded,
  detail,
  stepsSeries,
  onToggle,
  onSaved,
}: {
  day: JournalDaySummary
  expanded: boolean
  detail: JournalDayDetail | 'loading' | 'error' | undefined
  stepsSeries: (number | null)[]
  onToggle: () => void
  onSaved: (day: JournalDaySummary) => void
}) {
  const thin = day.event_count === 0
  const { shown, overflow } = pearlsFor(day)

  return (
    <li className="relative scroll-mt-32 pl-9" id={`day-${day.local_date}`}>
      {/* event pearls on the thread — sized by kind, fig on liquid */}
      <div className="absolute left-0 top-5 flex w-6 flex-col items-center gap-1" aria-hidden>
        {shown.length === 0 ? (
          <span className="h-2 w-2 rounded-full border border-line-strong bg-paper" />
        ) : (
          shown.map((kind, i) => (
            <span key={i} className={`rounded-full ${PEARL_STYLE[kind] ?? 'h-2 w-2 bg-fig'}`} />
          ))
        )}
        {overflow > 0 && <span className="font-mono text-[9px] leading-none text-ink-soft">+{overflow}</span>}
      </div>

      <article
        className={`rounded-lg border border-line ${thin ? 'bg-paper p-3' : 'bg-paper-mid p-4'}`}
        aria-label={`${prettyDate(day.local_date)}, ${day.event_count} event${
          day.event_count === 1 ? '' : 's'
        }${day.mood ? `, mood ${day.mood}` : ''}`}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="flex w-full items-baseline justify-between gap-3 text-left"
        >
          <span className={`font-serif ${thin ? 'text-sm text-ink-mid' : 'text-base text-ink'}`}>
            {prettyDate(day.local_date)}
          </span>
          <span className="flex shrink-0 items-center gap-2">
            {day.mood && (
              <span className="inline-flex items-center gap-1 rounded-full bg-clay/10 px-2 py-0.5 text-[11px] font-medium text-clay">
                <span className="h-1.5 w-1.5 rounded-full bg-clay" aria-hidden />
                {day.mood}
              </span>
            )}
            <span className="font-mono text-[11px] text-ink-soft">
              {day.event_count > 0 ? `${day.event_count} ev` : 'quiet'}
            </span>
            <span aria-hidden className={`text-ink-soft transition-transform ${expanded ? 'rotate-90' : ''}`}>
              ›
            </span>
          </span>
        </button>

        {/* thin days read quieter — smaller, lower contrast, still honest */}
        <div className={`mt-2 ${thin ? '[&_p]:!text-xs [&_p]:!text-ink-soft' : ''}`}>
          <Markdown text={stripLeadingHeading(day.summary_md)} />
        </div>

        {expanded && detail === 'loading' && (
          <div className="mt-3 space-y-2 border-t border-line pt-3" role="status" aria-label="Loading day detail">
            <div className="h-4 w-2/3 animate-pulse rounded bg-paper-deep" />
            <div className="h-4 w-1/2 animate-pulse rounded bg-paper-deep" />
          </div>
        )}
        {expanded && detail === 'error' && (
          <p className="mt-3 border-t border-line pt-3 text-xs text-ink-soft">
            Couldn’t load this day’s detail just now.
          </p>
        )}
        {expanded && detail && detail !== 'loading' && detail !== 'error' && (
          <DayDetail detail={detail} stepsSeries={stepsSeries} onSaved={onSaved} />
        )}
      </article>
    </li>
  )
}

// ------------------------------------------------------------ trip chapters --
/** Woodblock-minimal torii — the crimson chapter mark for Japan (MEMORY §5).
 * Flat clay ink via currentColor, so both print schemes come free. */
function ToriiMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 40" aria-hidden className={className}>
      <path d="M3 7c13-3.4 29-3.4 42 0l-.8 4.4c-12.5-3.1-27.9-3.1-40.4 0Z" fill="currentColor" />
      <rect x="8.5" y="16" width="31" height="3" fill="currentColor" />
      <rect x="12" y="10.5" width="3.2" height="27.5" fill="currentColor" />
      <rect x="32.8" y="10.5" width="3.2" height="27.5" fill="currentColor" />
      <rect x="22.4" y="10.5" width="3.2" height="5.5" fill="currentColor" />
    </svg>
  )
}

function chapterTitle(trip: DigestRow): string {
  const first = trip.content_md.split('\n')[0] ?? ''
  return first.startsWith('# ') ? first.slice(2).trim() : 'Trip'
}

/** The digest's cover block (everything above its `---` rule) — the body
 * below the rule repeats each day's summary, which the cards already show. */
function chapterCover(trip: DigestRow): string {
  const md = trip.content_md
  const cut = md.indexOf('\n---')
  const cover = cut === -1 ? md : md.slice(0, cut)
  // Drop the `# title` line — the header renders it as the chapter name.
  return cover.split('\n').slice(1).join('\n').trim()
}

function ChapterHeader({ trip, ended }: { trip: DigestRow; ended: boolean }) {
  const title = chapterTitle(trip)
  const japan = title.toLowerCase().includes('japan')
  return (
    <li className="relative scroll-mt-32 pl-9">
      <div className="absolute left-0 top-5 flex w-6 justify-center" aria-hidden>
        <span className="h-3 w-3 rounded-full border-2 border-clay bg-paper" />
      </div>
      <section
        aria-label={`Trip chapter: ${title}`}
        className="rounded-lg border border-l-2 border-line border-l-clay bg-paper-mid p-4"
      >
        <div className="flex items-center gap-3">
          {japan && <ToriiMark className="h-8 w-10 shrink-0 text-clay" />}
          <div>
            <h3 className="font-display text-base font-medium text-ink">{title}</h3>
            <p className="font-mono text-[11px] text-ink-soft">
              {trip.period_start} → {trip.period_end}
            </p>
          </div>
        </div>
        {ended && (
          <div className="mt-3">
            <Markdown text={chapterCover(trip)} />
          </div>
        )}
      </section>
    </li>
  )
}

// ------------------------------------------------------------------ digests --
function WeeklyCard({ digest }: { digest: DigestRow }) {
  return (
    <section
      aria-label="Week in review"
      className="rounded-lg border border-l-2 border-line border-l-clay bg-paper-mid p-4 sm:p-5"
    >
      <Markdown text={digest.content_md} />
    </section>
  )
}

// --------------------------------------------------------------------- page --
function Skeleton() {
  return (
    <div className="space-y-3" aria-label="Loading the journal" role="status">
      {[24, 32, 28, 20, 28].map((h, i) => (
        <div
          key={i}
          className="animate-pulse rounded-lg border border-line bg-paper-mid"
          style={{ height: h * 4 }}
        />
      ))}
    </div>
  )
}

export function JournalPage({ focusDate }: { focusDate?: string | null }) {
  const [days, setDays] = useState<JournalDaySummary[] | null>(null)
  const [digests, setDigests] = useState<DigestRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [details, setDetails] = useState<Record<string, JournalDayDetail | 'loading' | 'error'>>({})
  const focusDone = useRef(false)
  const reduce = useReducedMotion()

  const load = useCallback(() => {
    setError(null)
    Promise.all([fetchJournalRange(isoDaysAgo(RANGE_DAYS), isoDaysAgo(0)), fetchDigests()]).then(
      ([journal, digestRes]) => {
        setDays(journal.days) // server orders newest-first
        setDigests(digestRes.digests)
      },
      (err) => setError(err instanceof Error ? err.message : 'Something went wrong'),
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = useCallback((date: string) => {
    setExpanded((cur) => (cur === date ? null : date))
    setDetails((cur) => {
      if (cur[date]) return cur
      fetchJournalDay(date).then(
        (d) => setDetails((m) => ({ ...m, [date]: d })),
        () => setDetails((m) => ({ ...m, [date]: 'error' })),
      )
      return { ...cur, [date]: 'loading' }
    })
  }, [])

  // Memory-strip hand-off: expand + scroll to the tapped day once loaded.
  useEffect(() => {
    if (!focusDate || !days || focusDone.current) return
    focusDone.current = true
    if (!days.some((d) => d.local_date === focusDate)) return
    if (expanded !== focusDate) openDetail(focusDate)
    requestAnimationFrame(() => {
      document
        .getElementById(`day-${focusDate}`)
        ?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    })
  }, [focusDate, days, expanded, openDetail, reduce])

  // Mood PATCH response folds back into the list + detail cache.
  const onSaved = useCallback((updated: JournalDaySummary) => {
    setDays((cur) => cur?.map((d) => (d.local_date === updated.local_date ? { ...d, ...updated } : d)) ?? cur)
    setDetails((cur) => {
      const existing = cur[updated.local_date]
      if (!existing || existing === 'loading' || existing === 'error') return cur
      return { ...cur, [updated.local_date]: { ...existing, mood: updated.mood } }
    })
  }, [])

  if (error && !days) {
    return (
      <div className="rounded-lg border border-line bg-paper-mid px-5 py-8 text-center text-sm text-ink-soft">
        Couldn’t reach the dyehouse — {error}.{' '}
        <button type="button" onClick={load} className="font-medium text-sky underline underline-offset-2">
          Try again
        </button>
      </div>
    )
  }
  if (!days) return <Skeleton />

  if (days.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-paper-mid px-5 py-10 text-center text-sm text-ink-soft">
        Nothing in the journal yet — days assemble themselves overnight.
      </div>
    )
  }

  const today = isoDaysAgo(0)
  const trips = digests.filter((d) => d.kind === 'trip')
  const tripFor = (date: string) => trips.find((t) => t.period_start <= date && date <= t.period_end)
  // "Week in review" pins while it is the current week's digest (composed
  // Sunday for the week ending that Sunday — MEMORY §3).
  const weekly = digests.find(
    (d) => d.kind === 'weekly' && d.period_end <= today && isoDaysAgo(6) <= d.period_end,
  )

  // 14-day trailing steps series per expanded day, from the already-fetched
  // list (0 steps means "no health data that day" — render as a gap, not 0).
  const asc = [...days].sort((a, b) => (a.local_date < b.local_date ? -1 : 1))
  const stepsSeriesFor = (date: string): (number | null)[] => {
    const idx = asc.findIndex((d) => d.local_date === date)
    if (idx === -1) return []
    return asc.slice(Math.max(0, idx - 13), idx + 1).map((d) => (d.stats.steps ? d.stats.steps : null))
  }

  // Months present, newest first, for the jump-nav.
  const months: string[] = []
  for (const d of days) {
    const m = d.local_date.slice(0, 7)
    if (!months.includes(m)) months.push(m)
  }
  const monthLabel = (m: string, long = false) =>
    new Date(`${m}-15T12:00:00`).toLocaleDateString(
      'en-GB',
      long ? { month: 'long', year: 'numeric' } : { month: 'short', year: '2-digit' },
    )

  // Build the scroll: month markers + chapter headers woven between day cards.
  const items: ReactNode[] = []
  let lastMonth: string | null = null
  let lastTripId: number | null = null
  for (const day of days) {
    const m = day.local_date.slice(0, 7)
    if (m !== lastMonth) {
      lastMonth = m
      items.push(
        <li key={`month-${m}`} className="relative scroll-mt-32 pl-9 pt-1" id={`month-${m}`}>
          <span aria-hidden className="absolute left-0 top-1.5 flex w-6 justify-center">
            <span className="h-2.5 w-2.5 rounded-full border-2 border-liquid bg-paper" />
          </span>
          <h2 className="font-display text-xs font-medium uppercase tracking-[0.08em] text-ink-soft">
            {monthLabel(m, true)}
          </h2>
        </li>,
      )
      lastTripId = null // a fresh month heading restarts the chapter run
    }
    const trip = tripFor(day.local_date)
    if (trip && trip.id !== lastTripId) {
      lastTripId = trip.id
      items.push(<ChapterHeader key={`trip-${trip.id}-${m}`} trip={trip} ended={trip.period_end < today} />)
    } else if (!trip) {
      lastTripId = null
    }
    items.push(
      <DayCard
        key={day.local_date}
        day={day}
        expanded={expanded === day.local_date}
        detail={details[day.local_date]}
        stepsSeries={stepsSeriesFor(day.local_date)}
        onToggle={() => openDetail(day.local_date)}
        onSaved={onSaved}
      />,
    )
  }

  return (
    <div>
      {/* month jump-nav — sticky just below the 57px app header */}
      {months.length > 1 && (
        <nav
          aria-label="Jump to month"
          className="sticky top-[57px] z-10 -mx-1 mb-3 flex gap-1 overflow-x-auto bg-paper/95 px-1 py-2"
        >
          {months.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() =>
                document
                  .getElementById(`month-${m}`)
                  ?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
              }
              className="shrink-0 rounded-full border border-line bg-paper px-3 py-1 text-xs font-medium text-ink-mid transition hover:border-line-strong"
            >
              {monthLabel(m)}
            </button>
          ))}
        </nav>
      )}

      {weekly && <div className="mb-3">{<WeeklyCard digest={weekly} />}</div>}

      <ol className="relative space-y-3">
        {/* the liquid thread (DESIGN §1: liquid is THE connector) */}
        <div aria-hidden className="absolute bottom-2 left-[11px] top-2 w-0.5 rounded bg-liquid" />
        {items}
      </ol>
    </div>
  )
}
