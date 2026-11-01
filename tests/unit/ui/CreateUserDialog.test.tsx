import { afterEach, expect, test, vi } from 'vitest'
import { createRef } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreateUserDialog } from '../../../components/admin-ui/src/features/users/CreateUserDialog'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const created = { id: 'user-1', username: 'example-user', role: 'admin', sign_in: 'local', managed: false }

function fixture(write: (options: RequestInit) => Promise<object>, check: () => Promise<object> = async () => response({ status: 'not_found' })) {
  const request = vi.fn((path: string, options: RequestInit = {}) => {
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    if (path.startsWith('/api/user-operations/')) return check()
    return write(options)
  })
  vi.stubGlobal('fetch', request)
  return request
}

const writes = (request: ReturnType<typeof fixture>) =>
  request.mock.calls.filter(([path]) => path === '/api/users').map(([, options]) => JSON.parse(options!.body as string))

function open(onCreated = vi.fn(), onOpenChange = vi.fn()) {
  render(<CreateUserDialog open onOpenChange={onOpenChange} onCreated={onCreated} returnFocusRef={createRef<HTMLButtonElement>()} />)
  return onCreated
}
const noAnswer = "Keeplane didn't answer in time. Check to find out."
const unconfirmed = "Keeplane couldn't confirm the result. Check to find out."

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Username'), 'example-user')
  await user.type(screen.getByLabelText('Password'), 'a-test-password-123456')
  await user.click(screen.getByRole('radio', { name: 'Admin' }))
}

test('UI-01: Developer is the default and invalid local accounts never reach the API', async () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  open()

  expect(screen.getByRole('radio', { name: 'Developer' }).getAttribute('aria-checked')).toBe('true')
  await user.type(screen.getByLabelText('Username'), 'ab')
  await user.type(screen.getByLabelText('Password'), 'short')
  await user.click(screen.getByRole('button', { name: 'Create user' }))

  expect(await screen.findByText(/Use 3–64 letters/)).toBeTruthy()
  expect(screen.getByText(/Use at least 12 characters/)).toBeTruthy()
  expect(request).not.toHaveBeenCalled()
})

test('UI-02: the chosen role and an operation ID are sent once through the protected action', async () => {
  const request = fixture(async () => response(created, 201))
  const user = userEvent.setup()
  const onCreated = open()
  await fill(user)
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
  const sent = writes(request)
  expect(sent).toHaveLength(1)
  expect(sent[0]).toMatchObject({ username: 'example-user', role: 'admin' })
  expect(sent[0].operation_id).toMatch(/^[0-9a-f-]{36}$/)
})

test('UI-03: no answer within 10 seconds offers Check and Cancel, and Check that finds the user closes the dialog', async () => {
  const request = fixture(options => new Promise((_resolve, reject) =>
    options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
  async () => response({ status: 'created', user: created }))
  const user = userEvent.setup()
  const onOpenChange = vi.fn()
  const onCreated = open(vi.fn(), onOpenChange)
  await fill(user)
  vi.useFakeTimers()
  fireEvent.click(screen.getByRole('button', { name: 'Create user' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(9_900) })
  expect(screen.queryByRole('button', { name: 'Check' })).toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(100) })
  expect(screen.getByText("It isn't clear whether example-user was created")).toBeTruthy()
  expect(screen.getByText(noAnswer)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy()
  vi.useRealTimers()
  await user.click(screen.getByRole('button', { name: 'Check' }))
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
  expect(onOpenChange).toHaveBeenCalledWith(false)
  expect(writes(request)).toHaveLength(1)
})

test('UI-04: Check that finds nothing shows the typed form again and a retry reuses the operation ID', async () => {
  let attempt = 0
  const request = fixture(async () => {
    attempt += 1
    if (attempt === 1) throw new TypeError('Failed to fetch')
    return response(created, 201)
  })
  const user = userEvent.setup()
  const onCreated = open()
  await fill(user)
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  expect(await screen.findByText(noAnswer)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Check' }))
  expect((screen.getByLabelText('Username') as HTMLInputElement).value).toBe('example-user')
  expect((screen.getByLabelText('Password') as HTMLInputElement).value).toBe('a-test-password-123456')
  expect(screen.getByRole('radio', { name: 'Admin' }).getAttribute('aria-checked')).toBe('true')
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  await waitFor(() => expect(onCreated).toHaveBeenCalledOnce())
  const sent = writes(request)
  expect(sent).toHaveLength(2)
  expect(sent[1].operation_id).toBe(sent[0].operation_id)
})

test.each([500, 502, 503, 504])('UI-05: a %i answer is uncertain, so the dialog says the result is unconfirmed and offers Check', async status => {
  fixture(async () => response({ error: 'Upstream problem' }, status))
  const user = userEvent.setup()
  open()
  await fill(user)
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  expect(await screen.findByRole('button', { name: 'Check' })).toBeTruthy()
  expect(screen.getByText("It isn't clear whether example-user was created")).toBeTruthy()
  expect(screen.getByText(unconfirmed)).toBeTruthy()
  expect(screen.queryByText(noAnswer)).toBeNull()
  expect(screen.queryByText("example-user wasn't created")).toBeNull()
})

test('UI-06: a success answer that names no user is uncertain', async () => {
  fixture(async () => response({}, 201))
  const user = userEvent.setup()
  const onCreated = open()
  await fill(user)
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  expect(await screen.findByRole('button', { name: 'Check' })).toBeTruthy()
  expect(screen.getByText(unconfirmed)).toBeTruthy()
  expect(onCreated).not.toHaveBeenCalled()
})

test('UI-07: Keeplane refusing the user keeps what was typed and says nothing was saved', async () => {
  fixture(async () => response({ error: 'That name already exists' }, 409))
  const user = userEvent.setup()
  const onCreated = open()
  await fill(user)
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  expect(await screen.findByText("example-user wasn't created")).toBeTruthy()
  expect(screen.getByText(/That name already exists/)).toBeTruthy()
  expect((screen.getByLabelText('Username') as HTMLInputElement).value).toBe('example-user')
  expect(screen.queryByRole('button', { name: 'Check' })).toBeNull()
  expect(onCreated).not.toHaveBeenCalled()
  // the title keeps naming the refused username while the admin types a new one
  await user.type(screen.getByLabelText('Username'), '-2')
  expect(screen.getByText("example-user wasn't created")).toBeTruthy()
})

test('UI-08: a refused 64-character username is named in full and the title can wrap', async () => {
  const long = 'a'.repeat(64)
  fixture(async () => response({ error: 'That name already exists' }, 409))
  const user = userEvent.setup()
  open()
  await user.type(screen.getByLabelText('Username'), long)
  await user.type(screen.getByLabelText('Password'), 'a-test-password-123456')
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  const title = await screen.findByText(`${long} wasn't created`)
  expect(title.className).toContain('wrap-anywhere')
})

test.each([
  ['refused', 409, "example-user wasn't created"],
  ['unclear', 503, "It isn't clear whether example-user was created"],
])('UI-09: the %s alert has a circle-alert icon and a weight-600 title, as designed', async (_, status, text) => {
  fixture(async () => response({ error: 'That name already exists' }, status))
  const user = userEvent.setup()
  open()
  await fill(user)
  await user.click(screen.getByRole('button', { name: 'Create user' }))
  const title = await screen.findByText(text)
  expect(title.className).toContain('font-semibold')
  expect(title.className).not.toContain('font-medium')
  const icon = screen.getByRole('alert').querySelector('svg')!
  expect(icon.dataset.icon).toBe('circle-alert')
  expect(icon.querySelector('circle')).toBeTruthy()
})
