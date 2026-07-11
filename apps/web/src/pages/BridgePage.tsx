import { useCallback, useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { fetchDashboard, ageLabel, type Dashboard, type SiblingStatus } from '../dashboard'
import { GoalTile } from '../components/tiles/GoalTile'
import { MemoryStripTile } from '../components/tiles/MemoryStripTile'
import { NudgeTile } from '../components/tiles/NudgeTile'
import { OpsTile } from '../components/tiles/OpsTile'
import { PeopleTile } from '../components/tiles/PeopleTile'
import { StreaksTile } from '../components/tiles/StreaksTile'
import { Tile, TileEmpty, StaleChip } from '../components/tiles/Tile'
import { TileBoundary } from '../components/tiles/TileBoundary'
import { AwayChip, TodayTile } from '../components/tiles/TodayTile'
import { VitalsTile } from '../components/tiles/VitalsTile'

/** The Bridge (docs/DESIGN.md §3) — the morning tab: eight tiles in
 * priority order, painted from ONE GET /api/dashboard call. Skeleton
 * shimmer until it lands; a kraft `stale` chip when the service worker
 * served the last-good copy offline; tiles degrade independently and the
 * page never blanks because one source is down.
 *
 * role='partner' renders the slim portal variant — the server has already
 * redacted that response down to siblings + japan (tested server-side), so
 * the slim layout is just presentation over what actually arrived. */

const TILE_RISE = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 } }

function Skeleton() {
  return (
    <div className="space-y-3" aria-label="Loading the bridge" role="status">
      {[28, 40, 44, 32, 32, 28, 36, 20].map((h, i) => (
        <div key={i} className="animate-pulse rounded-lg border border-line bg-paper-mid" style={{ height: h * 4 }} />
      ))}
    </div>
  )
}

/** Partner slim bridge (DESIGN §3, HANDOFF Q9). */
function SlimBridge({ data }: { data: Dashboard }) {
  const michi = data.siblings.find((s) => s.app === 'michi')
  const mishka = data.siblings.find((s) => s.app === 'mishka')
  const streak = (michi?.data?.streak_days as number | undefined) ?? null
  const studied = (michi?.data?.studied_today as boolean | undefined) ?? false
  const recent = (mishka?.data?.recent as { title: string; watched_at: string; rating: number | null }[] | undefined) ?? []

  const links = [
    { label: 'Mishka Hub', href: 'https://fyreline.github.io/MishkaHub/' },
    { label: 'Michi', href: 'https://fyreline.github.io/learningLanguageMachine/' },
    { label: 'Japan 2026', href: 'https://fyreline.github.io/japan-2026/' },
  ]

  return (
    <div className="space-y-3">
      {(data.japan || data.away) && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-l-2 border-line border-l-clay bg-paper-mid p-4">
          {data.japan && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-clay/10 px-2.5 py-1 text-sm font-medium text-clay">
              <span aria-hidden>⛩</span>
              {data.japan.days_to_go === 0 ? 'Japan — it’s on' : `Japan in ${data.japan.days_to_go} days`}
            </span>
          )}
          {data.away && <AwayChip away={data.away} />}
        </div>
      )}

      <Tile title="Your Michi streak" dimmed={michi?.ok === false}>
        {streak == null ? (
          <TileEmpty>Michi hasn’t reported in yet.</TileEmpty>
        ) : (
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-3xl text-ink">{streak}</span>
            <span className="text-sm text-ink-mid">day{streak === 1 ? '' : 's'}</span>
            <span className="ml-2 text-xs text-ink-soft">{studied ? 'studied today ✓' : 'not studied yet today'}</span>
          </div>
        )}
      </Tile>

      <Tile title="Recently on Mishka" dimmed={mishka?.ok === false}>
        {recent.length === 0 ? (
          <TileEmpty>No recent watches on the shelf.</TileEmpty>
        ) : (
          <ul className="space-y-1.5">
            {recent.slice(0, 4).map((r, i) => (
              <li key={i} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate font-serif text-ink">{r.title}</span>
                {r.rating != null && <span className="font-mono text-[11px] text-ink-soft">{r.rating}/5</span>}
              </li>
            ))}
          </ul>
        )}
      </Tile>

      <Tile title="The household apps">
        <div className="flex flex-wrap gap-2">
          {links.map((l) => (
            <a
              key={l.label}
              href={l.href}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 items-center rounded-md border border-line bg-paper px-4 text-sm font-medium text-sky transition hover:border-sky"
            >
              {l.label} ↗
            </a>
          ))}
        </div>
      </Tile>
    </div>
  )
}

export function BridgePage({
  onOpenPeople,
  onOpenNudges,
  onOpenJournal,
}: {
  onOpenPeople?: () => void
  onOpenNudges?: () => void
  onOpenJournal?: (date: string) => void
}) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [stale, setStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reduce = useReducedMotion()

  const load = useCallback((quiet = false) => {
    if (!quiet) setError(null)
    fetchDashboard().then(
      ({ data, stale }) => {
        setData(data)
        setStale(stale)
      },
      (err) => {
        if (!quiet) setError(err instanceof Error ? err.message : 'Something went wrong')
      },
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (error && !data) {
    return (
      <div className="rounded-lg border border-line bg-paper-mid px-5 py-8 text-center text-sm text-ink-soft">
        Couldn’t reach the dyehouse — {error}.{' '}
        <button type="button" onClick={() => load()} className="font-medium text-sky underline underline-offset-2">
          Try again
        </button>
      </div>
    )
  }
  if (!data) return <Skeleton />

  const siblings: SiblingStatus[] = data.siblings ?? []

  if (data.role === 'partner') {
    return (
      <>
        {stale && <StaleBanner generatedAt={data.generated_at} />}
        <SlimBridge data={data} />
      </>
    )
  }

  // The eight tiles, priority order (DESIGN §3) — first-paint rise-in
  // stagger only, <300ms total, honouring prefers-reduced-motion.
  const tiles = [
    <TodayTile key="today" data={data} />,
    <VitalsTile key="vitals" vitals={data.vitals} />,
    <StreaksTile key="streaks" habits={data.habits} onLogged={() => load(true)} />,
    <GoalTile key="goal" goal={data.goal} />,
    <PeopleTile key="people" occasions={data.occasions} onOpenPeople={onOpenPeople ?? (() => undefined)} />,
    <MemoryStripTile key="memory" strip={data.memory_strip} anniversary={data.anniversary} onOpenDay={onOpenJournal} />,
    <OpsTile key="ops" siblings={siblings} />,
    <NudgeTile key="nudges" count={data.nudges_pending} onOpenNudges={onOpenNudges} />,
  ]

  return (
    <>
      {stale && <StaleBanner generatedAt={data.generated_at} />}
      <div className="space-y-3">
        {tiles.map((tile, i) => (
          <motion.div
            key={i}
            initial={reduce ? false : TILE_RISE.initial}
            animate={TILE_RISE.animate}
            transition={{ duration: 0.22, delay: i * 0.03, ease: 'easeOut' }}
          >
            <TileBoundary>{tile}</TileBoundary>
          </motion.div>
        ))}
      </div>
    </>
  )
}

function StaleBanner({ generatedAt }: { generatedAt: string }) {
  // generated_at is naive UTC 'YYYY-MM-DD HH:MM:SS'
  const age = Math.max(0, Math.round((Date.now() - Date.parse(`${generatedAt.replace(' ', 'T')}Z`)) / 1000))
  return (
    <div className="mb-3 flex items-center gap-2 rounded-md border border-kraft/40 bg-kraft/10 px-3 py-2 text-xs text-ink-mid">
      <StaleChip label="offline" />
      <span>Showing the last good view from {ageLabel(age)}.</span>
    </div>
  )
}
