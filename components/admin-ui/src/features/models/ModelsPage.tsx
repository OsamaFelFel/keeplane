import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, action, ApiError } from '@/app/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type ProviderKeyChoice = 'none' | 'shared' | 'personal'
type Model = {
  id: string
  provider: string
  kind: string
  approved?: boolean
  key_choice?: ProviderKeyChoice | null
  developer_key_count?: number
  approved_classes?: string[]
  owned_by_keeplane?: boolean
}
type Level = {
  level: 'simple' | 'standard' | 'complex'
  name: string
  model_id: string | null
  keeplane_pick: string | null
  changed_by_admin: boolean
  admin_model_id: string | null
  admin_model_set_up: boolean | null
}
type Classes = { enabled: boolean; classes: { name: string }[] }
type RunnerModels = { models: string[]; runtime?: Record<string, { active_context_tokens?: number; training_context_tokens?: number }> }

const selectStyle = 'h-11 w-full rounded-[6px] border border-input bg-background px-3 text-[15px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

function ClassChoices({ choices, selected, onChange }: {
  choices: string[]; selected: string[]; onChange: (names: string[]) => void
}) {
  return <fieldset><legend className="keeplane-field-label">Approved for</legend>
    {choices.map(name => <label key={name} className="flex min-h-9 items-center gap-2 text-[15px]">
      <input type="checkbox" checked={selected.includes(name)} onChange={event => onChange(event.target.checked ? [...selected, name] : selected.filter(item => item !== name))} />{name}
    </label>)}
    <p className="text-[14px] leading-5 text-muted-foreground">Projects with no data class can use any model Keeplane has set up.</p>
  </fieldset>
}

export function ModelsPage() {
  const [models, setModels] = useState<Model[] | null>(null)
  const [classes, setClasses] = useState<Classes | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Model | null>(null)
  const [removing, setRemoving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [source, setSource] = useState<'runner' | 'openai' | 'anthropic'>('runner')
  const [runnerAddress, setRunnerAddress] = useState('')
  const [runnerModels, setRunnerModels] = useState<RunnerModels | null>(null)
  const [finding, setFinding] = useState(false)
  const [modelName, setModelName] = useState('')
  const [keyChoice, setKeyChoice] = useState<ProviderKeyChoice>('shared')
  const [sharedKey, setSharedKey] = useState('')
  const [replacementKey, setReplacementKey] = useState('')
  const [approvedClasses, setApprovedClasses] = useState<string[]>([])
  const [levels, setLevels] = useState<Level[]>([])
  const [changingLevel, setChangingLevel] = useState<Level | null>(null)
  const [levelModel, setLevelModel] = useState('')
  const [inUse, setInUse] = useState<{ model: string; levels: string[] } | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [catalog, classListing] = await Promise.all([
        api<{ models: Model[]; levels?: Level[] }>('/api/models'), api<Classes>('/api/data-classes'),
      ])
      setModels(catalog.models.filter(model => model.kind !== 'endpoint-trial' || model.approved !== undefined))
      setLevels(catalog.levels ?? [])
      setClasses(classListing)
      setError('')
      return catalog.models
    } catch (cause) {
      setError((cause as Error).message)
      return []
    }
  }, [])
  // oxlint-disable-next-line react/set-state-in-effect -- Refresh updates state after remote API requests.
  useEffect(() => { void refresh() }, [refresh])

  function openAdd() {
    setDialogError(''); setAdding(true); setSource('runner'); setModelName('')
    setRunnerAddress(''); setRunnerModels(null); setSharedKey(''); setKeyChoice('shared')
    setApprovedClasses([])
  }

  async function findRunner() {
    if (!runnerAddress.trim()) return
    setFinding(true); setDialogError(''); setRunnerModels(null); setModelName('')
    try {
      setRunnerModels(await action<RunnerModels>('/api/runners/models', 'POST', { address: runnerAddress.trim() }))
    } catch (cause) { setDialogError((cause as Error).message) }
    finally { setFinding(false) }
  }

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = modelName.trim()
    setBusy(true); setDialogError('')
    try {
      const result = await action<{ existing?: boolean }>('/api/models', 'POST', {
        name, model: name, source,
        ...(source === 'runner' ? { address: runnerAddress.trim() } : {
          key_choice: keyChoice, ...(keyChoice === 'shared' ? { shared_key: sharedKey } : {}),
        }),
        ...(classes?.enabled ? { approved_classes: approvedClasses } : {}),
      })
      if (result.existing) throw new ApiError(409, `${name} is already added.`)
      setAdding(false); setSharedKey('')
      setNotice(`Added ${name}.`)
      for (const delay of [0, 300, 900, 2000]) {
        if (delay) await new Promise(resolve => setTimeout(resolve, delay))
        if ((await refresh()).some(model => model.id === name)) break
      }
    } catch (cause) { setDialogError(`${name || 'Model'} wasn't added. ${(cause as Error).message}`) }
    finally { setBusy(false) }
  }

  function openEdit(model: Model) {
    setEditing(model); setDialogError(''); setReplacementKey('')
    setApprovedClasses(model.approved_classes || [])
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editing) return
    setBusy(true); setDialogError('')
    try {
      await action(`/api/models/${encodeURIComponent(editing.id)}/setup`, 'POST', {
        key_choice: editing.key_choice ?? 'none',
        ...(classes?.enabled ? { approved_classes: approvedClasses } : {}),
        ...(replacementKey ? { replace_shared_key: replacementKey } : {}),
      })
      setNotice(`${editing.approved ? 'Saved' : 'Set up'} ${editing.id}.`)
      setEditing(null); setReplacementKey('')
      await refresh()
    } catch (cause) { setDialogError((cause as Error).message) }
    finally { setBusy(false) }
  }

  function levelsUsing(modelId: string) {
    return levels.filter(level => level.changed_by_admin && level.admin_model_id === modelId).map(level => level.name)
  }

  function startRemove() {
    if (!editing) return
    setDialogError('')
    const used = levelsUsing(editing.id)
    if (used.length) { setEditing(null); setInUse({ model: editing.id, levels: used }) }
    else setRemoving(true)
  }

  async function remove() {
    if (!editing) return
    setBusy(true); setDialogError('')
    try {
      const result = await api<{ gateway_model_preserved: boolean }>(`/api/models/${encodeURIComponent(editing.id)}/setup`, {
        method: 'DELETE', headers: { 'X-Keeplane-Action': '1' },
      })
      setNotice(result.gateway_model_preserved ? `Removed Keeplane setup for ${editing.id}. The gateway model remains.` :
        `Removed ${editing.id} from Keeplane and the gateway.`)
      setRemoving(false); setEditing(null)
      await refresh()
    } catch (cause) {
      const used = cause instanceof ApiError && cause.status === 409 ? (cause.body.in_use as { levels?: string[] } | undefined)?.levels : undefined
      if (used?.length) {
        // A level was changed to this model after the page loaded.
        setRemoving(false); setInUse({ model: editing.id, levels: used }); setEditing(null)
        void refresh()
      } else setDialogError((cause as Error).message)
    }
    finally { setBusy(false) }
  }

  function openLevel(level: Level) {
    setChangingLevel(level); setDialogError('')
    setLevelModel(level.model_id ?? '')
  }

  async function saveLevel(modelId: string | null) {
    if (!changingLevel) return
    setBusy(true); setDialogError('')
    try {
      const result = await action<{ levels: Level[] }>(`/api/levels/${changingLevel.level}`, 'POST', { model_id: modelId })
      setLevels(result.levels)
      setNotice(modelId ? `${changingLevel.name} now uses ${modelId}.` : `${changingLevel.name} uses Keeplane's pick again.`)
      setChangingLevel(null)
    } catch (cause) { setDialogError((cause as Error).message) }
    finally { setBusy(false) }
  }

  const setUpModels = (models ?? []).filter(model => model.approved === true).map(model => model.id)

  const runtime = runnerModels?.runtime?.[modelName]
  return <>
    <div className="keeplane-page-heading"><div><h1>Models and routing</h1><p>Register the models you use. Keeplane routes each task to a fitting model.</p></div></div>
    {notice && <p className="mt-5 text-[15px]" role="status">{notice}</p>}
    {error && <div className="mt-5 flex flex-wrap items-center gap-3" role="alert">
      <p><strong>The model gateway isn't answering.</strong> Developers' tasks can't reach any model, and models can't be added or changed, until it answers again.</p>
      <Button variant="outline" onClick={() => void refresh()}>Try again</Button>
    </div>}
    <section className="mt-6 rounded-[8px] border border-border bg-card p-5 md:p-6">
      <h2 className="text-[18px] font-semibold">Models</h2>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-4"><p className="text-[15px] text-muted-foreground">Every model you add is registered in the gateway.</p>
        <Button variant="outline" disabled={!!error || !classes} onClick={openAdd}>Add model</Button></div>
      <div className="keeplane-table-frame mt-4" role="region" aria-label="Models table" tabIndex={0}>
        <Table><TableHeader><TableRow><TableHead>Model</TableHead><TableHead>Provider</TableHead><TableHead>Reached</TableHead><TableHead>Key</TableHead>
          {classes?.enabled && <TableHead>Approved for</TableHead>}<TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
          <TableBody>{models === null ? <TableRow><TableCell colSpan={classes?.enabled ? 6 : 5}>Loading models…</TableCell></TableRow> :
            models.length === 0 ? <TableRow><TableCell colSpan={classes?.enabled ? 6 : 5}>No models added yet</TableCell></TableRow> :
            models.map(model => <TableRow key={model.id}>
              <TableCell><span className="font-medium">{model.id}</span>{model.approved === false && <span className="block text-[14px] text-muted-foreground">Added outside Keeplane</span>}</TableCell>
              <TableCell>{model.provider}</TableCell><TableCell>{model.kind === 'cloud' ? 'Cloud' : model.kind === 'unknown' ? 'Unknown' : 'Local'}</TableCell>
              <TableCell>{model.approved === false ? 'Not set' : model.key_choice === 'shared' ? 'Shared' : model.key_choice === 'personal' ? <>
                Each developer's own
                {typeof model.developer_key_count === 'number' && <span className="block text-[14px] leading-5 text-muted-foreground">
                  {model.developer_key_count} {model.developer_key_count === 1 ? 'developer has' : 'developers have'} added a key
                </span>}
              </> : 'None'}</TableCell>
              {classes?.enabled && <TableCell>{model.approved === false ? 'Not set · gets no work' : model.approved_classes?.join(', ') || 'None'}</TableCell>}
              <TableCell>{model.approved !== undefined && <Button variant="link" className="h-6 min-h-6 px-0 text-[15px]" onClick={() => openEdit(model)}>{model.approved ? 'Edit' : 'Set up'}</Button>}</TableCell>
            </TableRow>)}
          </TableBody></Table>
      </div>
      <p className="mt-4 text-[14px] leading-5 text-muted-foreground">A model added outside Keeplane gets no work until you set it up.</p>
    </section>

    <section className="mt-6 rounded-[8px] border border-border bg-card p-5 md:p-6" aria-labelledby="complexity-heading">
      <h2 id="complexity-heading" className="text-[18px] font-semibold">Complexity</h2>
      <p className="mt-4 text-[15px] text-muted-foreground">Keeplane judges each task's complexity and picks a model for each level from the models you add.</p>
      <div className="keeplane-table-frame mt-4" role="region" aria-label="Complexity levels table" tabIndex={0}>
        <Table><TableHeader><TableRow><TableHead>Level</TableHead><TableHead>Model</TableHead><TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
          <TableBody>{models === null ? <TableRow><TableCell colSpan={3}>Loading models…</TableCell></TableRow> :
            levels.map(level => <TableRow key={level.level}>
              <TableCell>{level.name}</TableCell>
              <TableCell>{level.model_id ? <>
                <span className="font-medium">{level.model_id}</span>{level.changed_by_admin && level.admin_model_set_up ? ' · changed by an admin' : " · Keeplane's pick"}
                {level.changed_by_admin && !level.admin_model_set_up && <span className="block text-[14px] leading-5 text-muted-foreground">
                  An admin chose {level.admin_model_id}, which isn't set up now.
                </span>}
              </> : <span className="text-muted-foreground">No model set up yet</span>}</TableCell>
              <TableCell><Button variant="link" className="h-6 min-h-6 px-0 text-[15px]" aria-label={`Change ${level.name}`} disabled={!!error || !setUpModels.length} onClick={() => openLevel(level)}>Change</Button></TableCell>
            </TableRow>)}
          </TableBody></Table>
      </div>
    </section>

    <Dialog open={adding} onOpenChange={open => { if (!open && !busy) setAdding(false) }}>
      <DialogContent showCloseButton={false}><DialogHeader><DialogTitle>Add model</DialogTitle></DialogHeader>
        <form className="grid gap-5" onSubmit={event => void add(event)}>
          <div><Label htmlFor="model-source" className="keeplane-field-label">Provider</Label>
            <select id="model-source" className={selectStyle} value={source} disabled={busy} onChange={event => {
              setSource(event.target.value as typeof source); setModelName(''); setRunnerModels(null); setDialogError('')
            }}><option value="runner">Local runner</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select>
            <p className="mt-1 text-[14px] text-muted-foreground">A cloud provider, or a local runner on your network.</p></div>
          {source === 'runner' ? <>
            <div><Label htmlFor="runner-address" className="keeplane-field-label">Runner address</Label>
              <div className="flex flex-wrap gap-2"><Input id="runner-address" type="url" className="min-w-0 flex-1" required value={runnerAddress} disabled={busy} onChange={event => {
                setRunnerAddress(event.target.value); setRunnerModels(null); setModelName('')
              }} placeholder="http://qwen:8080" /><Button type="button" variant="outline" disabled={finding || busy || !runnerAddress.trim()} onClick={() => void findRunner()}>{finding ? 'Finding…' : 'Find models'}</Button></div></div>
            <div><Label htmlFor="runner-model" className="keeplane-field-label">Model</Label>
              <select id="runner-model" className={selectStyle} value={modelName} required disabled={busy || !runnerModels?.models.length} onChange={event => setModelName(event.target.value)}>
                <option value="">{runnerModels ? 'Choose a model' : 'Find models first'}</option>{runnerModels?.models.map(name => <option key={name} value={name}>{name}</option>)}
              </select>{runtime?.active_context_tokens && <p className="mt-1 text-[14px] text-muted-foreground">Active context: {runtime.active_context_tokens.toLocaleString()} tokens.</p>}</div>
          </> : <>
            <div><Label htmlFor="cloud-model" className="keeplane-field-label">Model</Label><Input id="cloud-model" required maxLength={100} value={modelName} disabled={busy} onChange={event => setModelName(event.target.value)} /></div>
            <fieldset><legend className="keeplane-field-label">Provider key</legend>
              <label className="flex min-h-9 items-center gap-2 text-[15px]"><input type="radio" name="provider-key" checked={keyChoice === 'shared'} disabled={busy} onChange={() => setKeyChoice('shared')} />One shared key for the organization</label>
              <label className="flex min-h-9 items-center gap-2 text-[15px]"><input type="radio" name="provider-key" checked={keyChoice === 'personal'} disabled={busy} onChange={() => setKeyChoice('personal')} />Each developer adds their own key</label>
              <label className="flex min-h-9 items-center gap-2 text-[15px]"><input type="radio" name="provider-key" checked={keyChoice === 'none'} disabled={busy} onChange={() => setKeyChoice('none')} />No key needed</label>
              {keyChoice === 'personal' && <p className="text-[14px] leading-5 text-muted-foreground">Developers add their own keys from the CLI. Keys are never shown again.</p>}
            </fieldset>
            {keyChoice === 'shared' && <div><Label htmlFor="shared-key" className="keeplane-field-label">Shared key</Label><Input id="shared-key" type="password" autoComplete="new-password" required minLength={12} value={sharedKey} disabled={busy} onChange={event => setSharedKey(event.target.value)} /><p className="mt-1 text-[14px] text-muted-foreground">Keys are never shown again.</p></div>}
          </>}
          {classes?.enabled && <ClassChoices choices={classes.classes.map(item => item.name)} selected={approvedClasses} onChange={setApprovedClasses} />}
          {dialogError && <p role="alert" className="text-[15px]">{dialogError}</p>}
          <div className="flex justify-end gap-3"><Button type="button" variant="outline" disabled={busy} onClick={() => setAdding(false)}>Cancel</Button><Button type="submit" disabled={busy || !modelName.trim()}>{busy ? 'Adding…' : 'Add model'}</Button></div>
        </form>
      </DialogContent>
    </Dialog>

    <Dialog open={!!editing} onOpenChange={open => { if (!open && !busy) setEditing(null) }}>
      <DialogContent showCloseButton={false}><DialogHeader><DialogTitle>{editing?.approved ? `Edit ${editing.id}` : `Set up ${editing?.id}`}</DialogTitle></DialogHeader>
        <form className="grid gap-5" onSubmit={event => void save(event)}>
          <p className="text-[15px] text-muted-foreground">{editing?.provider} · {editing?.kind === 'cloud' ? 'Cloud' : 'Local'}. Keeplane checks that the {editing?.key_choice === 'personal' ? 'provider' : 'model'} answers before saving.</p>
          <div><Label className="keeplane-field-label">Provider key</Label><p className="text-[15px]">{editing?.key_choice === 'shared' ? 'Shared key' : editing?.key_choice === 'personal' ? "Each developer adds their own key" : 'No key needed'}</p>
            {editing?.key_choice === 'personal' && <p className="text-[14px] leading-5 text-muted-foreground">Developers add their own keys from the CLI. Keys are never shown again.</p>}</div>
          {editing?.key_choice === 'shared' && editing.owned_by_keeplane && editing.kind === 'cloud' && <div><Label htmlFor="replacement-key" className="keeplane-field-label">Replace shared key</Label><Input id="replacement-key" type="password" autoComplete="new-password" value={replacementKey} disabled={busy} onChange={event => setReplacementKey(event.target.value)} /><p className="mt-1 text-[14px] text-muted-foreground">Leave it empty to keep the current key.</p></div>}
          {classes?.enabled && <ClassChoices choices={classes.classes.map(item => item.name)} selected={approvedClasses} onChange={setApprovedClasses} />}
          {dialogError && <p role="alert" className="text-[15px]">{dialogError}</p>}
          <div className="flex flex-wrap justify-end gap-3">{editing?.approved && <Button type="button" variant="outline" className="mr-auto" disabled={busy} onClick={startRemove}>{editing.owned_by_keeplane ? 'Remove model' : 'Remove setup'}</Button>}
            <Button type="button" variant="outline" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button><Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button></div>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={removing} onOpenChange={open => { if (!open && !busy) setRemoving(false) }}>
      <DialogContent showCloseButton={false}><DialogHeader><DialogTitle>{editing?.owned_by_keeplane ? `Remove ${editing.id}?` : 'Remove Keeplane setup?'}</DialogTitle></DialogHeader>
        <p>Keeplane stops sending work to {editing?.id}{editing?.owned_by_keeplane ? ' and removes it from the gateway.' : '. The model stays in the gateway.'}</p>
        {dialogError && <p role="alert">{dialogError}</p>}
        <div className="flex justify-end gap-3"><Button variant="outline" disabled={busy} onClick={() => setRemoving(false)}>Cancel</Button><Button disabled={busy} onClick={() => void remove()}>{busy ? 'Removing…' : editing?.owned_by_keeplane ? 'Remove model' : 'Remove setup'}</Button></div>
      </DialogContent>
    </Dialog>
    <Dialog open={!!inUse} onOpenChange={open => { if (!open) setInUse(null) }}>
      <DialogContent showCloseButton={false}><DialogHeader><DialogTitle>{inUse?.model} is still in use</DialogTitle></DialogHeader>
        <div className="grid gap-2"><p className="text-[15px]">Routing still sends work to it here:</p>
          <ul className="list-disc pl-5 text-[15px]">{inUse?.levels.map(name => <li key={name}>Complexity level: {name}</li>)}</ul></div>
        <p className="text-[15px]">Move these to another model first, then remove it.</p>
        <div className="flex justify-end gap-3"><Button onClick={() => setInUse(null)}>Close</Button></div>
      </DialogContent>
    </Dialog>
    <Dialog open={!!changingLevel} onOpenChange={open => { if (!open && !busy) setChangingLevel(null) }}>
      <DialogContent showCloseButton={false}><DialogHeader><DialogTitle>Model for {changingLevel?.name}</DialogTitle></DialogHeader>
        <form className="grid gap-5" onSubmit={event => { event.preventDefault(); void saveLevel(levelModel) }}>
          <div><Label htmlFor="level-model" className="keeplane-field-label">Model</Label>
            <select id="level-model" className={selectStyle} value={levelModel} required disabled={busy} onChange={event => setLevelModel(event.target.value)}>
              {!setUpModels.includes(levelModel) && <option value="">Choose a model</option>}
              {setUpModels.map(name => <option key={name} value={name}>{name}</option>)}
            </select>
            {changingLevel?.keeplane_pick && <p className="mt-1 text-[14px] text-muted-foreground">Keeplane's pick is {changingLevel.keeplane_pick}.</p>}</div>
          {dialogError && <p role="alert" className="text-[15px]">{dialogError}</p>}
          <div className="flex flex-wrap justify-between gap-3">
            <Button type="button" variant="outline" disabled={busy || !changingLevel?.changed_by_admin} onClick={() => void saveLevel(null)}>Use Keeplane's pick</Button>
            <div className="ml-auto flex gap-3"><Button type="button" variant="outline" disabled={busy} onClick={() => setChangingLevel(null)}>Cancel</Button>
              <Button type="submit" disabled={busy || !levelModel}>{busy ? 'Saving…' : 'Save'}</Button></div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  </>
}
