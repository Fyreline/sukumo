import { useEffect, useState } from 'react'
import { bootstrap, getUser, subscribe, type AuthUser } from './auth'
import { LoginScreen } from './components/LoginScreen'
import { ThemeToggle } from './components/ThemeToggle'
import { VatMark } from './components/VatMark'
import { BridgePage } from './pages/BridgePage'
import { HabitsPage } from './pages/HabitsPage'
import { JournalPage } from './pages/JournalPage'
import { NudgeInbox } from './pages/NudgeInbox'
import { PeoplePage } from './pages/PeoplePage'
import { SettingsPage } from './pages/SettingsPage'

/** Gates the whole app behind the household login (docs/AUTH.md), then the
 * tab shell (Michi's household pattern: desktop header nav + mobile bottom
 * bar). role='partner' gets the slim shell — Bridge (the slim portal
 * variant, server-redacted) + Settings only; Journal/People/Habits are
 * primary-only surfaces (and the server 403s them anyway). */

type Tab = 'bridge' | 'journal' | 'people' | 'habits' | 'nudges' | 'settings'

const PRIMARY_TABS: { id: Tab; label: string }[] = [
  { id: 'bridge', label: 'Bridge' },
  { id: 'journal', label: 'Journal' },
  { id: 'people', label: 'People' },
  { id: 'habits', label: 'Habits' },
  { id: 'nudges', label: 'Nudges' },
  { id: 'settings', label: 'Settings' },
]
const PARTNER_TABS: { id: Tab; label: string }[] = [
  { id: 'bridge', label: 'Bridge' },
  { id: 'settings', label: 'Settings' },
]

function TabIcon({ tab }: { tab: Tab }) {
  const cls = 'h-5 w-5'
  switch (tab) {
    case 'bridge':
      // the vat seen side-on: a tiled dashboard mark
      return (
        <svg viewBox="0 0 20 20" aria-hidden className={cls}>
          <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
            <rect x="3" y="3" width="6" height="6" rx="1" />
            <rect x="11" y="3" width="6" height="9" rx="1" />
            <rect x="3" y="11" width="6" height="6" rx="1" />
            <rect x="11" y="14" width="6" height="3" rx="1" />
          </g>
        </svg>
      )
    case 'journal':
      // the memory thread: pearls on the liquid line
      return (
        <svg viewBox="0 0 20 20" aria-hidden className={cls}>
          <line x1="10" y1="2.5" x2="10" y2="17.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="10" cy="5.5" r="2" fill="currentColor" />
          <circle cx="10" cy="10.5" r="1.4" fill="currentColor" />
          <circle cx="10" cy="15" r="2.4" fill="currentColor" />
        </svg>
      )
    case 'people':
      return (
        <svg viewBox="0 0 20 20" aria-hidden className={cls}>
          <circle cx="10" cy="7" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M4 17c.8-3 3-4.5 6-4.5s5.2 1.5 6 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      )
    case 'habits':
      // hanko stamp
      return (
        <svg viewBox="0 0 20 20" aria-hidden className={cls}>
          <circle cx="10" cy="10" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M7 10.5l2 2 4-4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )
    case 'nudges':
      // a bell — the coach's voice
      return (
        <svg viewBox="0 0 20 20" aria-hidden className={cls}>
          <path
            d="M10 3.2c-2.2 0-3.6 1.7-3.6 4v2.2c0 .9-.4 1.7-1.1 2.3l-.4.4h10.2l-.4-.4a3.1 3.1 0 0 1-1.1-2.3V7.2c0-2.3-1.4-4-3.6-4Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path d="M8.5 14.5a1.6 1.6 0 0 0 3 0" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      )
    case 'settings':
      return (
        <svg viewBox="0 0 20 20" aria-hidden className={cls}>
          <circle cx="10" cy="10" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path
            d="M10 3.5v2M10 14.5v2M3.5 10h2M14.5 10h2M5.4 5.4l1.4 1.4M13.2 13.2l1.4 1.4M14.6 5.4l-1.4 1.4M6.8 13.2l-1.4 1.4"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
        </svg>
      )
  }
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(getUser())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const unsubscribe = subscribe(() => setUser(getUser()))
    bootstrap().finally(() => {
      setUser(getUser())
      setReady(true)
    })
    return unsubscribe
  }, [])

  if (!ready) {
    return <div className="min-h-full bg-paper" />
  }
  if (!user) {
    return <LoginScreen onLoggedIn={() => setUser(getUser())} />
  }
  return <AuthenticatedApp user={user} />
}

function AuthenticatedApp({ user }: { user: AuthUser }) {
  const [tab, setTab] = useState<Tab>('bridge')
  // A memory-strip tap carries its day into the journal; plain tab
  // navigation clears it so the page opens at the top.
  const [journalFocus, setJournalFocus] = useState<string | null>(null)
  const tabs = user.role === 'primary' ? PRIMARY_TABS : PARTNER_TABS

  const go = (next: Tab) => {
    setJournalFocus(null)
    setTab(next)
  }
  const openJournalDay = (date: string) => {
    setJournalFocus(date)
    setTab('journal')
  }

  return (
    <div className="flex min-h-full flex-col bg-paper text-ink">
      <header className="sticky top-0 z-20 border-b border-line bg-paper/95">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-5 py-3">
          <div className="flex items-center gap-2.5">
            <VatMark className="h-8 w-8" />
            <span className="font-display text-lg font-medium tracking-[-0.005em]">
              Sukumo <span className="text-clay">蒅</span>
            </span>
          </div>

          <nav className="hidden items-center gap-1 sm:flex" aria-label="Sections">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => go(t.id)}
                aria-current={tab === t.id ? 'page' : undefined}
                className={`inline-flex items-center gap-1.5 rounded-b-md px-3 py-1.5 text-sm font-medium transition ${
                  tab === t.id ? 'border-b-2 border-clay text-ink' : 'text-ink-mid hover:bg-oat'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <span className="text-sm text-ink-mid">{user.display_name}</span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-6 sm:pb-10 sm:pt-8">
        {tab === 'bridge' && (
          <BridgePage
            onOpenPeople={user.role === 'primary' ? () => go('people') : undefined}
            onOpenNudges={user.role === 'primary' ? () => go('nudges') : undefined}
            onOpenJournal={user.role === 'primary' ? openJournalDay : undefined}
          />
        )}
        {tab === 'journal' && user.role === 'primary' && (
          <JournalPage key={journalFocus ?? 'top'} focusDate={journalFocus} />
        )}
        {tab === 'people' && user.role === 'primary' && <PeoplePage />}
        {tab === 'habits' && user.role === 'primary' && <HabitsPage />}
        {tab === 'nudges' && user.role === 'primary' && <NudgeInbox />}
        {tab === 'settings' && <SettingsPage />}
      </main>

      {/* Mobile bottom bar — 64px of content + the home-indicator inset. The
          inset must ADD to the height, not pad inside a fixed h-16: inside,
          it compresses the 64px row and clips the icons against the top edge
          (seen on the installed PWA, 2026-07-11). */}
      <nav
        className="fixed inset-x-0 bottom-0 z-20 flex h-[calc(4rem+env(safe-area-inset-bottom))] items-stretch border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] sm:hidden"
        aria-label="Sections"
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => go(t.id)}
            aria-current={tab === t.id ? 'page' : undefined}
            className={`relative flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition ${
              tab === t.id ? 'text-clay' : 'text-ink-soft'
            }`}
          >
            <TabIcon tab={t.id} />
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  )
}
