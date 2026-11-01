import { useState } from 'react'
import { UpdateIcon } from '@radix-ui/react-icons'
import { api, action, ApiError, definiteRefusal, type User, type UserPage } from '@/app/api'
import { FailureAlert } from '@/components/FailureAlert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

type Role = User['role']

// The server's reasons may lack a closing full stop ("Account not found").
const sentence = (text: string) => /[.!?]$/.test(text) ? text : `${text}.`

// Reads the user's current account back from Users. The search matches parts of
// usernames, so it pages through the matches until it finds this user's ID.
async function readBack(user: User): Promise<User | null> {
  for (let page = 1; page <= 200; page += 1) {
    const params = new URLSearchParams({ page: String(page), page_size: '50', search: user.username })
    const result = await api<UserPage>(`/api/users?${params}`)
    const found = result.users.find(row => row.id === user.id)
    if (found) return found
    if (!result.has_more) return null
  }
  return null
}

export function ChangeRoleDialog({ user, onOpenChange, onChanged }: {
  user: User | null; onOpenChange: (open: boolean) => void; onChanged: (user: User) => void
}) {
  const [role, setRole] = useState<Role>(user?.role ?? 'developer')
  const [phase, setPhase] = useState<'form' | 'saving' | 'no-answer'>('form')
  // true when Keeplane answered but the answer doesn't confirm the result
  const [unconfirmed, setUnconfirmed] = useState(false)
  // Keeplane's reason when it answered and refused, so nothing was saved
  const [refusal, setRefusal] = useState('')
  const [checkError, setCheckError] = useState('')

  function close(open: boolean) {
    if (!open && phase === 'saving') return
    onOpenChange(open)
  }

  function done(changed: User) {
    onOpenChange(false); onChanged(changed)
  }

  async function save() {
    if (!user) return
    setRefusal(''); setCheckError(''); setPhase('saving')
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10_000)
    try {
      const changed = await action<User>(`/api/users/${user.id}/role`, 'PUT', { role }, controller.signal)
      // An answer that doesn't name this user with the new role proves nothing.
      if (changed?.id === user.id && changed.role === role) done(changed)
      else { setUnconfirmed(!controller.signal.aborted); setPhase('no-answer') }
    } catch (cause) {
      if (!controller.signal.aborted && definiteRefusal(cause)) {
        setPhase('form'); setRefusal(sentence(cause.message))
      } else {
        setUnconfirmed(!controller.signal.aborted && cause instanceof ApiError && cause.status >= 500)
        setPhase('no-answer')
      }
    } finally { window.clearTimeout(timeout) }
  }

  // Check reads the role back: the requested role means the change was made;
  // anything else brings the form back with the chosen role.
  async function check() {
    if (!user) return
    setCheckError('')
    try {
      const current = await readBack(user)
      if (current && current.role === role) done(current)
      else setPhase('form')
    } catch { setCheckError('Keeplane did not answer. Check again.') }
  }

  const username = user?.username
  return <Dialog open={!!user} onOpenChange={close}>
    <DialogContent showCloseButton={false} onEscapeKeyDown={event => { if (phase === 'saving') event.preventDefault() }}>
      <DialogHeader><DialogTitle className="text-[22px] font-semibold">Change role</DialogTitle></DialogHeader>
      <fieldset disabled={phase !== 'form'}>
        <legend className="keeplane-field-label wrap-anywhere">Role for <span className="text-muted-foreground">{username}</span></legend>
        <RadioGroup value={role} onValueChange={value => setRole(value as Role)} disabled={phase !== 'form'} className="gap-1">
          <div className="flex min-h-9 items-center gap-2.5"><RadioGroupItem value="admin" id="role-admin" className="size-[18px]" /><Label htmlFor="role-admin" className="text-[15px]">Admin</Label></div>
          <div className="flex min-h-9 items-center gap-2.5"><RadioGroupItem value="developer" id="role-developer" className="size-[18px]" /><Label htmlFor="role-developer" className="text-[15px]">Developer</Label></div>
        </RadioGroup>
      </fieldset>
      {phase === 'no-answer' && <FailureAlert title={`It isn't clear whether ${username}'s role was changed`}>{unconfirmed ? "Keeplane couldn't confirm the result. Check to find out." : "Keeplane didn't answer in time. Check to find out."}</FailureAlert>}
      {refusal && phase === 'form' && <FailureAlert title={`${username}'s role wasn't changed`}>{refusal} Nothing was saved. Check the details and try again.</FailureAlert>}
      {checkError && <p role="alert" className="text-[15px]">{checkError}</p>}
      {phase === 'saving' && <span className="sr-only" role="status">Saving</span>}
      <div className="flex justify-end gap-3">
        <Button variant="outline" onClick={() => close(false)} disabled={phase === 'saving'}>Cancel</Button>
        {phase === 'no-answer' ? <Button onClick={check}>Check</Button>
          : <Button onClick={save} disabled={phase === 'saving' || role === user?.role}>{phase === 'saving' && <UpdateIcon className="animate-spin" />}Change role</Button>}
      </div>
    </DialogContent>
  </Dialog>
}
