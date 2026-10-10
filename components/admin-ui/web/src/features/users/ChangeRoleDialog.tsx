import { useEffect, useState } from 'react'
import { ExclamationTriangleIcon, UpdateIcon } from '@radix-ui/react-icons'
import { action, type User } from '@/app/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

export function ChangeRoleDialog({ user, onOpenChange, onChanged }: {
  user: User | null; onOpenChange: (open: boolean) => void; onChanged: (user: User) => void
}) {
  const [role, setRole] = useState<'admin' | 'developer'>('developer')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (user) { setRole(user.role); setError('') } }, [user])
  async function save() {
    if (!user) return
    setBusy(true); setError('')
    try {
      const changed = await action<User>(`/api/users/${user.id}/role`, 'PUT', { role })
      onOpenChange(false); onChanged(changed)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Keeplane did not answer.') }
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
      {error && <Alert className="border-input bg-background p-4"><ExclamationTriangleIcon className="size-5" /><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="flex justify-end gap-3"><Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button><Button onClick={save} disabled={busy || role === user?.role}>{busy && <UpdateIcon className="animate-spin" />}Save role</Button></div>
    </DialogContent>
  </Dialog>
}
