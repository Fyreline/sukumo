import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api'

/** Nudge history: pending/snoozed/history + the source tag, snooze/dismiss/
 * action buttons (docs/API.md §1, docs/COACH.md §2, docs/phases/PHASE-5-notify.md).
 * Primary-only — the server 403s any partner request (COACH.md §1: "the
 * coach only nudges 'primary' at v1"), mirrored here by only ever routing
 * this page for the primary role (App.tsx). */

interface NudgeRow {
  id: number
  rule_key: string
  scheduled_for: string
  sent_at: string | null
  channel: string
  title: string
  body: string
  status: 'pending' | 'sent' | 'snoozed' | 'dismissed' | 'actioned' | 'expired'
  snoozed_until: string | null
  created_at: string
}

const quietButtonCls =
  'min-h-11 rounded-full border border-line-strong px-2.5 text-xs font-medium text-ink-mid transition hover:border-clay hover:text-clay disabled:opacity-50'
const primaryButtonCls =
  'min-h-11 rounded-full bg-clay px-3 text-xs font-medium text-paper transition hover:bg-clay-deep disabled:opacity-50'

/** 'bus:michi-bus' -> 'michi-bus'; 'gym-day' -> 'gym-day' — the household
 * source tag on each card, so a bus message reads distinctly from a coach
 * rule once Phase 6 lands. */
function sourceTag(ruleKey: string): string {
  return ruleKey.startsWith('bus:') ? ruleKey.slice(4) : ruleKey
}

function relativeAge(iso: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - Date.parse(`${iso.replace(' ', 'T')}Z`)
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 90) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}

const STATUS_STYLE: Record<NudgeRow['status'], string> = {
  pending: 'bg-sky/15 text-sky',
  sent: 'bg-sky/15 text-sky',
  snoozed: 'bg-kraft/15 text-kraft',
  dismissed: 'bg-oat text-ink-mid',
  actioned: 'bg-olive/15 text-olive',
  expired: 'bg-oat text-ink-soft',
}

function NudgeCard({ nudge, onChanged }: { nudge: NudgeRow; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const live = nudge.status === 'pending' || nudge.status === 'sent' || nudge.status === 'snoozed'

  async function act(action: 'action' | 'dismiss', body?: unknown) {
    setBusy(action)
    try {
      await post(`/api/nudges/${nudge.id}/${action}`, body ?? {})
      onChanged()
    } catch {
      /* quiet — the card just stays as-is */
    } finally {
      setBusy(null)
    }
  }

  async function snooze(option: '3h' | 'tomorrow' | 'next-week') {
    setBusy(`snooze:${option}`)
    try {
      await post(`/api/nudges/${nudge.id}/snooze`, { option })
      onChanged()
    } catch {
      /* quiet */
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className="rounded-lg border border-line bg-paper-mid p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-sm font-medium text-ink">{nudge.title}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[nudge.status]}`}>
              {nudge.status}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-mid">{nudge.body}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-soft">
            <span className="rounded-full border border-line px-2 py-0.5 font-mono">{sourceTag(nudge.rule_key)}</span>
            <span>{relativeAge(nudge.sent_at ?? nudge.created_at)}</span>
            {nudge.status === 'snoozed' && nudge.snoozed_until && (
              <span>until {relativeAge(nudge.snoozed_until) === 'just now' ? 'soon' : nudge.snoozed_until}</span>
            )}
          </div>
        </div>
      </div>

      {live && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <button type="button" disabled={busy !== null} onClick={() => act('action')} className={primaryButtonCls}>
            {busy === 'action' ? '…' : 'done'}
          </button>
          <button type="button" disabled={busy !== null} onClick={() => snooze('3h')} className={quietButtonCls}>
            {busy === 'snooze:3h' ? '…' : 'snooze 3h'}
          </button>
          <button type="button" disabled={busy !== null} onClick={() => snooze('tomorrow')} className={quietButtonCls}>
            {busy === 'snooze:tomorrow' ? '…' : 'tomorrow'}
          </button>
          <button type="button" disabled={busy !== null} onClick={() => snooze('next-week')} className={quietButtonCls}>
            {busy === 'snooze:next-week' ? '…' : 'next week'}
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => act('dismiss')}
            className="min-h-8 px-1.5 text-xs text-ink-soft hover:text-ink"
          >
            {busy === 'dismiss' ? '…' : 'dismiss'}
          </button>
        </div>
      )}
    </li>
  )
}

const TABS: { id: 'active' | 'history'; label: string }[] = [
  { id: 'active', label: 'Pending & snoozed' },
  { id: 'history', label: 'History' },
]

export function NudgeInbox() {
  const [nudges, setNudges] = useState<NudgeRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'active' | 'history'>('active')

  const load = useCallback(() => {
    get<NudgeRow[]>('/api/nudges').then(setNudges, (err) => setError(err instanceof Error ? err.message : 'failed'))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (error) {
    return <p className="rounded-lg border border-line bg-paper-mid p-5 text-sm text-ink-soft">Couldn’t load nudges — {error}</p>
  }
  if (nudges === null) {
    return <div className="h-40 animate-pulse rounded-lg border border-line bg-paper-mid" role="status" aria-label="Loading nudges" />
  }

  const active = nudges.filter((n) => n.status === 'pending' || n.status === 'sent' || n.status === 'snoozed')
  const history = nudges.filter((n) => n.status === 'dismissed' || n.status === 'actioned' || n.status === 'expired')
  const shown = tab === 'active' ? active : history

  return (
    <div className="space-y-4">
      <nav className="flex gap-1" aria-label="Nudge sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? 'page' : undefined}
            className={`min-h-9 rounded-full px-3 text-sm font-medium transition ${
              tab === t.id ? 'bg-clay text-paper' : 'border border-line-strong text-ink-mid hover:border-clay hover:text-clay'
            }`}
          >
            {t.label} {t.id === 'active' && active.length > 0 && `(${active.length})`}
          </button>
        ))}
      </nav>

      {shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong px-5 py-8 text-center text-sm text-ink-soft">
          {tab === 'active' ? 'Nothing waiting — you’re caught up.' : 'No history yet.'}
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((n) => (
            <NudgeCard key={n.id} nudge={n} onChanged={load} />
          ))}
        </ul>
      )}
    </div>
  )
}
