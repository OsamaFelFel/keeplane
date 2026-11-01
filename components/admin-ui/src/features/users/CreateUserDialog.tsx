import { useRef, useState, type RefObject } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { ExclamationTriangleIcon, UpdateIcon } from '@radix-ui/react-icons'
import { api, action, ApiError, type User, type UserOperation } from '@/app/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

const schema = z.object({
  username: z.string().regex(/^[A-Za-z0-9._-]{3,64}$/, 'Use 3–64 letters, numbers, dots, dashes or underscores.'),
  password: z.string().min(12, 'Use at least 12 characters.').max(256),
  role: z.enum(['admin', 'developer']),
})
type Fields = z.infer<typeof schema>

// Only Keeplane's own refusal (4xx), or a request the browser never sent, proves
// nothing was saved. A server or proxy error after sending may follow a commit.
function definiteRefusal(cause: unknown): cause is ApiError {
  if (!(cause instanceof ApiError)) return false
  if (cause.status >= 400 && cause.status < 500) return true
  return cause.status === 0 && cause.message !== 'Keeplane did not answer.'
}

export function CreateUserDialog({ open, onOpenChange, onCreated, returnFocusRef }: {
  open: boolean; onOpenChange: (value: boolean) => void; onCreated: (user: User) => void
  returnFocusRef: RefObject<HTMLButtonElement | null>
}) {
  const [phase, setPhase] = useState<'form' | 'saving' | 'no-answer'>('form')
  // true when Keeplane answered but the answer doesn't confirm the result
  const [unconfirmed, setUnconfirmed] = useState(false)
  const [error, setError] = useState('')
  const [checkError, setCheckError] = useState('')
  const operationId = useRef<string | null>(null)
  const { reset, register, handleSubmit, control, formState: { errors } } = useForm<Fields>({ resolver: zodResolver(schema), defaultValues: { username: '', password: '', role: 'developer' } })

  const username = useWatch({ control, name: "username" })
  const usernameField = register('username')
  const passwordField = register('password')

  function close(value: boolean) {
    if (!value && phase === 'saving') return
    if (!value) {
      reset(); setPhase('form'); setError(''); setCheckError(''); operationId.current = null
    }
    onOpenChange(value)
  }

  async function save(fields: Fields) {
    setError(''); setPhase('saving')
    operationId.current ||= crypto.randomUUID()
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10_000)
    try {
      const user = await action<User>('/api/users', 'POST', { ...fields, operation_id: operationId.current }, controller.signal)
      // An answer that names no user (for example a body cut off at the time limit) proves nothing.
      if (typeof user?.username === 'string') closeAfterSuccess(user)
      else { setUnconfirmed(!controller.signal.aborted); setPhase('no-answer') }
    } catch (cause) {
      if (!controller.signal.aborted && definiteRefusal(cause)) {
        setPhase('form'); setError(cause.message)
      } else {
        setUnconfirmed(!controller.signal.aborted && cause instanceof ApiError && cause.status >= 500)
        setPhase('no-answer')
      }
    } finally { window.clearTimeout(timeout) }
  }

  function closeAfterSuccess(user: User) {
    reset(); setPhase('form'); setError(''); operationId.current = null
    onOpenChange(false); onCreated(user)
  }

  async function check() {
    if (!operationId.current) return
    setCheckError('')
    try {
      const result = await api<UserOperation>(`/api/user-operations/${operationId.current}`)
      if (result.status === 'created' && result.user) closeAfterSuccess(result.user)
      else if (result.status === 'not_found') setPhase('form')
      else setCheckError('Keeplane is still saving. Check again.')
    } catch { setCheckError('Keeplane did not answer. Check again.') }
  }

  return <Dialog open={open} onOpenChange={close}>
    <DialogContent showCloseButton={false} onEscapeKeyDown={event => { if (phase === 'saving') event.preventDefault() }}
      onCloseAutoFocus={event => { event.preventDefault(); returnFocusRef.current?.focus() }}>
      <DialogHeader><DialogTitle className="text-[22px] font-semibold">Create user</DialogTitle></DialogHeader>
      <form onSubmit={event => { void handleSubmit(save)(event) }} className="grid gap-5">
        <div>
          <Label htmlFor="new-username" className="keeplane-field-label">Username</Label>
          <Input id="new-username" autoComplete="off" disabled={phase !== 'form'} aria-invalid={!!errors.username} {...usernameField}
            onChange={event => { void usernameField.onChange(event); if (phase === 'form') operationId.current = null }} />
          {errors.username && <p className="mt-1 text-[14px]" role="alert">{errors.username.message}</p>}
        </div>
        <div>
          <Label htmlFor="new-password" className="keeplane-field-label">Password</Label>
          <Input id="new-password" type="password" autoComplete="new-password" disabled={phase !== 'form'} aria-invalid={!!errors.password} {...passwordField}
            onChange={event => { void passwordField.onChange(event); if (phase === 'form') operationId.current = null }} />
          {errors.password && <p className="mt-1 text-[14px]" role="alert">{errors.password.message}</p>}
        </div>
        <fieldset><legend className="keeplane-field-label">Role</legend>
          <Controller name="role" control={control} render={({ field }) => <RadioGroup value={field.value} onValueChange={value => { field.onChange(value); operationId.current = null }} disabled={phase !== 'form'} className="gap-1">
            <div className="flex min-h-9 items-center gap-2.5"><RadioGroupItem value="admin" id="create-admin" className="size-[18px]" /><Label htmlFor="create-admin" className="text-[15px]">Admin</Label></div>
            <div className="flex min-h-9 items-center gap-2.5"><RadioGroupItem value="developer" id="create-developer" className="size-[18px]" /><Label htmlFor="create-developer" className="text-[15px]">Developer</Label></div>
          </RadioGroup>} />
        </fieldset>
        {phase === 'no-answer' && <Alert className="border-input bg-background p-4"><ExclamationTriangleIcon className="size-5" /><AlertTitle>It isn't clear whether {username} was created</AlertTitle><AlertDescription>{unconfirmed ? "Keeplane couldn't confirm the result. Check to find out." : "Keeplane didn't answer in time. Check to find out."}</AlertDescription></Alert>}
        {error && <Alert className="border-input bg-background p-4"><ExclamationTriangleIcon className="size-5" /><AlertTitle>User wasn't created</AlertTitle><AlertDescription>{error} Nothing was saved. Check the details and try again.</AlertDescription></Alert>}
        {checkError && <p role="alert" className="text-[15px]">{checkError}</p>}
        {phase === 'saving' && <span className="sr-only" role="status">Saving</span>}
        <div className="flex justify-end gap-3">
          <Button type="button" variant="outline" onClick={() => close(false)} disabled={phase === 'saving'}>Cancel</Button>
          {phase === 'no-answer' ? <Button type="button" onClick={check}>Check</Button>
            : <Button type="submit" disabled={phase === 'saving'}>{phase === 'saving' && <UpdateIcon className="animate-spin" />}Create user</Button>}
        </div>
      </form>
    </DialogContent>
  </Dialog>
}
