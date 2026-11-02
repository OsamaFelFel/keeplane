import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModelsPage } from '../../../components/admin-ui/src/features/models/ModelsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const listing = { models: [{ id: 'coder', provider: 'OpenAI', kind: 'cloud', approved: true, key_choice: 'shared', owned_by_keeplane: true }] }
// Gateway products and versions the page must never name (Spec 004 ST25).
const gatewayNames = /agentgateway|litellm|envoy|semantic router|routellm|plano|\bv?\d+\.\d+(\.\d+)?\b/i

function fixture({ add, models = () => response(listing) }: {
  add?: () => object; models?: () => object | Promise<object>
} = {}) {
  const request = vi.fn(async (path: string, options: RequestInit = {}) => {
    if (path === '/api/models' && (options.method ?? 'GET') === 'GET') return models()
    if (path === '/api/data-classes') return response({ enabled: false, classes: [] })
    if (path === '/api/auth-options') return response({ csrf_token: 'masked' })
    if (path === '/api/models' && add) return add()
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
