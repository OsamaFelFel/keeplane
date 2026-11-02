import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataClassesPage } from '../../../components/admin-ui/src/features/data-classes/DataClassesPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
type Row = { id: string; name: string; approved_model_ids: string[]; project_count: number }

// A small Keeplane that keeps class rows and answers like the data-class API.
function server(rows: Row[]) {
  const writes: { method: string; path: string; body?: object; action: string | null }[] = []
  const request = vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    if (path === '/api/auth-options') return response({ csrf_token: 'token' })
    if (path === '/api/models') return response({ models: [{ id: 'coder', approved: true }, { id: 'reviewer', approved: true }, { id: 'gateway-only', approved: false }] })
    if (method === 'GET') return response({ enabled: true, classes: rows.map(row => ({ ...row })), detection: { enabled: false, class_id: 'confidential', available: true } })
    const body = init.body ? JSON.parse(String(init.body)) : undefined
    writes.push({ method, path, body, action: new Headers(init.headers).get('X-Keeplane-Action') })
    const id = decodeURIComponent(path.split('/').pop() ?? '')
    if (method === 'POST') { const row = { id: 'restricted', ...body, project_count: 0 }; rows.push(row); return response(row, 201) }
    const row = rows.find(item => item.id === id)!
    if (method === 'PUT') { Object.assign(row, body); return response(row) }
    if (row.project_count) return response({ error: 'Projects still use this class' }, 409)
    rows.splice(rows.indexOf(row), 1); return response({ removed: true })
  })
  vi.stubGlobal('fetch', request)
  return writes
}

const starters = (): Row[] => [
  { id: 'public', name: 'Public', approved_model_ids: [], project_count: 0 },
  { id: 'internal', name: 'Internal', approved_model_ids: [], project_count: 0 },
  { id: 'confidential', name: 'Confidential', approved_model_ids: ['coder'], project_count: 0 },
]

async function rowFor(name: string) {
  const table = await screen.findByRole('region', { name: 'Data classes table' })
  return within(table).getByRole('cell', { name }).closest('tr') as HTMLElement
}

// DC-UI-11 (ST18 "Add a class"): the class appears with the models picked for it.
test('an admin adds a class with its approved models', async () => {
  const writes = server(starters())
  const user = userEvent.setup()
  render(<DataClassesPage />)
  await user.click(await screen.findByRole('button', { name: 'Add class' }))
  const dialog = await screen.findByRole('dialog', { name: 'Add class' })
  // Only models set up in Keeplane are offered; none is picked by default.
  const coder = await within(dialog).findByRole('checkbox', { name: 'coder' }) as HTMLInputElement
  expect(coder.checked).toBe(false)
  expect(within(dialog).queryByRole('checkbox', { name: 'gateway-only' })).toBeNull()
  await user.type(within(dialog).getByLabelText('Name'), 'Restricted')
  await user.click(coder)
  await user.click(within(dialog).getByRole('button', { name: 'Add class' }))
  expect(await screen.findByText('Added Restricted.')).toBeTruthy()
  expect(writes).toEqual([{ method: 'POST', path: '/api/data-classes', body: { name: 'Restricted', approved_model_ids: ['coder'] }, action: '1' }])
  const row = await rowFor('Restricted')
  expect(within(row).getByRole('cell', { name: 'coder' })).toBeTruthy()
})

// DC-UI-12 (ST18 "Change a class"): a rename and new approved models show in the table.
test('an admin renames a class and changes its approved models', async () => {
  const writes = server(starters())
  const user = userEvent.setup()
  render(<DataClassesPage />)
  await user.click(within(await rowFor('Confidential')).getByRole('button', { name: 'Edit' }))
  const dialog = await screen.findByRole('dialog', { name: 'Edit Confidential' })
  const coder = await within(dialog).findByRole('checkbox', { name: 'coder' }) as HTMLInputElement
  expect(coder.checked).toBe(true)
  const name = within(dialog).getByLabelText('Name')
  await user.clear(name)
  await user.type(name, 'Secret')
  await user.click(coder)
  await user.click(within(dialog).getByRole('checkbox', { name: 'reviewer' }))
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Saved Secret.')).toBeTruthy()
  expect(writes).toEqual([{ method: 'PUT', path: '/api/data-classes/confidential', body: { name: 'Secret', approved_model_ids: ['reviewer'] }, action: '1' }])
  const row = await rowFor('Secret')
  expect(within(row).getByRole('cell', { name: 'reviewer' })).toBeTruthy()
  expect(screen.queryByRole('cell', { name: 'Confidential' })).toBeNull()
})

// DC-UI-13 (ST18 "A class in use"): Keeplane keeps the class and the page says projects use it.
test('removing a class a project uses keeps it and says why', async () => {
  const rows = starters()
  rows[2].project_count = 1
  const writes = server(rows)
  const user = userEvent.setup()
  render(<DataClassesPage />)
  await user.click(within(await rowFor('Confidential')).getByRole('button', { name: 'Edit' }))
  await user.click(await screen.findByRole('button', { name: 'Remove class' }))
  const confirm = await screen.findByRole('dialog', { name: 'Remove class?' })
  await user.click(within(confirm).getByRole('button', { name: 'Remove class' }))
  expect(await within(confirm).findByRole('alert')).toHaveProperty('textContent', 'Projects still use this class')
  expect(writes).toEqual([{ method: 'DELETE', path: '/api/data-classes/confidential', body: undefined, action: '1' }])
  await user.click(within(confirm).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Remove class?' })).toBeNull())
  await user.click(within(screen.getByRole('dialog', { name: 'Edit Confidential' })).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.queryByText('Removed Confidential.')).toBeNull()
  expect(within(await rowFor('Confidential')).getByRole('cell', { name: '1' })).toBeTruthy()
})
