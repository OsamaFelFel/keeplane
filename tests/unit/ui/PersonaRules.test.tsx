import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModelsPage } from '../../../components/admin-ui/src/features/models/ModelsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const model = (id: string, approved = true) => ({ id, provider: 'Local runner', kind: 'real-local', approved, key_choice: approved ? 'none' : null, owned_by_keeplane: approved })
const level = (key: string, name: string, modelId: string) => ({
  level: key, name, model_id: modelId, keeplane_pick: modelId, changed_by_admin: false, admin_model_id: null, admin_model_set_up: null,
})
const rule = (persona: string, name: string, modelId: string, setUp = true) => ({ persona, name, model_id: modelId, model_set_up: setUp })
const personas = [
  { persona: 'architect', name: 'Architect' }, { persona: 'developer', name: 'Developer' }, { persona: 'frontend', name: 'Frontend' },
]
const listing = {
  models: [model('small'), model('large'), model('gateway-only', false)],
  levels: [level('simple', 'Simple', 'small'), level('standard', 'Standard', 'small'), level('complex', 'Complex', 'large')],
  persona_rules: [rule('architect', 'Architect', 'large')],
  personas,
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

test('PR-UI-01: each rule shows its persona and model', async () => {
  fixture()
  render(<ModelsPage />)
  const table = await screen.findByRole('region', { name: 'Persona rules table' })
  const row = await within(table).findByRole('row', { name: /Persona is Architect/ })
  expect(within(row).getByText('large')).toBeTruthy()
})

test('PR-UI-02: Add rule offers the personas and only set-up models, and saves the rule', async () => {
  const request = fixture((path, options) => {
    expect(path).toBe('/api/persona-rules/frontend')
    expect(new Headers(options.headers).get('X-Keeplane-Action')).toBe('1')
    expect(JSON.parse(options.body as string)).toEqual({ model_id: 'small' })
    return response({ persona_rules: [listing.persona_rules[0], rule('frontend', 'Frontend', 'small')] })
  })
  render(<ModelsPage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Add rule' }))
  const dialog = await screen.findByRole('dialog', { name: 'Add persona rule' })
  const persona = within(dialog).getByLabelText('When the persona is')
  expect(within(persona).getAllByRole('option').map(option => option.textContent)).toEqual(['Architect', 'Developer', 'Frontend'])
  const route = within(dialog).getByLabelText('Route to')
  expect(within(route).getAllByRole('option').map(option => option.textContent)).toEqual(['Choose a model', 'small', 'large'])
  expect((within(dialog).getByRole('button', { name: 'Add rule' }) as HTMLButtonElement).disabled).toBe(true)
  await user.selectOptions(persona, 'frontend')
  await user.selectOptions(route, 'small')
  await user.click(within(dialog).getByRole('button', { name: 'Add rule' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByRole('status').textContent).toBe("Frontend's work now goes to small.")
  const table = screen.getByRole('region', { name: 'Persona rules table' })
  expect(within(table).getByRole('row', { name: /Persona is Frontend/ })).toBeTruthy()
  expect(request.mock.calls.filter(([path]) => path === '/api/persona-rules/frontend')).toHaveLength(1)
})

test('PR-UI-03: a persona that already has a rule says the new rule replaces it', async () => {
  fixture()
  render(<ModelsPage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Add rule' }))
  const dialog = await screen.findByRole('dialog', { name: 'Add persona rule' })
  expect(within(dialog).getByText("Architect's work goes to large now. This rule replaces it.")).toBeTruthy()
  await user.selectOptions(within(dialog).getByLabelText('When the persona is'), 'developer')
  expect(within(dialog).queryByText(/This rule replaces it/)).toBeNull()
})

test('PR-UI-04: a refused rule keeps the dialog open with the reason', async () => {
  fixture(() => response({ error: 'Choose a model that is set up' }, 400))
  render(<ModelsPage />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Add rule' }))
  const dialog = await screen.findByRole('dialog', { name: 'Add persona rule' })
  await user.selectOptions(within(dialog).getByLabelText('Route to'), 'small')
  await user.click(within(dialog).getByRole('button', { name: 'Add rule' }))
  expect((await within(dialog).findByRole('alert')).textContent).toBe('Choose a model that is set up')
})

test('PR-UI-05: removing a model a persona rule uses lists the rule and sends nothing', async () => {
  const request = fixture()
  render(<ModelsPage />)
  const user = userEvent.setup()
  const largeRow = await screen.findByRole('row', { name: /^large/ })
  await user.click(within(largeRow).getByRole('button', { name: 'Edit' }))
  await user.click(await screen.findByRole('button', { name: 'Remove model' }))
  const dialog = await screen.findByRole('dialog', { name: 'large is still in use' })
  expect(within(dialog).getByText('Persona rule: Architect')).toBeTruthy()
  expect(within(dialog).queryByText(/Complexity level/)).toBeNull()
  expect(request.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false)
})

test('PR-UI-06: a rule added after the page loaded still stops the removal', async () => {
  fixture((_, options) => {
    expect(options.method).toBe('DELETE')
    return response({ error: 'small is still in use.', in_use: { levels: [], persona_rules: ['Frontend'] } }, 409)
  })
  render(<ModelsPage />)
  const user = userEvent.setup()
  const smallRow = await screen.findByRole('row', { name: /^small/ })
  await user.click(within(smallRow).getByRole('button', { name: 'Edit' }))
  await user.click(await screen.findByRole('button', { name: 'Remove model' }))
  const confirm = await screen.findByRole('dialog', { name: 'Remove small?' })
  await user.click(within(confirm).getByRole('button', { name: 'Remove model' }))
  const dialog = await screen.findByRole('dialog', { name: 'small is still in use' })
  expect(within(dialog).getByText('Persona rule: Frontend')).toBeTruthy()
})

test("PR-UI-07: no rules, a rule whose model isn't set up, and no set-up model", async () => {
  fixture(undefined, { ...listing, persona_rules: [] })
  render(<ModelsPage />)
  expect(await screen.findByText('No persona rules yet')).toBeTruthy()
  cleanup()
  fixture(undefined, { ...listing, persona_rules: [rule('architect', 'Architect', 'gone', false)] })
  render(<ModelsPage />)
  expect(await screen.findByText("gone isn't set up now, so this rule sends no work.")).toBeTruthy()
  cleanup()
  fixture(undefined, { ...listing, models: [model('gateway-only', false)], persona_rules: [] })
  render(<ModelsPage />)
  await screen.findByText('No persona rules yet')
  expect((screen.getByRole('button', { name: 'Add rule' }) as HTMLButtonElement).disabled).toBe(true)
})
