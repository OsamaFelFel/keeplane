import { useEffect, useMemo, useRef, useState } from 'react'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { api } from '@/app/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Project, ProjectPage } from './types'
import { SetProjectClassDialog } from './SetProjectClassDialog'

const EMPTY_PROJECTS: Project[] = []

export function ProjectsPage() {
  const [result, setResult] = useState<ProjectPage | null>(null)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [changing, setChanging] = useState<Project | null>(null)
  const [notice, setNotice] = useState('')
  const classTrigger = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    const next = searchInput.trim()
    if (next === search) return
    const timer = window.setTimeout(() => { setSearch(next); setPage(1) }, 250)
    return () => window.clearTimeout(timer)
  }, [searchInput, search])
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError('')
    const params = new URLSearchParams({ page: String(page), page_size: '25', search })
    api<ProjectPage>(`/api/projects?${params}`, { signal: controller.signal, cache: 'no-store' })
      .then(value => { if (!controller.signal.aborted) setResult(value) })
      .catch(cause => { if (!controller.signal.aborted) { setResult(null); setError(cause.message) } })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [page, search])
  const columns = useMemo<ColumnDef<Project>[]>(() => [
    { accessorKey: 'name', header: 'Project' },
    { accessorKey: 'initialized', header: 'Initialised', cell: ({ row }) => row.original.initialized ? 'Yes' : 'Not yet' },
    { id: 'users', header: 'Used by', cell: ({ row }) => row.original.users.map(user => user.username).join(', ') || 'No recorded users' },
    ...(result?.classes_enabled ? [{ id: 'data_class', header: 'Data class', cell: ({ row }: { row: { original: Project } }) => row.original.data_class?.name || 'None' }] : []),
    ...(result?.classes_enabled ? [{ id: 'actions', header: () => <span className="sr-only">Actions</span>, cell: ({ row }: { row: { original: Project } }) => <Button variant="link" className="h-6 min-h-6 px-0 text-[15px]" onClick={event => { classTrigger.current = event.currentTarget; setChanging(row.original) }}>Set class</Button> }] : []),
  ], [result?.classes_enabled])
  // oxlint-disable-next-line react/incompatible-library -- React Compiler is not enabled.
  const table = useReactTable({ data: result?.projects ?? EMPTY_PROJECTS, columns, getCoreRowModel: getCoreRowModel() })
  const total = result?.total ?? 0
  const start = total ? (page - 1) * 25 + 1 : 0
  const end = total ? Math.min(start + (result?.projects.length ?? 0) - 1, total) : 0
  return <>
    <div className="keeplane-page-heading"><div><h1>Projects</h1><p>Every project used through Keeplane's CLI. A developer onboards a project by running init in its repo.</p></div></div>
    {error && <p className="mt-6 text-[15px]" role="alert">Projects could not load. {error}</p>}
    {notice && <p className="mt-6 text-[15px]" role="status">{notice}</p>}
    <div className="mt-6 max-w-[400px]"><Label htmlFor="search-projects" className="keeplane-field-label">Search projects</Label><Input id="search-projects" type="search" value={searchInput} onChange={event => setSearchInput(event.target.value)} /></div>
    <div className="keeplane-table-frame mt-6 [&>[data-slot=table-container]]:overflow-visible" tabIndex={0} role="region" aria-label="Projects table">
      <Table><TableHeader>{table.getHeaderGroups().map(group => <TableRow key={group.id}>{group.headers.map(header => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
        <TableBody>{busy ? <TableRow><TableCell colSpan={columns.length}>Loading projects…</TableCell></TableRow> : table.getRowModel().rows.length === 0 ? <TableRow><TableCell colSpan={columns.length}>{error ? 'Projects unavailable' : 'No projects found'}</TableCell></TableRow> :
          table.getRowModel().rows.map(row => <TableRow key={row.id}>{row.getVisibleCells().map(cell => <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>)}</TableBody>
      </Table>
    </div>
    <div className="mt-5 flex flex-wrap items-center justify-between gap-4 text-[14px]">
      <span>{total ? `Showing ${start}–${end} of ${total} projects` : 'No results'}</span>
      <div className="flex gap-3"><Button variant="outline" disabled={page === 1 || busy} onClick={() => setPage(value => value - 1)}>Previous</Button><Button variant="outline" disabled={!result?.has_more || busy} onClick={() => setPage(value => value + 1)}>Next</Button></div>
    </div>
    {changing && <SetProjectClassDialog project={changing} returnFocusRef={classTrigger} onClose={() => setChanging(null)} onSaved={value => {
      setResult(previous => previous ? { ...previous, projects: previous.projects.map(project => project.id === value.id ? { ...project, data_class: value.data_class } : project) } : previous)
      setNotice(`Data class for ${value.name}: ${value.data_class?.name ?? 'none'}.`); setChanging(null)
    }} />}
  </>
}
