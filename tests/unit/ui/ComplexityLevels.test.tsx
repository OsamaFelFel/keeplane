import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModelsPage } from '../../../components/admin-ui/src/features/models/ModelsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const model = (id: string, approved = true) => ({ id, provider: 'Local runner', kind: 'real-local', approved, key_choice: approved ? 'none' : null, owned_by_keeplane: approved })
const row = (level: string, name: string, model_id: string | null, keeplane_pick: string | null, admin: string | null = null, setUp: boolean | null = null) => ({
  level, name, model_id, keeplane_pick, changed_by_admin: admin !== null, admin_model_id: admin, admin_model_set_up: setUp,
})
const listing = {
  models: [model('small'), model('large'), model('gateway-only', false)],
  levels: [
    row('simple', 'Simple', 'small', 'small'),
    row('standard', 'Standard', 'small', 'small'),
    row('complex', 'Complex', 'small', 'large', 'small', true),
  ],
}

function fixture(write: (path: string, options: RequestInit) => object = () => response({}), body: object = listing) {
  const request = vi.fn(async (path: string, options: RequestInit = {}) => {
    if (path === '/api/models') return response(body)
    if (path === '/api/data-classes') return response({ enabled: false, classes: [] })
    if (path === '/api/auth-options') return response({ csrf_token: 'masked' })
    return write(path, options)
  })
  vi.stubGlobal('fetch', request)
  return request
}

test('CL-UI-01: each level shows its model and who picked it', async () => {
  fixture()
  render(<ModelsPage />)
  const table = await screen.findByRole('region', { name: 'Complexity levels table' })
  await within(table).findByRole('row', { name: /Simple/ })
  expect(within(within(table).getByRole('row', { name: /Simple/ })).getByText(/Keeplane's pick/)).toBeTruthy()
  expect(within(within(table).getByRole('row', { name: /Complex/ })).getByText(/changed by an admin/)).toBeTruthy()
})

test('CL-UI-02: Change a level offers only set-up models and saves the choice', async () => {
  const request = fixture((path, options) => {
    expect(path).toBe('/api/levels/simple')
    expect(new Headers(options.headers).get('X-Keeplane-Action')).toBe('1')
    expect(JSON.parse(options.body as string)).toEqual({ model_id: 'large' })
    return response({ levels: [row('simple', 'Simple', 'large', 'small', 'large', true), listing.levels[1], listing.levels[2]] })
  })
  render(<ModelsPage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Change Simple' }))
  const dialog = await screen.findByRole('dialog', { name: 'Model for Simple' })
  const options = within(dialog).getAllByRole('option').map(option => option.textContent)
  expect(options).toEqual(['small', 'large'])
  expect(within(dialog).getByText("Keeplane's pick is small.")).toBeTruthy()
  expect((within(dialog).getByRole('button', { name: "Use Keeplane's pick" }) as HTMLButtonElement).disabled).toBe(true)
  await user.selectOptions(within(dialog).getByLabelText('Model'), 'large')
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByRole('status').textContent).toBe('Simple now uses large.')
  const simple = within(screen.getByRole('region', { name: 'Complexity levels table' })).getByRole('row', { name: /Simple/ })
  expect(within(simple).getByText(/changed by an admin/)).toBeTruthy()
  expect(request.mock.calls.filter(([path]) => path === '/api/levels/simple')).toHaveLength(1)
})

test("CL-UI-03: Use Keeplane's pick sends no model", async () => {
  fixture((_, options) => {
    expect(JSON.parse(options.body as string)).toEqual({ model_id: null })
    return response({ levels: [listing.levels[0], listing.levels[1], row('complex', 'Complex', 'large', 'large')] })
  })
  render(<ModelsPage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Change Complex' }))
  const dialog = await screen.findByRole('dialog', { name: 'Model for Complex' })
  await user.click(within(dialog).getByRole('button', { name: "Use Keeplane's pick" }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByRole('status').textContent).toBe("Complex uses Keeplane's pick again.")
})

test('CL-UI-04: a refused change keeps the dialog open with the reason', async () => {
  fixture(() => response({ error: 'Choose a model that is set up' }, 400))
  render(<ModelsPage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Change Standard' }))
  const dialog = await screen.findByRole('dialog', { name: 'Model for Standard' })
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  expect((await within(dialog).findByRole('alert')).textContent).toBe('Choose a model that is set up')
})

test('CL-UI-05: removing a model an admin-changed level uses shows where it is used and sends nothing', async () => {
  const request = fixture()
  render(<ModelsPage />)
  const user = userEvent.setup()
  const smallRow = await screen.findByRole('row', { name: /^small/ })
  await user.click(within(smallRow).getByRole('button', { name: 'Edit' }))
  await user.click(await screen.findByRole('button', { name: 'Remove model' }))
  const dialog = await screen.findByRole('dialog', { name: 'small is still in use' })
  expect(within(dialog).getByText('Complexity level: Complex')).toBeTruthy()
  expect(within(dialog).getByText('Move these to another model first, then remove it.')).toBeTruthy()
  await user.click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(request.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false)
})

test('CL-UI-06: a level changed after the page loaded still stops the removal', async () => {
  fixture((_, options) => {
    expect(options.method).toBe('DELETE')
    return response({ error: 'large is still in use.', in_use: { levels: ['Standard'], persona_rules: [] } }, 409)
  })
  render(<ModelsPage />)
  const user = userEvent.setup()
  const largeRow = await screen.findByRole('row', { name: /^large/ })
  await user.click(within(largeRow).getByRole('button', { name: 'Edit' }))
  await user.click(await screen.findByRole('button', { name: 'Remove model' }))
  const confirm = await screen.findByRole('dialog', { name: 'Remove large?' })
  await user.click(within(confirm).getByRole('button', { name: 'Remove model' }))
  const dialog = await screen.findByRole('dialog', { name: 'large is still in use' })
  expect(within(dialog).getByText('Complexity level: Standard')).toBeTruthy()
})

test('CL-UI-07: with no set-up model the levels say so and cannot be changed', async () => {
  fixture(undefined, { models: [model('gateway-only', false)], levels: ['Simple', 'Standard', 'Complex'].map(name => row(name.toLowerCase(), name, null, null)) })
  render(<ModelsPage />)
  const table = await screen.findByRole('region', { name: 'Complexity levels table' })
  expect(await within(table).findAllByText('No model set up yet')).toHaveLength(3)
  for (const name of ['Simple', 'Standard', 'Complex']) {
    expect((within(table).getByRole('button', { name: `Change ${name}` }) as HTMLButtonElement).disabled).toBe(true)
  }
})

test("CL-UI-08: an admin's model that isn't set up now is explained", async () => {
  fixture(undefined, { models: [model('small')], levels: [listing.levels[0], row('standard', 'Standard', 'small', 'small', 'gone', false), listing.levels[1]] })
  render(<ModelsPage />)
  expect(await screen.findByText("An admin chose gone, which isn't set up now.")).toBeTruthy()
})
