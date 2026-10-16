import { StrictMode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SetProjectClassDialog } from '../../../components/admin-ui/src/features/projects/SetProjectClassDialog'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })
const project = { id: 'project-one', name: 'Example', initialized: false, users: [], data_class: { id: 'confidential', name: 'Confidential' } }
const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const choices = { enabled: true, classes: [{ id: 'public', name: 'Public' }, project.data_class] }

function fixture(write: (options: RequestInit) => Promise<object>, current = { ...project, classes_enabled: true, data_class: { id: 'public', name: 'Public' } }) {
  const request = vi.fn((path: string, options: RequestInit = {}) => {
    if (path === '/api/data-classes') return Promise.resolve(response(choices))
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    if (options.method === 'PUT') return write(options)
    return Promise.resolve(response(current))
  })
  vi.stubGlobal('fetch', request)
  return request
}

test('an explicit class is saved through the normal protected action, including StrictMode', async () => {
  const request = fixture(async () => response({ ...project, data_class: choices.classes[0] }))
  const saved = vi.fn()
  render(<StrictMode><SetProjectClassDialog project={project} onClose={() => {}} onSaved={saved} /></StrictMode>)
  const user = userEvent.setup()
  await screen.findByRole('option', { name: 'Public' })
  await user.selectOptions(screen.getByLabelText('Data class'), 'public')
  await user.click(screen.getByRole('button', { name: 'Save', exact: true }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  const write = request.mock.calls.find(([, options]) => options?.method === 'PUT')!
  expect(JSON.parse(write[1]!.body as string)).toEqual({ class_id: 'public' })
  expect(new Headers(write[1]!.headers).get('X-Keeplane-Action')).toBe('1')
})

test('a refused assignment keeps the choice and permits correction', async () => {
  fixture(async () => response({ error: 'Turn on data classes first' }, 409))
  const saved = vi.fn()
  render(<SetProjectClassDialog project={project} onClose={() => {}} onSaved={saved} />)
  const user = userEvent.setup()
  await screen.findByRole('option', { name: 'Public' })
  await user.selectOptions(screen.getByLabelText('Data class'), 'public')
  await user.click(screen.getByRole('button', { name: 'Save', exact: true }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect((screen.getByLabelText('Data class') as HTMLSelectElement).value).toBe('public')
  expect(saved).not.toHaveBeenCalled()
})

test('a lost response never repeats the write and Check reads the actual saved class', async () => {
  const request = fixture(async () => { throw new Error('Connection lost after commit') })
  const saved = vi.fn()
  render(<SetProjectClassDialog project={project} onClose={() => {}} onSaved={saved} />)
  const user = userEvent.setup()
  await screen.findByRole('option', { name: 'Public' })
  await user.selectOptions(screen.getByLabelText('Data class'), 'public')
  await user.click(screen.getByRole('button', { name: 'Save', exact: true }))
  await screen.findByRole('button', { name: 'Check', exact: true })
  expect((screen.getByLabelText('Data class') as HTMLSelectElement).disabled).toBe(true)
  expect(screen.queryByRole('button', { name: 'Save', exact: true })).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Check', exact: true }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(request.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(1)
})

test('if classes are now off, recovery stays uncertain and never clears the stored class', async () => {
  const request = fixture(async () => { throw new Error('Lost reply') }, { ...project, classes_enabled: false, data_class: project.data_class })
  const saved = vi.fn()
  render(<SetProjectClassDialog project={project} onClose={() => {}} onSaved={saved} />)
  const user = userEvent.setup()
  await screen.findByRole('option', { name: 'Public' })
  await user.selectOptions(screen.getByLabelText('Data class'), '')
  await user.click(screen.getByRole('button', { name: 'Save', exact: true }))
  await user.click(await screen.findByRole('button', { name: 'Check', exact: true }))
  await screen.findByText('Data classes are off. Close this dialog and reload Projects.')
  expect(saved).not.toHaveBeenCalled()
  expect(request.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(1)
})

test('ten seconds without a write response stops saving and offers readback', async () => {
  fixture(options => new Promise((_resolve, reject) => options.signal?.addEventListener('abort', () => reject(new Error('No reply')))))
  render(<SetProjectClassDialog project={project} onClose={() => {}} onSaved={() => {}} />)
  const user = userEvent.setup()
  await screen.findByRole('option', { name: 'Public' })
  await user.selectOptions(screen.getByLabelText('Data class'), 'public')
  vi.useFakeTimers()
  fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }))
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
  expect(screen.getByRole('button', { name: 'Check', exact: true })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Saving…' })).toBeNull()
})
