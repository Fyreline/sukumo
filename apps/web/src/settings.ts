// Types + fetch for GET/PATCH /api/settings — the coach's household knobs
// (docs/COACH.md §2). The server (routers/settings.py) owns the read-through
// defaults; this module owns only the response/patch types.
import { get, patch } from './api'

export interface RuleToggle {
  key: string
  enabled: boolean
}

export interface CoachSettings {
  quiet_hours: string // 'HH:MM-HH:MM'
  daily_cap: number
  rules: RuleToggle[]
}

export interface SettingsPatch {
  quiet_hours?: string
  daily_cap?: number
  rules?: Record<string, boolean>
}

export function getCoachSettings(): Promise<CoachSettings> {
  return get<CoachSettings>('/api/settings')
}

export function patchCoachSettings(body: SettingsPatch): Promise<CoachSettings> {
  return patch<CoachSettings>('/api/settings', body)
}

/** Human labels for the rule keys the engine reports (COACH §3). */
export const RULE_LABELS: Record<string, string> = {
  'morning-briefing': 'Morning briefing',
  'gym-day': 'Gym day',
  reading: 'Reading',
  'michi-streak-guard': 'Japanese streak guard',
  'birthday-gift': 'Birthday gifts',
  'office-day': 'Office day',
  'occasion-reminder': 'Occasion reminders',
  'ops:health-sync-stale': 'Health-sync watch',
  'ops:sibling-down': 'Sibling-down watch',
  'goal-milestone': 'House-pot milestones',
  'japan-countdown': 'Japan countdown',
  'low-movement': 'Low-movement nudge',
}
