import { useState } from 'react'
import { UpdateIcon } from '@radix-ui/react-icons'
import { action, ApiError, definiteRefusal, type User } from '@/app/api'
import { FailureAlert } from '@/components/FailureAlert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

// The server's reasons may lack a closing full stop ("Account not found").
const sentence = (text: string) => /[.!?]$/.test(text) ? text : `${text}.`

export function ChangeRoleDialog({ user, onOpenChange, onChanged }: {
  user: User | null; onOpenChange: (open: boolean) => void; onChanged: (user: User) => void
}) {
  const [role, setRole] = useState<'admin' | 'developer'>(user?.role ?? 'developer')
  const [busy, setBusy] = useState(false)
  // A refusal proves nothing was saved; any other failure leaves the result unknown.
  const [failure, setFailure] = useState<{ refused: boolean; reason: string } | null>(null)
  async function save() {
    if (!user) return
    setBusy(true); setFailure(null)
    try {
      const changed = await action<User>(`/api/users/${user.id}/role`, 'PUT', { role })
      onOpenChange(false); onChanged(changed)
    } catch (cause) {
      if (definiteRefusal(cause)) setFailure({ refused: true, reason: sentence(cause.message) })
      else setFailure({ refused: false, reason: cause instanceof ApiError && cause.status >= 500
        ? "Keeplane couldn't confirm the result." : "Keeplane didn't answer." })
    }
    finally { setBusy(false) }
  }
  return <Dialog open={!!user} onOpenChange={open => { if (!busy) onOpenChange(open) }}>
    <DialogContent showCloseButton={false} onEscapeKeyDown={event => { if (busy) event.preventDefault() }}>
      <DialogHeader><DialogTitle className="text-[22px] font-semibold">Change role</DialogTitle></DialogHeader>
      <p className="text-[15px]">{user?.username}</p>
      <fieldset disabled={busy}><legend className="keeplane-field-label">Role</legend>
        <RadioGroup value={role} onValueChange={value => setRole(value as 'admin' | 'developer')} className="gap-1">
          <div className="flex min-h-9 items-center gap-2.5"><RadioGroupItem value="admin" id="role-admin" className="size-[18px]" /><Label htmlFor="role-admin" className="text-[15px]">Admin</Label></div>
          <div className="flex min-h-9 items-center gap-2.5"><RadioGroupItem value="developer" id="role-developer" className="size-[18px]" /><Label htmlFor="role-developer" className="text-[15px]">Developer</Label></div>
        </RadioGroup>
      </fieldset>
      {failure?.refused && <FailureAlert title={`${user?.username}'s role wasn't changed`}>{failure.reason} Nothing was saved. Check the details and try again.</FailureAlert>}
      {failure && !failure.refused && <FailureAlert title={`It isn't clear whether ${user?.username}'s role was changed`}>{failure.reason} Save the role again to make sure; it won't be changed twice.</FailureAlert>}
      <div className="flex justify-end gap-3"><Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button><Button onClick={save} disabled={busy || role === user?.role}>{busy && <UpdateIcon className="animate-spin" />}Save role</Button></div>
    </DialogContent>
  </Dialog>
}
