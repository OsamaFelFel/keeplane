import { useEffect, useRef, useState, type RefObject } from 'react'
import { action, api, ApiError } from '@/app/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import type { Project, ProjectClass } from './types'

type CurrentClass = { id: string; name: string; classes_enabled?: boolean; data_class?: ProjectClass | null }

export function SetProjectClassDialog({ project, onClose, onSaved, returnFocusRef }: {
  project: Project; onClose: () => void; onSaved: (value: CurrentClass) => void
  returnFocusRef?: RefObject<HTMLButtonElement | null>
}) {
  const [classes, setClasses] = useState<ProjectClass[]>([])
  const [selected, setSelected] = useState(project.data_class?.id ?? '')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [phase, setPhase] = useState<'ready' | 'saving' | 'uncertain' | 'checking'>('ready')
  const pending = useRef<AbortController | null>(null)
  const alive = useRef(true)
  const busy = phase === 'saving' || phase === 'checking'
  const uncertain = phase === 'uncertain'
  useEffect(() => {
    alive.current = true
    const controller = new AbortController()
    api<{ enabled: boolean; classes: ProjectClass[] }>('/api/data-classes', { signal: controller.signal, cache: 'no-store' })
      .then(value => { if (!controller.signal.aborted) {
        if (!value.enabled) setLoadError('Data classes are off. Close this dialog and reload Projects.')
        else setClasses(value.classes)
      } })
      .catch(cause => { if (!controller.signal.aborted) setLoadError(cause.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); alive.current = false; pending.current?.abort() }
  }, [])

  async function save() {
    setPhase('saving'); setError('')
    const controller = new AbortController()
    pending.current = controller
    const timer = window.setTimeout(() => controller.abort(), 10_000)
    try {
      const value = await action<CurrentClass>(`/api/projects/${project.id}/class`, 'PUT', { class_id: selected || null }, controller.signal)
      if (alive.current) onSaved(value)
    } catch (cause) {
      if (!alive.current) return
      if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
        setPhase('ready'); setError(`The class was not saved. ${cause.message}`)
      } else {
        setPhase('uncertain'); setError("It isn't clear whether the class was saved. Keeplane did not confirm the result. Check to find out.")
      }
    } finally { window.clearTimeout(timer); pending.current = null }
  }
  async function check() {
    setPhase('checking'); setError('')
    const controller = new AbortController()
    pending.current = controller
    const timer = window.setTimeout(() => controller.abort(), 10_000)
    try {
      const value = await api<CurrentClass>(`/api/projects/${project.id}/class`, { signal: controller.signal, cache: 'no-store' })
      if (!alive.current) return
      if (!value.classes_enabled) {
        setPhase('uncertain'); setError('Data classes are off. Close this dialog and reload Projects.')
      } else if ((value.data_class?.id ?? '') === selected) onSaved(value)
      else { setPhase('ready'); setError(`The current class is ${value.data_class?.name ?? 'none'}. Review your choice before saving again.`) }
    } catch (cause) {
      if (alive.current) { setPhase('uncertain'); setError(cause instanceof Error ? cause.message : 'Keeplane did not answer.') }
    } finally { window.clearTimeout(timer); pending.current = null }
  }

  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose() }}>
    <DialogContent showCloseButton={false} aria-describedby="project-class-help" onCloseAutoFocus={event => { if (returnFocusRef?.current) { event.preventDefault(); returnFocusRef.current.focus() } }} onEscapeKeyDown={event => { if (busy) event.preventDefault() }}>
      <DialogHeader><DialogTitle className="text-[22px] font-semibold">Data class for {project.name}</DialogTitle></DialogHeader>
      <div><Label htmlFor="project-class" className="keeplane-field-label">Data class</Label>
        <select id="project-class" aria-describedby="project-class-help" className="h-11 w-full rounded-[6px] border border-input bg-background px-3 text-[15px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={selected} onChange={event => setSelected(event.target.value)} disabled={loading || phase !== 'ready' || !!loadError}>
          <option value="">None</option>{classes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <p id="project-class-help" className="mt-2 text-[14px] text-muted-foreground">With a class, only models approved for it appear in the project's allowed models. Repository settings cannot change this class.</p>
      </div>
      {loading && <p role="status">Loading classes…</p>}
      {(loadError || error) && <Alert><AlertDescription>{loadError || error}</AlertDescription></Alert>}
      {busy && <p className="sr-only" role="status">{phase === 'saving' ? 'Saving' : 'Checking'}</p>}
      <div className="flex justify-end gap-3"><Button variant="outline" disabled={busy} onClick={onClose}>Cancel</Button>
        {uncertain || phase === 'checking' ? <Button disabled={busy} onClick={check}>{busy ? 'Checking…' : 'Check'}</Button> :
          <Button disabled={busy || loading || !!loadError || selected === (project.data_class?.id ?? '')} onClick={save}>{busy && <span aria-hidden="true" className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent" />}{busy ? 'Saving…' : 'Save'}</Button>}
      </div>
    </DialogContent>
  </Dialog>
}
