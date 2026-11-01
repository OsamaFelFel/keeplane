import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FailureAlert } from '@/components/FailureAlert'
import { api, ApiError } from '@/app/api'
import mark from '@/assets/keeplane-mark.svg'

export function SignInPage({ onSignedIn }: { onSignedIn: () => void }) {
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
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 401
        ? 'The username or password is wrong.'
        : cause instanceof ApiError ? cause.message : 'Keeplane could not sign you in. Try again.')
    }
    finally { setBusy(false) }
  }
  // Main.dc.html, Main-no-sso.dc.html and Main-failed.dc.html
  return <main className="flex min-h-svh items-center justify-center p-4">
    <Card className="w-full max-w-[400px] gap-5 rounded-[10px] border-border bg-card p-8 shadow-none">
      <CardHeader className="grid gap-1.5 p-0">
        <span className="flex items-center gap-3 text-[20px] font-semibold"><img src={mark} width="40" height="40" alt="" />Keeplane</span>
        <h1 className="m-0 text-[28px] leading-[36px] font-semibold">Sign in</h1>
      </CardHeader>
      <CardContent className="grid gap-5 p-0"><form onSubmit={submit} className="grid gap-5">
        <div><Label htmlFor="username" className="keeplane-field-label">Username</Label><Input id="username" name="username" autoComplete="username" required /></div>
        <div><Label htmlFor="password" className="keeplane-field-label">Password</Label><Input id="password" name="password" type="password" autoComplete="current-password" required /></div>
        {error && <FailureAlert title={error} />}
        <Button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
      </form>
        <p className="m-0 text-[14px] leading-[20px] text-muted-foreground">{ssoConnected
          ? 'No account? Signing in with single sign-on creates one. For a username and password, ask your admin.'
          : 'No account? Ask your admin.'}</p>
        {ssoConnected && <div className="grid border-t border-border pt-5">
          <Button asChild variant="outline"><a href="/api/oidc/start" className="no-underline">Sign in with single sign-on</a></Button>
        </div>}
      </CardContent>
    </Card>
  </main>
}
