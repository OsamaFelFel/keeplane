import { useState } from 'react'
import { api } from './api'

export function SignOut() {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function signOut() {
    setPending(true)
    setError('')
    try {
      await api('/sign-out', { method: 'POST' })
      window.location.assign('/sign-in')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not sign out. Try again.')
      setPending(false)
    }
  }
  return <><button type="button" className="cursor-pointer underline disabled:opacity-50" disabled={pending} onClick={signOut}>Sign out</button>
    {error && <span role="alert">{error}</span>}</>
}
