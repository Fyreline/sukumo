import { useEffect, useState } from 'react'
import { bootstrap, getUser, subscribe, type AuthUser } from './auth'
import { LoginScreen } from './components/LoginScreen'
import { ThemeToggle } from './components/ThemeToggle'
import { VatMark } from './components/VatMark'
import { BridgePage } from './pages/BridgePage'

/** Gates the whole app behind the household login (docs/AUTH.md).
 * `bootstrap()` tries a silent refresh from a stored refresh token on first
 * mount so a page reload doesn't force a re-login; `subscribe()` re-renders
 * this the moment auth state changes. Port of Michi's/Mishka Hub's App.tsx
 * gate, trimmed to Phase 1's single BridgePage stub
 * (docs/phases/PHASE-1-scaffold.md) — the tab switch + full shell (Journal,
 * People, Habits, Nudges, Settings) is Fable-built in later phases. */
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
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <span className="text-sm text-ink-mid">{user.display_name}</span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 pb-10 pt-8">
        <BridgePage />
      </main>
    </div>
  )
}
