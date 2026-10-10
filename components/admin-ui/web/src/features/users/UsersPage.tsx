import { useEffect, useMemo, useRef, useState } from 'react'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { api, action, type User, type UserPage } from '@/app/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { CreateUserDialog } from './CreateUserDialog'
import { ChangeRoleDialog } from './ChangeRoleDialog'

export function UsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editionNote, setEditionNote] = useState(false)
  const [creating, setCreating] = useState(false)
  const [changing, setChanging] = useState<User | null>(null)
  const noteRequested = useRef(false)
  const createTrigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 250)
    return () => window.clearTimeout(timer)
  }, [searchInput])
  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    const params = new URLSearchParams({ page: String(page), page_size: '25', search })
    api<UserPage>(`/api/users?${params}`).then(result => {
      if (cancelled) return
      setUsers(result.users); setTotal(result.total); setHasMore(result.has_more)
    }).catch(cause => { if (!cancelled) setError(cause.message) })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [page, search, refresh])
  useEffect(() => {
    if (noteRequested.current) return
    noteRequested.current = true
    action<{ show: boolean }>('/api/edition-note/consume', 'POST', {}).then(result => setEditionNote(result.show)).catch(() => {})
  }, [])

  const columns = useMemo<ColumnDef<User>[]>(() => [
    { accessorKey: 'username', header: 'Username', cell: ({ row }) => row.original.managed ? <span className="text-muted-foreground">{row.original.username}</span> : row.original.username },
    { accessorKey: 'role', header: 'Role', cell: ({ row }) => row.original.role === 'admin' ? 'Admin' : 'Developer' },
    { accessorKey: 'sign_in', header: 'Signs in with', cell: ({ row }) => row.original.sign_in === 'break-glass' ? 'Break-glass, managed at infrastructure level' : row.original.sign_in === 'oidc' ? 'Single sign-on' : 'Username and password' },
    { id: 'actions', header: () => <span className="sr-only">Actions</span>, cell: ({ row }) => row.original.managed ? null :
      <Button variant="link" className="h-6 min-h-6 px-0 text-[15px]" onClick={() => setChanging(row.original)}>Change role</Button> },
  ], [])
  const table = useReactTable({ data: users, columns, getCoreRowModel: getCoreRowModel() })
  const start = total ? (page - 1) * 25 + 1 : 0
  const end = total ? Math.min(start + users.length - 1, total) : 0

  function created(user: User) {
    setNotice(`Created ${user.username}.`); setSearchInput(''); setSearch(''); setPage(1); setRefresh(value => value + 1)
  }
  function changed(user: User) {
    setNotice(`Changed ${user.username}'s role to ${user.role}.`); setRefresh(value => value + 1)
  }

  return <>
    <div className="keeplane-page-heading">
      <div><h1>Users</h1><p>The admin creates username and password accounts. People who sign in with single sign-on get a developer account the first time.</p></div>
      <Button ref={createTrigger} className="shrink-0" onClick={() => setCreating(true)}>Create user</Button>
    </div>
    {editionNote && <p className="mt-6 rounded-[8px] border border-border bg-card p-4 text-[15px]">Teams and group access control are available in Enterprise. <a className="underline" href="/editions">See Editions</a>.</p>}
    {notice && <p className="mt-6 text-[15px]" role="status">{notice}</p>}
    {error && <p className="mt-6 text-[15px]" role="alert">Users could not load. {error}</p>}
    <div className="mt-6 max-w-[400px]"><Label htmlFor="search-users" className="keeplane-field-label">Search users</Label><Input id="search-users" type="search" value={searchInput} onChange={event => setSearchInput(event.target.value)} /></div>
    <div className="keeplane-table-frame mt-6" tabIndex={0} role="region" aria-label="Users table">
      <Table><TableHeader>{table.getHeaderGroups().map(group => <TableRow key={group.id}>{group.headers.map(header => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
        <TableBody>{busy ? <TableRow><TableCell colSpan={4}>Loading users…</TableCell></TableRow> : users.length === 0 ? <TableRow><TableCell colSpan={4}>No users found</TableCell></TableRow> :
          table.getRowModel().rows.map(row => <TableRow key={row.id}>{row.getVisibleCells().map(cell => <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>)}</TableBody>
      </Table>
    </div>
    <div className="mt-5 flex flex-wrap items-center justify-between gap-4 text-[14px]">
      <span>{total ? `Showing ${start}–${end} of ${total} users` : 'No results'}</span>
      <div className="flex gap-3"><Button variant="outline" disabled={page === 1 || busy} onClick={() => setPage(value => value - 1)}>Previous</Button><Button variant="outline" disabled={!hasMore || busy} onClick={() => setPage(value => value + 1)}>Next</Button></div>
    </div>
    <CreateUserDialog open={creating} onOpenChange={setCreating} onCreated={created} returnFocusRef={createTrigger} />
    <ChangeRoleDialog user={changing} onOpenChange={open => { if (!open) setChanging(null) }} onChanged={changed} />
  </>
}
