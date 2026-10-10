import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { api, type Identity } from '@/app/api'
import { Shell } from '@/app/Shell'
import { DeveloperPage } from '@/app/DeveloperPage'
import { UsersPage } from '@/features/users/UsersPage'
import { DataClassesPage } from '@/features/data-classes/DataClassesPage'
import { AuditPage } from '@/features/audit/AuditPage'
import { ModelsPage } from '@/features/models/ModelsPage'

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ssoConnected, setSsoConnected] = useState(false)
  useEffect(() => { api<{ sso_connected: boolean }>('/api/auth-options').then(result => setSsoConnected(result.sso_connected)).catch(() => {}) }, [])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true); setError('')
    const fields = Object.fromEntries(new FormData(event.currentTarget))
    try {
      await api('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields) })
      onSignedIn()
    } catch { setError('The username or password is wrong.') }
    finally { setBusy(false) }
  }
  return <main className="flex min-h-svh items-center justify-center p-4">
    <Card className="w-full max-w-[400px] rounded-[10px] border-border bg-card p-8 shadow-none">
      <CardHeader className="p-0 pb-6"><h1 className="text-[24px] font-semibold">Sign in to Keeplane</h1></CardHeader>
      <CardContent className="p-0"><form onSubmit={submit} className="grid gap-5">
        <div><Label htmlFor="username" className="keeplane-field-label">Username</Label><Input id="username" name="username" autoComplete="username" required /></div>
        <div><Label htmlFor="password" className="keeplane-field-label">Password</Label><Input id="password" name="password" type="password" autoComplete="current-password" required /></div>
        {error && <Alert><AlertDescription>{error}</AlertDescription></Alert>}
        <Button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
        {ssoConnected && <a className="text-[15px] underline" href="/api/oidc/start">Sign in with single sign-on</a>}
      </form></CardContent>
    </Card>
  </main>
}

export default function App() {
  const [identity, setIdentity] = useState<Identity | null | undefined>(undefined)
  const refresh = useCallback(() => { api<Identity>('/api/identity').then(setIdentity).catch(() => setIdentity(null)) }, [])
  useEffect(refresh, [refresh])
  if (identity === undefined) return <main className="p-8" role="status">Loading Keeplane…</main>
  if (identity === null) return <SignIn onSignedIn={refresh} />
  if (identity.role === 'developer') return <DeveloperPage identity={identity} />
  const page = window.location.pathname
  return <Shell identity={identity}>{page === '/app/data-classes' ? <DataClassesPage /> : page === '/app/audit' ? <AuditPage /> : page === '/app/models' ? <ModelsPage /> : <UsersPage />}</Shell>
}
