import { useEffect, useState } from 'react'
import { api, action } from '@/app/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

const community = ["Projects, onboarded with init in Keeplane's CLI", 'Workflows and agents',
  "Models and routing, with developers' own keys", 'Data classes and personal-data detection',
  'The audit add-on', 'Sign-in with username and password or single sign-on', "Keeplane's CLI for developers"]
const enterprise = ['Organization-wide rules', 'Teams and access control, with groups mapped from your provider',
  'Governance across all teams', 'An outcome report across teams']

export function EditionsPage() {
  const [enabled, setEnabled] = useState(true)
  const [busy, setBusy] = useState(true)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    api<{ enabled: boolean }>('/api/edition-note').then(result => setEnabled(result.enabled))
      .catch(cause => setError(cause.message)).finally(() => setBusy(false))
  }, [])
  async function change(wanted: boolean) {
    const previous = enabled
    setEnabled(wanted)
    setBusy(true); setError(''); setNotice('')
    try {
      await action('/api/edition-note', 'PUT', { enabled: wanted })
      setEnabled(wanted)
      setNotice(wanted ? 'The note is on.' : 'The note is off.')
    } catch (cause) {
      setEnabled(previous)
      setError(cause instanceof Error ? cause.message : 'Could not save the setting.')
    }
    finally { setBusy(false) }
  }
  return <div className="grid gap-6">
    <div><h1 className="keeplane-page-title">Editions</h1><p className="keeplane-page-description">You are using Keeplane Open Source. It works fully on its own.</p></div>
    {error && <Alert role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
    {notice && <p role="status">{notice}</p>}
    {[{ title: 'Open Source includes', items: community }, { title: 'Enterprise adds', items: enterprise }].map(section =>
      <Card key={section.title}><CardHeader><h2 className="text-lg font-semibold">{section.title}</h2></CardHeader>
        <CardContent><ul className="list-disc space-y-1 pl-5">{section.items.map(item => <li key={item}>{item}</li>)}</ul></CardContent></Card>)}
    <Card><CardHeader><h2 className="text-lg font-semibold">Notes in the web UI</h2></CardHeader><CardContent>
      <label className="flex min-h-11 items-center gap-3"><input type="checkbox" role="switch" checked={enabled}
        disabled={busy} onChange={event => change(event.target.checked)} />Show a note where a feature is part of Enterprise</label>
      <p className="text-sm text-muted-foreground">One plain line, shown once, where you reach something only Enterprise does.</p>
    </CardContent></Card>
    <p>No feature moves from Open Source to Enterprise. The Open Source license stays Apache 2.0.</p>
  </div>
}
