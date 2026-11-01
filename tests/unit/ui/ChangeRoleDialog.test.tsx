import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChangeRoleDialog } from '../../../components/admin-ui/src/features/users/ChangeRoleDialog'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const developer = { id: 'developer-1', username: 'developer-example', role: 'developer' as const, sign_in: 'local', managed: false }
const promoted = { ...developer, role: 'admin' as const }
const listing = (users: object[], hasMore = false, page = 1) =>
  response({ users, page, page_size: 50, total: users.length, has_more: hasMore })
const noAnswer = "Keeplane didn't answer in time. Check to find out."
const unconfirmed = "Keeplane couldn't confirm the result. Check to find out."
const unclear = "It isn't clear whether developer-example's role was changed"

function fixture(write: (options: RequestInit) => Promise<object>, read: (url: URL) => Promise<object> = async () => listing([developer])) {
  const request = vi.fn((path: string, options: RequestInit = {}) => {
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    if (path.startsWith('/api/users?')) return read(new URL(path, 'http://keeplane.test'))
    return write(options)
  })
  vi.stubGlobal('fetch', request)
  return request
}
const writes = (request: ReturnType<typeof fixture>) =>
  request.mock.calls.filter(([path]) => path === '/api/users/developer-1/role').map(([, options]) => JSON.parse(options!.body as string))
const hangs = (options: RequestInit) => new Promise<object>((_resolve, reject) =>
  options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))

function open(onOpenChange = vi.fn(), onChanged = vi.fn()) {
  render(<ChangeRoleDialog user={developer} onOpenChange={onOpenChange} onChanged={onChanged} />)
  return { onOpenChange, onChanged }
}

async function saveAdmin(onOpenChange = vi.fn(), onChanged = vi.fn()) {
  const user = userEvent.setup()
  open(onOpenChange, onChanged)
  await user.click(screen.getByRole('radio', { name: 'Admin' }))
  await user.click(screen.getByRole('button', { name: 'Change role' }))
  return { user, onOpenChange, onChanged }
}

// The design system's failure message: a circle-alert icon (not the old triangle) and a weight-600 first line.
async function expectFailureMessage(title: string, second: string) {
  const heading = await screen.findByText(title)
  expect(heading.className).toContain('font-semibold')
  const alert = screen.getByRole('alert')
  expect(alert.textContent).toBe(title + second)
  const icons = alert.querySelectorAll('svg')
  expect(icons).toHaveLength(1)
  expect(icons[0].dataset.icon).toBe('circle-alert')
  expect(icons[0].querySelector('circle')).toBeTruthy()
  expect(icons[0].getAttribute('class')).toContain('size-5')
}

test('UI-ROLE-01: a refused change says "[Username]\'s role wasn\'t changed" with the reason and keeps the dialog open', async () => {
  const request = fixture(async () => response({ error: 'Account not found' }, 404))
  const { onOpenChange, onChanged } = await saveAdmin()
  await expectFailureMessage("developer-example's role wasn't changed",
    'Account not found. Nothing was saved. Check the details and try again.')
  expect(onOpenChange).not.toHaveBeenCalled()
  expect(onChanged).not.toHaveBeenCalled()
  expect(screen.getByRole('radio', { name: 'Admin' }).getAttribute('aria-checked')).toBe('true')
  expect(screen.queryByRole('button', { name: 'Check' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Change role' })).toHaveProperty('disabled', false)
  expect(writes(request)).toHaveLength(1)
})

test.each([
  ['a 500', async () => response({ error: 'Internal error' }, 500), unconfirmed],
  ['a 503', async () => response({ error: 'Internal error' }, 503), unconfirmed],
  ['a success answer that names no user', async () => response({}), unconfirmed],
  ['a lost connection', async () => { throw new TypeError('Failed to fetch') }, noAnswer],
])("UI-ROLE-02: after %s the dialog says it isn't clear whether the role was changed and offers Cancel and Check", async (_, write, second) => {
  fixture(write)
  const { onChanged } = await saveAdmin()
  await expectFailureMessage(unclear, second)
  expect(screen.queryByText(/Nothing was saved/)).toBeNull()
  expect(screen.getByRole('button', { name: 'Cancel' })).toHaveProperty('disabled', false)
  expect(screen.getByRole('button', { name: 'Check' })).toHaveProperty('disabled', false)
  expect(screen.queryByRole('button', { name: 'Change role' })).toBeNull()
  expect(screen.getByRole('radio', { name: 'Admin' })).toHaveProperty('disabled', true)
  expect(onChanged).not.toHaveBeenCalled()
})

test('UI-ROLE-03: the dialog reads "Role for [Username]" and a "Change role" button, as in Users-role.dc.html', () => {
  fixture(async () => response(promoted))
  open()
  expect(screen.getByRole('heading', { name: 'Change role' })).toBeTruthy()
  const legend = document.querySelector('legend')!
  expect(legend.textContent).toBe('Role for developer-example')
  expect(legend.querySelector('span')!.className).toContain('text-muted-foreground')
  expect(screen.getByRole('group', { name: 'Role for developer-example' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Change role' })).toHaveProperty('disabled', true)
  expect(screen.queryByRole('button', { name: 'Save role' })).toBeNull()
})

test('UI-ROLE-04: while saving, the button spins, a screen-reader status says Saving, everything is off and Escape does not close', async () => {
  let answer: (value: object) => void = () => {}
  fixture(() => new Promise(resolve => { answer = resolve }))
  const { onOpenChange, onChanged } = await saveAdmin()
  expect(await screen.findByRole('status')).toHaveProperty('textContent', 'Saving')
  const button = screen.getByRole('button', { name: 'Change role' })
  expect(button).toHaveProperty('disabled', true)
  expect(button.querySelector('svg.animate-spin')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Cancel' })).toHaveProperty('disabled', true)
  expect(screen.getByRole('radio', { name: 'Developer' })).toHaveProperty('disabled', true)
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
  expect(onOpenChange).not.toHaveBeenCalled()
  await act(async () => { answer(response(promoted)) })
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith(promoted))
  expect(onOpenChange).toHaveBeenCalledWith(false)
})

test('UI-ROLE-05: no answer within 10 seconds offers Check, and Check that reads back the new role closes the dialog with it', async () => {
  const request = fixture(hangs, async () => listing([promoted]))
  const user = userEvent.setup()
  const { onOpenChange, onChanged } = open()
  await user.click(screen.getByRole('radio', { name: 'Admin' }))
  vi.useFakeTimers()
  fireEvent.click(screen.getByRole('button', { name: 'Change role' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(9_900) })
  expect(screen.queryByRole('button', { name: 'Check' })).toBeNull()
  expect(screen.getByRole('status').textContent).toBe('Saving')
  await act(async () => { await vi.advanceTimersByTimeAsync(100) })
  expect(screen.getByText(unclear)).toBeTruthy()
  vi.useRealTimers()
  await expectFailureMessage(unclear, noAnswer)
  expect(screen.queryByRole('status')).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Check' }))
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith(promoted))
  expect(onOpenChange).toHaveBeenCalledWith(false)
  expect(writes(request)).toHaveLength(1)
  const read = request.mock.calls.map(([path]) => path).find(path => path.startsWith('/api/users?'))!
  expect(new URL(read, 'http://keeplane.test').searchParams.get('search')).toBe('developer-example')
})

test('UI-ROLE-06: Check that reads back the old role brings the form back with the chosen role, and sending again changes it', async () => {
  let attempt = 0
  const request = fixture(async () => {
    attempt += 1
    if (attempt === 1) throw new TypeError('Failed to fetch')
    return response(promoted)
  })
  const { user, onChanged } = await saveAdmin()
  expect(await screen.findByText(noAnswer)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Check' }))
  const save = await screen.findByRole('button', { name: 'Change role' })
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('radio', { name: 'Admin' }).getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('radio', { name: 'Admin' })).toHaveProperty('disabled', false)
  await user.click(save)
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
  expect(writes(request)).toEqual([{ role: 'admin' }, { role: 'admin' }])
})

test('UI-ROLE-07: Check finds the user beyond the first page of partial matches, and a missing user brings the form back', async () => {
  const others = Array.from({ length: 50 }, (_, index) => ({ ...developer, id: `other-${index}`, username: `a-developer-example-${index}` }))
  const request = fixture(async () => response({ error: 'Internal error' }, 502),
    async url => url.searchParams.get('page') === '1' ? listing(others, true) : listing([promoted], false, 2))
  const { user, onChanged } = await saveAdmin()
  expect(await screen.findByText(unconfirmed)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Check' }))
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith(promoted))
  expect(request.mock.calls.filter(([path]) => path.startsWith('/api/users?'))).toHaveLength(2)

  cleanup()
  fixture(async () => response({ error: 'Internal error' }, 502), async () => listing([]))
  const second = await saveAdmin()
  expect(await screen.findByText(unconfirmed)).toBeTruthy()
  await second.user.click(screen.getByRole('button', { name: 'Check' }))
  expect(await screen.findByRole('button', { name: 'Change role' })).toBeTruthy()
  expect(second.onChanged).not.toHaveBeenCalled()
})

test('UI-ROLE-08: Check that gets no answer says so and keeps Check', async () => {
  fixture(async () => { throw new TypeError('Failed to fetch') }, async () => { throw new TypeError('Failed to fetch') })
  const { user, onChanged } = await saveAdmin()
  expect(await screen.findByText(noAnswer)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Check' }))
  expect(await screen.findByText('Keeplane did not answer. Check again.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Check' })).toBeTruthy()
  expect(screen.getByText(unclear)).toBeTruthy()
  expect(onChanged).not.toHaveBeenCalled()
})

test('UI-ROLE-09: Cancel closes the dialog after no answer', async () => {
  fixture(async () => { throw new TypeError('Failed to fetch') })
  const { user, onOpenChange, onChanged } = await saveAdmin()
  expect(await screen.findByText(noAnswer)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(onOpenChange).toHaveBeenCalledWith(false)
  expect(onChanged).not.toHaveBeenCalled()
})
