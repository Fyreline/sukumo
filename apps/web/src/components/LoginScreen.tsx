import { useState } from 'react'
import { login } from '../auth'
import { VatMark } from './VatMark'

/** Household sign-in — port of Michi's/Mishka Hub's LoginScreen.tsx styling
 * (docs/DESIGN.md). There is no registration path anywhere: this form only
 * ever has one possible "correct" answer per household member, and the
 * credential is Mishka Hub's own (docs/AUTH.md). */
export function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
      onLoggedIn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-paper px-5 text-ink">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <VatMark className="h-11 w-11" />
          <span className="font-display text-xl font-medium tracking-[-0.005em]">
            Sukumo <span className="text-clay">蒅</span>
          </span>
          <p className="font-serif text-base text-ink-mid">The bridge, one scroll every morning.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="min-h-11 w-full rounded-md border border-line-strong bg-white px-3.5 py-2.5 text-sm text-ink placeholder:text-cloud outline-none focus:border-clay dark:bg-paper-mid"
          />
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="min-h-11 w-full rounded-md border border-line-strong bg-white px-3.5 py-2.5 text-sm text-ink placeholder:text-cloud outline-none focus:border-clay dark:bg-paper-mid"
          />

          {error && <p className="text-sm text-fig">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="min-h-11 w-full rounded-md bg-clay py-2.5 text-sm font-medium text-paper transition hover:bg-clay-deep disabled:opacity-50"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-ink-soft">
          One household login — same email and password as Mishka Hub.
        </p>
      </div>
    </div>
  )
}
