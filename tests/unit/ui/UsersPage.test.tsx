import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UsersPage } from '../../../components/admin-ui/src/features/users/UsersPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object) => ({ ok: true, status: 200, json: async () => body })
const users = [
  { id: 'break-glass', username: 'first-admin', role: 'admin', sign_in: 'break-glass', managed: true },
  { id: 'developer-1', username: 'developer-example', role: 'developer', sign_in: 'local', managed: false },
]

function fixture(overrides: object = {}) {
  const request = vi.fn((path: string) => {
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    if (path === '/api/edition-note/consume') return Promise.resolve(response({ show: false }))
    return Promise.resolve(response({ users, page: 1, page_size: 25, total: 2, has_more: false, ...overrides }))
  })
  vi.stubGlobal('fetch', request)
  return request
}
const listings = (request: ReturnType<typeof fixture>) => request.mock.calls
  .filter(([path]) => path.startsWith('/api/users?'))
  .map(([path]) => new URL(path, 'http://localhost').searchParams)

test('UI-USERS-01: the break-glass row is shown as managed at infrastructure level with no Change role', async () => {
  fixture()
  render(<UsersPage />)
  const managed = (await screen.findByText('first-admin')).closest('tr')!
  expect(within(managed).getByText('Break-glass, managed at infrastructure level')).toBeTruthy()
  expect(within(managed).queryByRole('button')).toBeNull()
  const local = screen.getByText('developer-example').closest('tr')!
  expect(within(local).getByRole('button', { name: 'Change role' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /remove|delete|edit/i })).toBeNull()
})

test('UI-USERS-02: search asks the server for matching users from the first page; Next asks for the next page', async () => {
  const request = fixture({ total: 30, has_more: true })
  const user = userEvent.setup()
  render(<UsersPage />)
  await screen.findByText('first-admin')
  await user.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(listings(request).at(-1)!.get('page')).toBe('2'))
  await user.type(screen.getByLabelText('Search users'), 'dev')
  await waitFor(() => {
    const last = listings(request).at(-1)!
    expect([last.get('search'), last.get('page'), last.get('page_size')]).toEqual(['dev', '1', '25'])
  })
})

test("UI-USERS-03: after Change role is done, Users shows the change and focus goes back to that row's Change role", async () => {
  const listed = users.map(row => ({ ...row }))
  const request = vi.fn((path: string) => {
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    if (path === '/api/edition-note/consume') return Promise.resolve(response({ show: false }))
    if (path === '/api/users/developer-1/role') {
      listed[1].role = 'admin'
      return Promise.resolve(response(listed[1]))
    }
    return Promise.resolve(response({ users: listed.map(row => ({ ...row })), page: 1, page_size: 25, total: 2, has_more: false }))
  })
  vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  render(<UsersPage />)
  const row = (await screen.findByText('developer-example')).closest('tr')!
  await user.click(within(row).getByRole('button', { name: 'Change role' }))
  const dialog = await screen.findByRole('dialog', { name: 'Change role' })
  await user.click(within(dialog).getByRole('radio', { name: 'Admin' }))
  await user.click(within(dialog).getByRole('button', { name: 'Change role' }))
  expect(await screen.findByText("Changed developer-example's role to admin.")).toBeTruthy()
  await waitFor(() => {
    const updated = screen.getByText('developer-example').closest('tr')!
    expect(within(updated).getByText('Admin')).toBeTruthy()
    expect(document.activeElement).toBe(within(updated).getByRole('button', { name: 'Change role' }))
  })
})

test('UI-USERS-04: when Create user gets no answer and Check finds the user, the dialog closes and Users shows the user', async () => {
  const listed = users.map(row => ({ ...row }))
  const created = { id: 'user-1', username: 'example-user', role: 'admin', sign_in: 'local', managed: false }
  const request = vi.fn((path: string) => {
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    if (path === '/api/edition-note/consume') return Promise.resolve(response({ show: false }))
    if (path === '/api/users') {
      // Keeplane saves the user, but the answer is lost on the way back.
      listed.push(created)
      return Promise.reject(new TypeError('Failed to fetch'))
    }
    if (path.startsWith('/api/user-operations/')) return Promise.resolve(response({ status: 'created', user: created }))
    return Promise.resolve(response({ users: listed.map(row => ({ ...row })), page: 1, page_size: 25, total: listed.length, has_more: false }))
  })
  vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  render(<UsersPage />)
  await screen.findByText('first-admin')
  expect(screen.queryByText('example-user')).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  const dialog = await screen.findByRole('dialog', { name: 'Create user' })
  await user.type(within(dialog).getByLabelText('Username'), 'example-user')
  await user.type(within(dialog).getByLabelText('Password'), 'a-test-password-123456')
  await user.click(within(dialog).getByRole('radio', { name: 'Admin' }))
  await user.click(within(dialog).getByRole('button', { name: 'Create user' }))
  expect(await within(dialog).findByText("It isn't clear whether example-user was created")).toBeTruthy()
  await user.click(within(dialog).getByRole('button', { name: 'Check' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Create user' })).toBeNull())
  const row = (await screen.findByText('example-user')).closest('tr')!
  expect(within(row).getByText('Admin')).toBeTruthy()
  expect(request.mock.calls.filter(([path]) => path === '/api/users')).toHaveLength(1)
})
