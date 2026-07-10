// Types + fetch for GET /api/dashboard — the one aggregate that paints every
// bridge tile (docs/API.md §1). The server composes everything
// (docs/ARCHITECTURE.md §5.4); this module owns only the response types.
import { getWithStale } from './api'

export interface MetricBlock {
  today: number | null
  series: (number | null)[]
}

export interface Vitals {
  series_days: string[]
  steps: MetricBlock
  sleep_hours: MetricBlock
  active_kcal: MetricBlock
  workouts: { this_week: number; series: number[] }
}

export interface HabitState {
  id: number
  key: string
  title: string
  kind: 'auto' | 'tap' | 'hybrid'
  evidence: string | null
  target: { per_week?: number; per_day?: number }
  last_date: string | null
  gap_days: number | null
  done_today: boolean
  week_count: number
  state: 'done_today' | 'ok' | 'due' | 'empty'
  current_book?: { id: number; title: string; author: string | null } | null
}

export interface Goal {
  goal_pence: number | null
  saved_pence: number | null
  pct: number | null
  pace_status: string | null
  as_of: string | null
  age_seconds: number
}

export interface OccasionEntry {
  id: number
  title: string
  kind: string
  date: string
  days_to_go: number
  lead_days: number
  in_lead_window: boolean
  person: { id: number; name: string } | null
  gift_status: 'none' | 'ideas' | 'bought'
}

export interface MemoryDay {
  date: string
  event_count: number
}

export interface SiblingStatus {
  app: 'michi' | 'kakeibo' | 'mishka'
  ok: boolean | null
  age_seconds: number | null
  latency_ms: number | null
  consecutive_failures: number
  data: Record<string, unknown> | null
  data_age_seconds: number | null
}

export interface WeatherDay {
  temp_max: number
  temp_min: number
  precip_prob: number
  weathercode: number
}

export interface Dashboard {
  generated_at: string
  date: string
  role: 'primary' | 'partner'
  siblings: SiblingStatus[]
  japan: { days_to_go: number } | null
  // primary-only sections — the server omits them entirely for role=partner
  // (DESIGN §3 partner portal; enforced server-side, tested server-side).
  briefing?: string | null
  vitals?: Vitals
  habits?: HabitState[]
  goal?: Goal | null
  occasions?: OccasionEntry[]
  memory_strip?: MemoryDay[]
  weather?: { home: WeatherDay | null; office: WeatherDay | null; age_seconds: number } | null
  nudges_pending?: number
}

export function fetchDashboard(): Promise<{ data: Dashboard; stale: boolean }> {
  return getWithStale<Dashboard>('/api/dashboard')
}

/** "just now" / "4m" / "3h" / "2d" — the tile-corner age chip. */
export function ageLabel(seconds: number | null): string {
  if (seconds == null) return '—'
  if (seconds < 90) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}

/** "today" / "yesterday" / "3 days ago" — streak-card gap phrasing. */
export function gapLabel(gapDays: number | null): string {
  if (gapDays == null) return 'no entries yet'
  if (gapDays === 0) return 'today'
  if (gapDays === 1) return 'yesterday'
  return `${gapDays} days ago`
}
