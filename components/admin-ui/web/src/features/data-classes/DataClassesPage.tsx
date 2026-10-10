import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, action } from '@/app/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type DataClass = { id: string; name: string; approved_model_ids: string[]; project_count: number }
type ClassListing = { enabled: boolean; classes: DataClass[] }
type Model = { id: string; approved: boolean }

export function DataClassesPage() {
  const [listing, setListing] = useState<ClassListing | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [editing, setEditing] = useState<DataClass | 'new' | null>(null)
  const [name, setName] = useState('')
  const [approved, setApproved] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dialogError, setDialogError] = useState('')
  const [notice, setNotice] = useState('')
  const [removing, setRemoving] = useState<DataClass | null>(null)

  const refresh = useCallback(async () => {
    try { setListing(await api<ClassListing>('/api/data-classes')); setError('') }
    catch (cause) { setError((cause as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  async function setMode(enabled: boolean) {
    setBusy(true); setError('')
    setListing(current => current && { ...current, enabled })
    try {
      await action('/api/data-classes/mode', 'PUT', { enabled })
      await refresh()
      setNotice(`Data classes turned ${enabled ? 'on' : 'off'}.`)
    } catch (cause) { setError((cause as Error).message); await refresh() }
    finally { setBusy(false) }
  }

  async function openEditor(item: DataClass | 'new') {
    setEditing(item); setDialogError('')
    setName(item === 'new' ? '' : item.name)
    setApproved(item === 'new' ? [] : item.approved_model_ids)
    try {
      const result = await api<{ models: Model[] }>('/api/models')
      setModels(result.models.filter(model => model.approved))
    } catch (cause) { setDialogError((cause as Error).message) }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editing) return
    setBusy(true); setDialogError('')
    try {
      const path = editing === 'new' ? '/api/data-classes' : `/api/data-classes/${encodeURIComponent(editing.id)}`
      await action(path, editing === 'new' ? 'POST' : 'PUT', { name, approved_model_ids: approved })
      setEditing(null); setNotice(editing === 'new' ? `Added ${name}.` : `Saved ${name}.`)
      await refresh()
    } catch (cause) { setDialogError((cause as Error).message) }
    finally { setBusy(false) }
  }

  async function remove() {
    if (!removing) return
    setBusy(true); setDialogError('')
    try {
      await api(`/api/data-classes/${encodeURIComponent(removing.id)}`, {
        method: 'DELETE', headers: { 'X-Keeplane-Action': '1' },
      })
      setNotice(`Removed ${removing.name}.`); setRemoving(null); setEditing(null)
      await refresh()
    } catch (cause) { setDialogError((cause as Error).message) }
    finally { setBusy(false) }
  }

  return <>
    <div className="keeplane-page-heading">
      <div><h1>Data classes</h1><p>A project's work goes only to models approved for its class. Projects with no class can use any model.</p></div>
      {listing?.enabled && <Button disabled={busy} onClick={() => void openEditor('new')}>Add class</Button>}
    </div>
    <div className="mt-6">
      <div className="flex min-h-11 items-center gap-3">
        <input id="use-classes" type="checkbox" role="switch" className="size-[18px] accent-primary" checked={listing?.enabled ?? false}
          disabled={!listing || busy} onChange={event => void setMode(event.target.checked)} />
        <Label htmlFor="use-classes" className="text-[15px] font-medium">Use data classes</Label>
      </div>
      <p className="pl-[30px] text-[14px] leading-5 text-muted-foreground">Off until you turn it on. While off, every project can use every model and nothing asks for a class.</p>
    </div>
    {notice && <p className="mt-5 text-[15px]" role="status">{notice}</p>}
    {error && <p className="mt-5 text-[15px]" role="alert">Data classes could not load. {error}</p>}
    {listing?.enabled && <div className="keeplane-table-frame mt-6" role="region" aria-label="Data classes table" tabIndex={0}>
      <Table><TableHeader><TableRow><TableHead>Class</TableHead><TableHead>Approved models</TableHead><TableHead>Projects</TableHead><TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
        <TableBody>{listing.classes.map(item => <TableRow key={item.id}>
          <TableCell>{item.name}</TableCell><TableCell>{item.approved_model_ids.join(', ') || 'None'}</TableCell>
          <TableCell>{item.project_count}</TableCell><TableCell><Button variant="link" className="h-6 min-h-6 px-0 text-[15px]" onClick={() => void openEditor(item)}>Edit</Button></TableCell>
        </TableRow>)}</TableBody></Table>
    </div>}
    <Dialog open={editing !== null} onOpenChange={open => { if (!open && !busy) setEditing(null) }}>
      <DialogContent><DialogHeader><DialogTitle>{editing === 'new' ? 'Add class' : `Edit ${editing?.name}`}</DialogTitle></DialogHeader>
        <form className="grid gap-5" onSubmit={event => void save(event)}>
          <div><Label htmlFor="class-name" className="keeplane-field-label">Name</Label><Input id="class-name" minLength={2} maxLength={80} required value={name} onChange={event => setName(event.target.value)} /></div>
          <fieldset><legend className="keeplane-field-label">Approved models</legend>
            {models.length ? models.map(model => <label key={model.id} className="flex min-h-9 items-center gap-2 text-[15px]">
              <input type="checkbox" checked={approved.includes(model.id)} onChange={event => setApproved(current => event.target.checked ? [...current, model.id] : current.filter(id => id !== model.id))} />{model.id}
            </label>) : <p className="text-[14px] text-muted-foreground">No models set up yet</p>}
          </fieldset>
          {dialogError && <p role="alert" className="text-[15px]">{dialogError}</p>}
          <div className="flex flex-wrap justify-end gap-3">
            {editing !== 'new' && <Button type="button" variant="outline" className="mr-auto" onClick={() => setRemoving(editing)}>Remove class</Button>}
            <Button type="button" variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button type="submit" disabled={busy || !!dialogError}>{busy ? 'Saving…' : editing === 'new' ? 'Add class' : 'Save'}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={!!removing} onOpenChange={open => { if (!open && !busy) { setRemoving(null); setDialogError('') } }}>
      <DialogContent><DialogHeader><DialogTitle>Remove class?</DialogTitle></DialogHeader>
        <p>Remove {removing?.name}? Its model approvals will be removed. The model setup remains.</p>
        {dialogError && <p role="alert">{dialogError}</p>}
        <div className="flex justify-end gap-3"><Button variant="outline" onClick={() => { setRemoving(null); setDialogError('') }}>Cancel</Button><Button disabled={busy} onClick={() => void remove()}>Remove class</Button></div>
      </DialogContent>
    </Dialog>
  </>
}
