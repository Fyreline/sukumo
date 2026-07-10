// Types + fetchers for the journal read API (docs/MEMORY.md §5, docs/API.md,
// apps/server/app/routers/journal.py). Every route is primary-only — the
// server 403s role='partner', and App.tsx never routes the tab for them.
// Assembly is a server-side job: this surface is reads plus the single
// optional ``mood`` tap (the ONE human input on the whole page).
import { get, patch } from './api'

export type Mood = 'great' | 'good' | 'ok' | 'low' | 'rough'

/** stats_json as assembled (memory/assemble.py) — all fields optional so a
 * future assembler slot never breaks the page. */
export interface JournalStats {
  steps?: number
  workouts?: number
  study?: boolean
  study_streak?: number | null
  films?: number
  photos?: number
  places?: number
  calendar?: number
  milestones?: number
  events?: number
}

/** A day as returned by GET /api/journal?from=&to= (no events in the list). */
export interface JournalDaySummary {
  local_date: string
  assembled_at: string
  summary_md: string
  stats: JournalStats
  event_count: number
  mood: Mood | null
}

export interface JournalEvent {
  kind: string // workout | study | calendar | place | film | photo | finance | milestone | manual
  ts: string // naive UTC 'YYYY-MM-DD HH:MM:SS'
  title: string
  detail: Record<string, unknown>
  source: string
}

export interface AnniversaryHit {
  local_date: string
  years_ago: number
  summary_md: string
  stats: JournalStats
}

/** GET /api/journal/{date} — the day plus its events and anniversary hits. */
export interface JournalDayDetail extends JournalDaySummary {
  events: JournalEvent[]
  anniversary: AnniversaryHit[]
}

export interface DigestRow {
  id: number
  kind: 'weekly' | 'trip'
  period_start: string
  period_end: string
  content_md: string
  sent_at: string | null
}

export function fetchJournalRange(from: string, to: string): Promise<{ days: JournalDaySummary[] }> {
  return get<{ days: JournalDaySummary[] }>(`/api/journal?from=${from}&to=${to}`)
}

export function fetchJournalDay(date: string): Promise<JournalDayDetail> {
  return get<JournalDayDetail>(`/api/journal/${date}`)
}

/** The one input: set or clear the day's mood. Returns the updated day. */
export function patchMood(date: string, mood: Mood | null): Promise<JournalDaySummary> {
  return patch<JournalDaySummary>(`/api/journal/${date}`, { mood })
}

export function fetchDigests(): Promise<{ digests: DigestRow[] }> {
  return get<{ digests: DigestRow[] }>('/api/digests')
}

/** Assembly's deterministic slot order (memory/assemble.py _KIND_ORDER) —
 * reused so grouped events and pearls read in the same order everywhere. */
export const KIND_ORDER = [
  'workout',
  'study',
  'calendar',
  'place',
  'film',
  'photo',
  'finance',
  'milestone',
  'manual',
] as const

export const KIND_LABEL: Record<string, string> = {
  workout: 'Workouts',
  study: 'Study',
  calendar: 'Calendar',
  place: 'Places',
  film: 'Films',
  photo: 'Photos',
  finance: 'Money',
  milestone: 'Milestones',
  manual: 'Notes',
}

/** "Friday 4 July" from a local YYYY-MM-DD (noon guard avoids TZ day-shift). */
export function prettyDate(localDate: string): string {
  return new Date(`${localDate}T12:00:00`).toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

/** Local HH:MM from a naive-UTC event timestamp. */
export function eventTime(ts: string): string {
  return new Date(`${ts.replace(' ', 'T')}Z`).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** The journal's Photos hand-off (MEMORY §2: metadata only, the journal
 * links INTO Photos). No public time-range URL scheme exists yet, so this
 * opens the Photos app; swap in the documented range link when the photo
 * mapper lands (HANDOFF Q4). */
export function photosDeepLink(_localDate: string): string {
  return 'photos-redirect://'
}
