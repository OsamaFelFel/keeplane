import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModelsPage } from '../../../components/admin-ui/src/features/models/ModelsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const listing = { models: [{ id: 'coder', provider: 'OpenAI', kind: 'cloud', approved: true, key_choice: 'shared', owned_by_keeplane: true }] }
// Gateway products and versions the page must never name (Spec 004 ST25).
const gatewayNames = /agentgateway|litellm|envoy|semantic router|routellm|plano|\bv?\d+\.\d+(\.\d+)?\b/i

function fixture({ add, runners, setup, models = () => response(listing) }: {
  add?: () => object; runners?: () => object; setup?: () => object; models?: () => object | Promise<object>
} = {}) {
  const request = vi.fn(async (path: string, options: RequestInit = {}) => {
    if (path === '/api/models' && (options.method ?? 'GET') === 'GET') return models()
    if (path === '/api/runners/models' && runners) return runners()
    if (path === '/api/data-classes') return response({ enabled: false, classes: [] })
    if (path === '/api/auth-options') return response({ csrf_token: 'masked' })
    if (path === '/api/models' && add) return add()
    if (path === '/api/models/coder/setup' && setup) return setup()
    return response({})
  })
  vi.stubGlobal('fetch', request)
  return request
}

async function addCloud(name = 'coder') {
  const user = userEvent.setup()
  render(<ModelsPage />)
  await user.click(await screen.findByRole('button', { name: 'Add model' }))
  const dialog = screen.getByRole('dialog')
  await user.selectOptions(within(dialog).getByLabelText('Provider'), 'openai')
  await user.type(within(dialog).getByLabelText('Model', { selector: 'input' }), name)
  await user.type(within(dialog).getByLabelText('Shared key'), 'synthetic-shared-key')
  await user.click(within(dialog).getByRole('button', { name: 'Add model' }))
  return dialog
}

test("MOD-UI-02: a model that isn't added keeps the dialog and says why, as in Model-add-failed", async () => {
  fixture({ add: () => response({ error: 'OpenAI refused the key. Nothing was saved.' }, 503) })
  const dialog = await addCloud('new-model')
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText("new-model wasn't added")).toBeTruthy()
  expect(within(alert).getByText('OpenAI refused the key. Nothing was saved. Check the details and try again.')).toBeTruthy()
  expect((within(dialog).getByLabelText('Model', { selector: 'input' }) as HTMLInputElement).value).toBe('new-model')
  expect((within(dialog).getByLabelText('Shared key') as HTMLInputElement).value).toBe('synthetic-shared-key')
})

test("MOD-UI-07: a model the gateway doesn't register keeps the dialog and says so", async () => {
  fixture({ add: () => response({ error: "The gateway didn't register it. Nothing was saved." }, 503) })
  const dialog = await addCloud('new-model')
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText("new-model wasn't added")).toBeTruthy()
  expect(within(alert).getByText("The gateway didn't register it. Nothing was saved. Check the details and try again.")).toBeTruthy()
})

async function addLocal(name = 'runner-model') {
  const user = userEvent.setup()
  render(<ModelsPage />)
  await user.click(await screen.findByRole('button', { name: 'Add model' }))
  const dialog = screen.getByRole('dialog')
  await user.type(within(dialog).getByLabelText('Runner address'), 'http://runner.example:8080')
  await user.click(within(dialog).getByRole('button', { name: 'Find models' }))
  await within(dialog).findByRole('option', { name })
  await user.selectOptions(within(dialog).getByLabelText('Model', { selector: 'select' }), name)
  await user.click(within(dialog).getByRole('button', { name: 'Add model' }))
  return dialog
}

test("MOD-UI-08: a local model that doesn't answer through the gateway keeps the dialog and says nothing was saved", async () => {
  fixture({
    runners: () => response({ models: ['runner-model'] }),
    add: () => response({ error: "The model didn't answer through the gateway. Nothing was saved." }, 503),
  })
  const dialog = await addLocal()
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText("runner-model wasn't added")).toBeTruthy()
  expect(within(alert).getByText("The model didn't answer through the gateway. Nothing was saved. Check the details and try again.")).toBeTruthy()
  expect(screen.getByRole('dialog')).toBe(dialog)
})

test("MOD-UI-08: when its gateway entry may remain, the dialog doesn't say nothing was saved", async () => {
  const error = "The model didn't answer through the gateway. The model may remain in the gateway without Keeplane approval. Check Models."
  fixture({ runners: () => response({ models: ['runner-model'] }), add: () => response({ error }, 503) })
  const dialog = await addLocal()
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText("runner-model wasn't added")).toBeTruthy()
  expect(within(alert).getByText(error)).toBeTruthy()
  expect(within(alert).queryByText(/Nothing was saved/)).toBeNull()
})

const entryRemains = 'The model may remain in the gateway without Keeplane approval. Check Models.'

test.each([
  ["The gateway didn't register it."],
  ['OpenAI refused the key.'],
])("MOD-UI-08: a cloud model whose gateway entry may remain shows %s and to check Models as given", async reason => {
  const error = `${reason} ${entryRemains}`
  fixture({ add: () => response({ error }, 503) })
  const dialog = await addCloud('new-model')
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText("new-model wasn't added")).toBeTruthy()
  expect(within(alert).getByText(error)).toBeTruthy()
  expect(within(alert).queryByText(/Nothing was saved|try again/)).toBeNull()
})

const approvalNotSaved = "Keeplane couldn't save the model approval. Nothing was saved."
const approvalNotSavedEntryRemains =
  "Keeplane couldn't save the model approval. The model may remain in the gateway without Keeplane approval. Check Models."

test.each([
  ['cloud', () => addCloud('new-model'), 'new-model'],
  ['local', () => addLocal(), 'runner-model'],
])("MOD-UI-09: a %s model whose approval isn't saved says nothing was saved and to try again", async (_kind, add, name) => {
  fixture({ runners: () => response({ models: ['runner-model'] }), add: () => response({ error: approvalNotSaved }, 503) })
  const dialog = await add()
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText(`${name} wasn't added`)).toBeTruthy()
  expect(within(alert).getByText(`${approvalNotSaved} Check the details and try again.`)).toBeTruthy()
})

test.each([
  ['cloud', () => addCloud('new-model'), 'new-model'],
  ['local', () => addLocal(), 'runner-model'],
])("MOD-UI-09: a %s model whose gateway entry may remain says to check Models, not that nothing was saved", async (_kind, add, name) => {
  fixture({ runners: () => response({ models: ['runner-model'] }), add: () => response({ error: approvalNotSavedEntryRemains }, 503) })
  const dialog = await add()
  const alert = await within(dialog).findByRole('alert')
  expect(within(alert).getByText(`${name} wasn't added`)).toBeTruthy()
  expect(within(alert).getByText(approvalNotSavedEntryRemains)).toBeTruthy()
  expect(within(alert).queryByText(/Nothing was saved|try again/)).toBeNull()
})

test('MOD-UI-03: a model already added from the provider is named on the Model field', async () => {
  const request = fixture({ add: () => response({ error: 'coder from OpenAI is already added.' }, 409) })
  const dialog = await addCloud()
  const field = within(dialog).getByLabelText('Model', { selector: 'input' })
  await waitFor(() => expect(field.getAttribute('aria-invalid')).toBe('true'))
  expect(field.parentElement?.textContent).toContain('coder from OpenAI is already added.')
  expect(within(dialog).queryByText(/wasn't added/)).toBeNull()
  expect(request.mock.calls.filter(([path, options]) => path === '/api/models' && options?.method === 'POST')).toHaveLength(1)
})

test('MOD-UI-04: while the models load, each table says Loading models…', async () => {
  fixture({ models: () => new Promise(() => {}) })
  render(<ModelsPage />)
  const table = await screen.findByRole('region', { name: 'Models table' })
  expect(within(table).getByText('Loading models…')).toBeTruthy()
  expect(within(table).queryByRole('button', { name: /Edit|Set up/ })).toBeNull()
})

test("MOD-UI-05: when the gateway isn't answering, a notice says so, Add model is off and Try again reads again", async () => {
  let down = true
  const request = fixture({ models: () => down ? response({ error: 'Gateway unavailable' }, 503) : response(listing) })
  const user = userEvent.setup()
  render(<ModelsPage />)
  const notice = await screen.findByRole('alert')
  expect(notice.textContent).toContain("The model gateway isn't answering.")
  expect(notice.textContent).toContain("Developers' tasks can't reach any model, and models can't be added or changed, until it answers again.")
  expect((screen.getByRole('button', { name: 'Add model' }) as HTMLButtonElement).disabled).toBe(true)
  const reads = () => request.mock.calls.filter(([path]) => path === '/api/models').length
  const before = reads()
  down = false
  await user.click(within(notice).getByRole('button', { name: 'Try again' }))
  await screen.findByRole('row', { name: /coder/ })
  expect(reads()).toBe(before + 1)
  expect(screen.queryByRole('alert')).toBeNull()
  expect((screen.getByRole('button', { name: 'Add model' }) as HTMLButtonElement).disabled).toBe(false)
})

test('MOD-UI-05: models already listed cannot be edited once the gateway stops answering', async () => {
  let down = false
  fixture({ models: () => down ? response({ error: 'Gateway unavailable' }, 503) : response(listing) })
  const user = userEvent.setup()
  render(<ModelsPage />)
  await user.click(await within(await screen.findByRole('row', { name: /coder/ })).findByRole('button', { name: 'Edit' }))
  down = true
  // Saving reads the models again, and that read finds the gateway down.
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^Save/ }))
  await screen.findByText("The model gateway isn't answering.")
  const edit = within(screen.getByRole('row', { name: /coder/ })).getByRole('button', { name: 'Edit' }) as HTMLButtonElement
  expect(edit.disabled).toBe(true)
  expect((screen.getByRole('button', { name: 'Add model' }) as HTMLButtonElement).disabled).toBe(true)
})

test('MOD-UI-06: the page names no gateway product or version, up or down', async () => {
  let down = false
  fixture({ models: () => down ? response({ error: 'Gateway unavailable' }, 503) : response(listing) })
  render(<ModelsPage />)
  await screen.findByRole('row', { name: /coder/ })
  expect(document.body.textContent).not.toMatch(gatewayNames)
  cleanup(); down = true
  render(<ModelsPage />)
  await screen.findByRole('alert')
  expect(document.body.textContent).not.toMatch(gatewayNames)
})

test.each([
  ["The replacement key didn't answer through the gateway. A verification model may need cleanup. Check Models."],
  ["The replacement key didn't work. The model may need admin attention. Check Models."],
  ["Keeplane couldn't save the change. The model may need admin attention. Check Models."],
])('MOD-UI-10: a replaced key whose previous key isn\'t restored keeps Edit open and shows "%s" as given', async error => {
  fixture({ setup: () => response({ error }, 503) })
  const user = userEvent.setup()
  render(<ModelsPage />)
  await user.click(await within(await screen.findByRole('row', { name: /coder/ })).findByRole('button', { name: 'Edit' }))
  const dialog = screen.getByRole('dialog')
  await user.type(within(dialog).getByLabelText('Replace shared key'), 'synthetic-replacement-key')
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  const alert = await within(dialog).findByRole('alert')
  expect(alert.textContent).toBe(error)
  expect(screen.getByRole('dialog')).toBe(dialog)
})

const OWN_KEYS_REFUSED = "Keeplane can't pass developers' own keys to a gateway it doesn't run yet, so use No key for this model. Nothing was saved."

function editFixture(listing: object, setup: (body: Record<string, unknown>) => object) {
  const bodies: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit = {}) => {
    if (path === '/api/models' && (options.method ?? 'GET') === 'GET') return response(listing)
    if (path === '/api/data-classes') return response({ enabled: true, classes: [{ name: 'Public' }, { name: 'Internal' }] })
    if (path === '/api/auth-options') return response({ csrf_token: 'masked' })
    if (path === '/api/models/coder/setup') {
      const body = JSON.parse(String(options.body))
      bodies.push(body)
      return setup(body)
    }
    return response({})
  }))
  return bodies
}

async function openEdit() {
  const user = userEvent.setup()
  render(<ModelsPage />)
  await user.click(await within(await screen.findByRole('row', { name: /coder/ })).findByRole('button', { name: /Edit|Set up/ }))
  return { user, dialog: screen.getByRole('dialog') }
}

const radio = (dialog: HTMLElement, name: string) => within(dialog).getByRole('radio', { name }) as HTMLInputElement
const model = (key_choice: string, kind = 'cloud') => ({ id: 'coder', provider: 'OpenAI', kind, approved: true, key_choice, approved_classes: ['Public'], owned_by_keeplane: true })

test.each([
  // [current, kind, customer-run gateway, enabled shared, own, none]
  ['shared', 'cloud', false, [true, false, false]],
  ['none', 'cloud', false, [false, true, true]],
  ['none', 'real-local', false, [false, false, true]],
  ['personal', 'cloud', false, [false, true, false]],
  ['personal', 'cloud', true, [false, true, true]],
  ['none', 'cloud', true, [false, true, true]],
] as const)('MOD-UI-11: Edit shows the three key choices and lets you pick only those it can save (%s, %s, customer-run gateway %s)', async (current, kind, customer, enabled) => {
  editFixture({ models: [model(current, kind)], customer_run_gateway: customer }, () => response({}))
  const { dialog } = await openEdit()
  const radios = ['One shared key for the organization', 'Each developer adds their own key', 'No key needed'].map(name => radio(dialog, name))
  expect(radios.map(item => !item.disabled)).toEqual(enabled)
  expect(radios.map(item => item.checked)).toEqual(['shared', 'personal', 'none'].map(value => value === current))
})

test('MOD-UI-12: on a customer-run gateway an own-key model saves No key with its class change, and own key is refused', async () => {
  const bodies = editFixture({ models: [model('personal')], customer_run_gateway: true },
    body => body.key_choice === 'none' ? response({ key_choice: 'none' }) : response({ error: OWN_KEYS_REFUSED }, 422))
  const { user, dialog } = await openEdit()
  await user.click(within(dialog).getByRole('checkbox', { name: 'Internal' }))
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  expect((await within(dialog).findByRole('alert')).textContent).toBe(`${OWN_KEYS_REFUSED} Check the details and try again.`)
  expect(within(dialog).queryByRole('button', { name: 'Use No key' })).toBeNull()
  await user.click(radio(dialog, 'No key needed'))
  expect(within(dialog).queryByText(/Developers add their own keys from the CLI/)).toBeNull()
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(bodies).toEqual([
    { key_choice: 'personal', approved_classes: ['Public', 'Internal'] },
    { key_choice: 'none', approved_classes: ['Public', 'Internal'] },
  ])
  expect(await screen.findByText('Saved coder.')).toBeTruthy()
})

test('MOD-UI-13: a model with no key can move to developers\' own keys', async () => {
  const bodies = editFixture({ models: [model('none')] }, () => response({ key_choice: 'personal' }))
  const { user, dialog } = await openEdit()
  await user.click(radio(dialog, 'Each developer adds their own key'))
  expect(within(dialog).getByText(/Developers add their own keys from the CLI/)).toBeTruthy()
  expect(within(dialog).getByText(/Keeplane checks that the provider answers/)).toBeTruthy()
  await user.click(within(dialog).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(bodies).toEqual([{ key_choice: 'personal', approved_classes: ['Public'] }])
})

const GREYED_OUT_HINT = "To use a choice that's greyed out, remove the model and add it again with that key choice."

test.each([
  ['shared', 'cloud', false],
  ['personal', 'cloud', true],
  ['none', 'real-local', false],
] as const)('MOD-UI-14: with a greyed-out choice, Edit says how to use it and screen readers hear it on the group (%s, %s, customer-run gateway %s)', async (current, kind, customer) => {
  editFixture({ models: [model(current, kind)], customer_run_gateway: customer }, () => response({}))
  const { dialog } = await openEdit()
  const group = within(dialog).getByRole('radiogroup', { name: 'Provider key' })
  expect(within(group).getByText(GREYED_OUT_HINT)).toBeTruthy()
  const described = (group.getAttribute('aria-describedby') ?? '').split(' ').map(id => document.getElementById(id)?.textContent)
  expect(described).toEqual([GREYED_OUT_HINT])
})
