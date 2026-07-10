import { useState } from 'react'
import { get } from '../../api'
import { ageLabel, type SiblingStatus } from '../../dashboard'
import { Tile, TileEmpty } from './Tile'

/** Tile 7 — Dyehouse status (DESIGN §3.7): one row per sibling with the
 * green/kraft/clay dot, snapshot age and latency. Tap expands the
 * /api/status detail (latest sync_runs per source) — the infra-monitor
 * payoff. */

interface StatusDetail {
  sync_runs: { source: string; status: string; started_at: string; items: number; error: string | null }[]
}

const APP_LABELS: Record<string, string> = { michi: 'Michi', kakeibo: 'Kakeibo', mishka: 'Mishka Hub' }

function dotClass(s: SiblingStatus): string {
  if (s.ok === null) return 'bg-cloud' // never polled / not configured
  if (s.ok) return s.age_seconds != null && s.age_seconds > 3600 ? 'bg-kraft' : 'bg-olive'
  return 'bg-clay'
}

function rowSummary(s: SiblingStatus): string {
  const name = APP_LABELS[s.app] ?? s.app
  if (s.ok === null) return `${name}: not configured yet`
  if (!s.ok) return `${name}: unreachable, ${s.consecutive_failures} failed poll${s.consecutive_failures === 1 ? '' : 's'}`
  return `${name}: healthy, checked ${ageLabel(s.age_seconds)}`
}

export function OpsTile({ siblings }: { siblings: SiblingStatus[] }) {
  const [detail, setDetail] = useState<StatusDetail | null>(null)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  async function toggleDetail() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (!detail && !loading) {
      setLoading(true)
      try {
        setDetail(await get<StatusDetail>('/api/status'))
      } catch {
        /* the rows above still stand on their own */
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <Tile
      title="Dyehouse"
      aside={
        <button
          type="button"
          onClick={toggleDetail}
          aria-expanded={open}
          className="min-h-6 text-[11px] font-medium text-sky underline-offset-2 hover:underline"
        >
          {open ? 'less' : 'detail'}
        </button>
      }
    >
      {siblings.length === 0 ? (
        <TileEmpty>No sources reporting yet.</TileEmpty>
      ) : (
        <ul className="space-y-1.5">
          {siblings.map((s) => (
            <li
              key={s.app}
              aria-label={rowSummary(s)}
              className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper px-3 py-2"
            >
              <div className="flex items-center gap-2.5">
                <span className={`h-2 w-2 rounded-full ${dotClass(s)}`} aria-hidden />
                <span className="text-sm font-medium text-ink">{APP_LABELS[s.app] ?? s.app}</span>
                {s.consecutive_failures > 0 && (
                  <span className="rounded-full bg-clay/10 px-1.5 py-0.5 font-mono text-[10px] text-clay">
                    ×{s.consecutive_failures}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 font-mono text-[11px] text-ink-soft">
                {s.latency_ms != null && <span>{s.latency_ms}ms</span>}
                <span>{s.ok === null ? 'not set up' : ageLabel(s.age_seconds)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="mt-3 border-t border-line pt-3">
          {loading && <p className="text-xs text-ink-soft">Checking…</p>}
          {detail && detail.sync_runs.length === 0 && <p className="text-xs text-ink-soft">No sync runs recorded yet.</p>}
          {detail && detail.sync_runs.length > 0 && (
            <ul className="space-y-1 font-mono text-[11px] text-ink-mid">
              {detail.sync_runs.map((r) => (
                <li key={r.source} className="flex items-center justify-between gap-2">
                  <span className="truncate">{r.source}</span>
                  <span
                    className={
                      r.status === 'ok' ? 'text-olive' : r.status === 'not_configured' ? 'text-ink-soft' : 'text-clay'
                    }
                  >
                    {r.status}
                    {r.items > 0 && ` · ${r.items}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Tile>
  )
}
