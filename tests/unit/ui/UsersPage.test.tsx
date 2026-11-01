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
