import { useEffect, useMemo, useState } from 'react'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { api, action } from '@/app/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type OptionalKind = 'settings' | 'held_requests' | 'model_answers'
type Kind = 'all' | OptionalKind | 'break_glass_sign_ins'
type Options = Record<OptionalKind, boolean>
type RecordRow = { id: number; kind: Kind; when: string; who: string; what: string }
type RecordPage = { records: RecordRow[]; total: number; page: number; page_size: number; has_more: boolean }

const controls: { kind: OptionalKind; label: string; description: string }[] = [
  { kind: 'settings', label: 'Changes to models, routing and data classes', description: 'Who changed what, and when.' },
  { kind: 'held_requests', label: 'Requests held back by personal-data detection', description: 'Which request, whose, and the class it was handled as.' },
  { kind: 'model_answers', label: 'Which model answered each task', description: 'The model, the developer and the project.' },
]

export function AuditPage() {
  const [options, setOptions] = useState<Options | null>(null)
  const [changing, setChanging] = useState<OptionalKind | null>(null)
  const [optionError, setOptionError] = useState('')
  const [notice, setNotice] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<RecordPage | null>(null)
  const [recordsError, setRecordsError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => { api<{ options: Options }>('/api/audit/options')
    .then(value => setOptions(value.options)).catch(cause => setOptionError((cause as Error).message)) }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 250)
    return () => window.clearTimeout(timer)
  }, [searchInput])
  useEffect(() => {
    let cancelled = false
    setLoading(true); setRecordsError(''); setResult(null)
    const params = new URLSearchParams({ page: String(page), kind, search })
    api<RecordPage>(`/api/audit/records?${params}`).then(value => { if (!cancelled) setResult(value) })
      .catch(cause => { if (!cancelled) setRecordsError((cause as Error).message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [page, kind, search])

  async function setOption(option: OptionalKind, enabled: boolean) {
    if (!options) return
    setChanging(option); setOptionError(''); setNotice('')
    setOptions(current => current && { ...current, [option]: enabled })
    try {
      const result = await action<{ options: Options }>(`/api/audit/options/${option}`, 'PUT', { enabled })
      setOptions(result.options)
      setNotice(enabled ? 'Recording turned on.' : 'Recording turned off.')
    } catch (cause) {
      setOptions(current => current && { ...current, [option]: !enabled })
      setOptionError((cause as Error).message)
      try { setOptions((await api<{ options: Options }>('/api/audit/options')).options) }
      catch { /* Keep the last confirmed switch state until the service answers. */ }
    } finally { setChanging(null) }
  }

  const columns = useMemo<ColumnDef<RecordRow>[]>(() => [
    { accessorKey: 'when', header: 'When', cell: ({ row }) => {
      const date = new Date(row.original.when)
      return Number.isNaN(date.valueOf()) ? row.original.when : date.toLocaleString()
    } },
    { accessorKey: 'who', header: 'Who' },
    { accessorKey: 'what', header: 'What' },
  ], [])
  const table = useReactTable({ data: result?.records ?? [], columns, getCoreRowModel: getCoreRowModel() })
  const first = result?.total ? (result.page - 1) * result.page_size + 1 : 0
  const last = result?.total ? Math.min(result.page * result.page_size, result.total) : 0

  return <>
    <div className="keeplane-page-heading"><div><h1>Audit</h1><p>Turn on what your organization wants recorded, then search the records.</p></div></div>
    {notice && <p className="mt-5 text-[15px]" role="status">{notice}</p>}
    {optionError && <p className="mt-5 text-[15px]" role="alert">Audit options could not be changed. {optionError}</p>}
    <section className="mt-6 rounded-[8px] border border-border bg-card px-6 py-5" aria-labelledby="audit-options-title">
      <h2 id="audit-options-title" className="text-[18px] font-semibold">What is recorded</h2>
      <p className="mt-3 text-[15px] text-muted-foreground">Break-glass sign-ins are always recorded. The rest are off until you turn them on.</p>
      <div className="mt-3 grid gap-3">
        {controls.map(control => <div key={control.kind}>
          <div className="flex min-h-11 items-center gap-2.5">
            <input id={`rec-${control.kind}`} type="checkbox" role="switch" className="size-[18px] accent-primary"
              checked={options?.[control.kind] ?? false} disabled={!options || changing !== null}
              onChange={event => void setOption(control.kind, event.target.checked)} />
            <Label htmlFor={`rec-${control.kind}`} className="text-[15px]">{control.label}</Label>
          </div>
          <p className="pl-7 text-[14px] leading-5 text-muted-foreground">{control.description}</p>
        </div>)}
        <div>
          <div className="flex min-h-11 items-center gap-2.5">
            <input id="rec-breakglass" type="checkbox" role="switch" className="size-[18px] accent-primary" checked disabled readOnly />
            <Label htmlFor="rec-breakglass" className="text-[15px]">Sign-ins with the break-glass admin</Label>
          </div>
          <p className="pl-7 text-[14px] leading-5 text-muted-foreground">When someone signed in with it.</p>
        </div>
      </div>
    </section>
    <section className="mt-6" aria-labelledby="records-title">
      <h2 id="records-title" className="text-[18px] font-semibold">Records</h2>
      {recordsError && <p className="mt-3 text-[15px]" role="alert">Records could not load. {recordsError}</p>}
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-[1_1_280px]"><Label htmlFor="search-records" className="keeplane-field-label">Search records</Label>
          <Input id="search-records" type="search" maxLength={80} value={searchInput} onChange={event => setSearchInput(event.target.value)} /></div>
        <div className="min-w-0 flex-[0_1_240px]"><Label htmlFor="record-kind" className="keeplane-field-label">Show</Label>
          <select id="record-kind" className="h-11 w-full rounded-[6px] border border-input bg-card px-3 text-[15px] focus-visible:outline-2 focus-visible:outline-ring" value={kind}
            onChange={event => { setKind(event.target.value as Kind); setPage(1) }}>
            <option value="all">All records</option><option value="settings">Settings changes</option>
            <option value="held_requests">Held-back requests</option><option value="model_answers">Model answers</option>
            <option value="break_glass_sign_ins">Break-glass sign-ins</option>
          </select></div>
      </div>
      <div className="keeplane-table-frame mt-4" role="region" aria-label="Audit records table" tabIndex={0}>
        <Table><TableHeader>{table.getHeaderGroups().map(group => <TableRow key={group.id}>
          {group.headers.map(header => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}
        </TableRow>)}</TableHeader><TableBody>
          {loading ? <TableRow><TableCell colSpan={3}>Loading records…</TableCell></TableRow>
            : !result?.records.length ? <TableRow><TableCell colSpan={3}>No records found.</TableCell></TableRow>
              : table.getRowModel().rows.map(row => <TableRow key={row.id}>{row.getVisibleCells().map(cell =>
                <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>)}
        </TableBody></Table>
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-4 text-[14px] text-muted-foreground">
        <span>Showing {first}–{last} of {result?.total ?? 0} records</span>
        <div className="flex gap-3"><Button variant="outline" disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>Previous</Button>
          <Button variant="outline" disabled={loading || !result?.has_more} onClick={() => setPage(value => value + 1)}>Next</Button></div>
      </div>
    </section>
  </>
}
