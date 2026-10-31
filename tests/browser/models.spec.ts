import { expect, test, type Page } from '@playwright/test'

type Model = { id: string; provider: string; kind: string; approved: boolean; key_choice: string | null; approved_classes: string[]; owned_by_keeplane: boolean }

async function mockModels(page: Page, initial: Model[] = []) {
  const models = [...initial]
  await page.route('**/api/identity', route => route.fulfill({ json: { id: 'admin', username: 'first-admin', role: 'admin' } }))
  await page.route('**/api/data-classes', route => route.fulfill({ json: { enabled: false, classes: [] } }))
  await page.route(url => url.pathname === '/api/models', async route => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      expect(route.request().headers()['x-keeplane-action']).toBe('1')
      models.push({ id: body.name, provider: 'Local runner', kind: 'real-local', approved: true,
        key_choice: 'none', approved_classes: [], owned_by_keeplane: true })
      return route.fulfill({ json: { name: body.name, approved_classes: [] } })
    }
    return route.fulfill({ json: { models } })
  })
  return models
}

test('MO-UI-01: Models table uses the React shell and keeps narrow pages contained', async ({ page }) => {
  await mockModels(page, [
    { id: 'approved-model', provider: 'Local runner', kind: 'real-local', approved: true, key_choice: 'none', approved_classes: [], owned_by_keeplane: true },
    { id: 'outside-model', provider: 'OpenAI', kind: 'cloud', approved: false, key_choice: null, approved_classes: [], owned_by_keeplane: false },
  ])
  await page.goto('/app/models')
  await expect(page.getByRole('heading', { name: 'Models and routing' })).toBeVisible()
  await expect(page.getByRole('row', { name: /approved-model/ })).toContainText('Local')
  await expect(page.getByRole('row', { name: /outside-model/ })).toContainText('Added outside Keeplane')
  await expect(page.getByRole('columnheader', { name: 'Approved for' })).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready)
  await expect(page).toHaveScreenshot('models-1280.png', { fullPage: true })
  await page.setViewportSize({ width: 320, height: 800 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  await expect(page).toHaveScreenshot('models-320.png', { fullPage: true })
  await page.getByRole('button', { name: 'Add model' }).click()
  const heights = await page.evaluate(() => ({
    source: document.querySelector<HTMLSelectElement>('#model-source')?.getBoundingClientRect().height,
    address: document.querySelector<HTMLInputElement>('#runner-address')?.getBoundingClientRect().height,
  }))
  expect(heights.source).toBeGreaterThanOrEqual(44)
  expect(heights.address).toBeGreaterThanOrEqual(44)
})

test('MO-UI-02: finding and adding a local runner model updates the table', async ({ page }) => {
  await mockModels(page)
  await page.route('**/api/runners/models', route => {
    expect(route.request().postDataJSON().address).toBe('http://qwen:8080')
    return route.fulfill({ json: { models: ['qwen2.5-coder:0.5b'], runtime: {
      'qwen2.5-coder:0.5b': { active_context_tokens: 4096 },
    } } })
  })
  await page.goto('/app/models')
  await page.getByRole('button', { name: 'Add model' }).click()
  await page.getByLabel('Runner address').fill('http://qwen:8080')
  await page.getByRole('button', { name: 'Find models' }).click()
  await page.getByLabel('Model', { exact: true }).selectOption('qwen2.5-coder:0.5b')
  await expect(page.getByText('Active context: 4,096 tokens.')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Add model' }).click()
  await expect(page.getByRole('row', { name: /qwen2.5-coder:0.5b/ })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('Added qwen2.5-coder:0.5b.')
})

test('MO-UI-03: an unsupported shared key keeps the Add dialog and its entries', async ({ page }) => {
  await mockModels(page)
  await page.route('**/api/models', route => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 422, json: {
      error: 'Shared provider keys need a supported delivery path to the customer-run gateway',
    } })
    return route.fallback()
  })
  await page.goto('/app/models')
  await page.getByRole('button', { name: 'Add model' }).click()
  await page.getByLabel('Provider').selectOption('openai')
  await page.getByLabel('Model', { exact: true }).fill('cloud-example')
  await page.getByLabel('Shared key', { exact: true }).fill('disposable-fixture-key')
  await page.getByRole('dialog').getByRole('button', { name: 'Add model' }).click()
  await expect(page.getByRole('alert')).toContainText('supported delivery path')
  await expect(page.getByLabel('Model', { exact: true })).toHaveValue('cloud-example')
  await expect(page.getByLabel('Shared key', { exact: true })).toHaveValue('disposable-fixture-key')
  await expect(page.getByRole('dialog')).toBeVisible()
})

test('MO-UI-04: removing an outside setup leaves its gateway model listed', async ({ page }) => {
  const model: Model = { id: 'outside-model', provider: 'Local runner', kind: 'real-local', approved: true,
    key_choice: 'none', approved_classes: [], owned_by_keeplane: false }
  await mockModels(page, [model])
  await page.route('**/api/models/outside-model/setup', route => {
    expect(route.request().method()).toBe('DELETE')
    model.approved = false
    return route.fulfill({ json: { removed_from_keeplane: true, gateway_model_preserved: true } })
  })
  await page.goto('/app/models')
  await page.getByRole('row', { name: /outside-model/ }).getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('button', { name: 'Remove setup' }).click()
  await page.getByRole('dialog', { name: 'Remove Keeplane setup?' }).getByRole('button', { name: 'Remove setup' }).click()
  await expect(page.getByRole('row', { name: /outside-model/ })).toContainText('Added outside Keeplane')
  await expect(page.getByRole('status')).toContainText('The gateway model remains.')
})

test('MO-UI-05 MODEL-01 EDIT-01: setup and editing retain class choices after a refused save', async ({ page }) => {
  const model: Model = { id: 'outside-model', provider: 'Local runner', kind: 'real-local', approved: false,
    key_choice: 'none', approved_classes: [], owned_by_keeplane: false }
  await mockModels(page, [model])
  await page.route('**/api/data-classes', route => route.fulfill({ json: {
    enabled: true, classes: [{ name: 'Public' }, { name: 'Internal' }],
  } }))
  let refuse = true
  await page.route('**/api/models/outside-model/setup', route => {
    expect(route.request().method()).toBe('POST')
    if (refuse) return route.fulfill({ status: 503, json: { error: 'The gateway did not answer.' } })
    model.approved = true
    model.approved_classes = route.request().postDataJSON().approved_classes
    return route.fulfill({ json: { model_id: model.id, approved_classes: model.approved_classes } })
  })
  await page.goto('/app/models')
  await page.getByRole('row', { name: /outside-model/ }).getByRole('button', { name: 'Set up', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Set up outside-model' })
  await dialog.getByRole('checkbox', { name: 'Public', exact: true }).check()
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('The gateway did not answer.')
  await expect(dialog.getByRole('checkbox', { name: 'Public', exact: true })).toBeChecked()
  refuse = false
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await page.getByRole('row', { name: /outside-model/ }).getByRole('button', { name: 'Edit', exact: true }).click()
  const edit = page.getByRole('dialog', { name: 'Edit outside-model' })
  await expect(edit.getByRole('checkbox', { name: 'Public', exact: true })).toBeChecked()
  await edit.getByRole('checkbox', { name: 'Internal', exact: true }).check()
  await edit.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(edit).not.toBeVisible()
  await expect(page.getByRole('row', { name: /outside-model/ })).toContainText('Public, Internal')
})

test('MO-UI-06: Personal add sends no shared key and keeps the choice after refusal', async ({ page }) => {
  await mockModels(page)
  let refuse = true
  let submitted = 0
  await page.route('**/api/models', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    submitted += 1
    expect(route.request().postDataJSON()).toEqual({ name: 'personal-coder', model: 'personal-coder', source: 'openai', key_choice: 'personal' })
    expect(route.request().postData()).not.toContain('disposable-shared-key')
    return route.fulfill(refuse ? { status: 503, json: { error: "OpenAI didn't answer. Nothing was saved." } } : { json: { name: 'personal-coder' } })
  })
  await page.goto('/app/models')
  await page.getByRole('button', { name: 'Add model' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add model' })
  await dialog.getByLabel('Provider').selectOption('openai')
  await dialog.getByLabel('Model', { exact: true }).fill('personal-coder')
  await dialog.getByLabel('Shared key', { exact: true }).fill('disposable-shared-key')
  await dialog.getByRole('radio', { name: 'Each developer adds their own key', exact: true }).check()
  await expect(dialog.getByLabel('Shared key', { exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Add model', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText("OpenAI didn't answer.")
  await expect(dialog.getByRole('radio', { name: 'Each developer adds their own key', exact: true })).toBeChecked()
  await expect(dialog.getByLabel('Model', { exact: true })).toHaveValue('personal-coder')
  refuse = false
  await dialog.getByRole('button', { name: 'Add model', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(submitted).toBe(2)
})

test('MO-UI-07: editing a Personal model preserves its key choice and explains the provider check', async ({ page }) => {
  const model: Model = { id: 'personal-coder', provider: 'OpenAI', kind: 'cloud', approved: true,
    key_choice: 'personal', approved_classes: [], owned_by_keeplane: true }
  await mockModels(page, [model])
  await page.route('**/api/data-classes', route => route.fulfill({ json: {
    enabled: true, classes: [{ name: 'Public' }],
  } }))
  await page.route('**/api/models/personal-coder/setup', route => {
    expect(route.request().postDataJSON()).toEqual({ key_choice: 'personal', approved_classes: ['Public'] })
    return route.fulfill({ json: { model_id: model.id, key_choice: 'personal', approved_classes: ['Public'] } })
  })
  await page.goto('/app/models')
  await page.getByRole('row', { name: /personal-coder/ }).getByRole('button', { name: 'Edit', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Edit personal-coder' })
  await expect(dialog.getByText('Each developer adds their own key', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/Keeplane checks that the provider answers/)).toBeVisible()
  await expect(dialog.getByText('No key needed', { exact: true })).toHaveCount(0)
  await expect(dialog.getByLabel('Replace shared key', { exact: true })).toHaveCount(0)
  await dialog.getByRole('checkbox', { name: 'Public', exact: true }).check()
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).not.toBeVisible()
})

type Level = { level: string; name: string; model_id: string | null; keeplane_pick: string | null; changed_by_admin: boolean; admin_model_id: string | null; admin_model_set_up: boolean | null }

async function mockLevels(page: Page) {
  const models: Model[] = ['small-coder', 'large-coder'].map(id => ({ id, provider: 'Local runner', kind: 'real-local', approved: true,
    key_choice: 'none', approved_classes: [], owned_by_keeplane: true }))
  const picks: Record<string, string> = { simple: 'small-coder', standard: 'small-coder', complex: 'large-coder' }
  const admin: Record<string, string> = {}
  const levels = (): Level[] => [['simple', 'Simple'], ['standard', 'Standard'], ['complex', 'Complex']].map(([level, name]) => ({
    level, name, model_id: admin[level] ?? picks[level], keeplane_pick: picks[level], changed_by_admin: level in admin,
    admin_model_id: admin[level] ?? null, admin_model_set_up: level in admin ? true : null,
  }))
  await page.route('**/api/identity', route => route.fulfill({ json: { id: 'admin', username: 'first-admin', role: 'admin' } }))
  await page.route('**/api/data-classes', route => route.fulfill({ json: { enabled: false, classes: [] } }))
  await page.route(url => url.pathname === '/api/models', route => route.fulfill({ json: { models, levels: levels() } }))
  const writes: unknown[] = []
  await page.route(url => url.pathname.startsWith('/api/levels/'), route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().headers()['x-keeplane-action']).toBe('1')
    const level = new URL(route.request().url()).pathname.split('/').pop()!
    const { model_id: modelId } = route.request().postDataJSON()
    writes.push({ level, modelId })
    if (modelId === null) delete admin[level]
    else admin[level] = modelId
    return route.fulfill({ json: { levels: levels() } })
  })
  return { writes, admin }
}

test("MO-UI-08 ST13: change a level with the keyboard and go back to Keeplane's pick", async ({ page }) => {
  const { writes } = await mockLevels(page)
  await page.goto('/app/models')
  const table = page.getByRole('region', { name: 'Complexity levels table' })
  await expect(table.getByRole('row', { name: /Simple/ })).toContainText("small-coder · Keeplane's pick")
  await expect(table.getByRole('row', { name: /Complex/ })).toContainText("large-coder · Keeplane's pick")
  await table.getByRole('button', { name: 'Change Complex' }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Model for Complex' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText("Keeplane's pick is large-coder.")).toBeVisible()
  expect(await dialog.getByLabel('Model', { exact: true }).evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  expect(await dialog.evaluate(element => element.getBoundingClientRect().width)).toBeLessThanOrEqual(560)
  await dialog.getByLabel('Model', { exact: true }).selectOption('small-coder')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(table.getByRole('row', { name: /Complex/ })).toContainText('small-coder · changed by an admin')
  await table.getByRole('button', { name: 'Change Complex' }).click()
  await dialog.getByRole('button', { name: "Use Keeplane's pick" }).click()
  await expect(dialog).not.toBeVisible()
  await expect(table.getByRole('row', { name: /Complex/ })).toContainText("large-coder · Keeplane's pick")
  expect(writes).toEqual([{ level: 'complex', modelId: 'small-coder' }, { level: 'complex', modelId: null }])
  await page.setViewportSize({ width: 320, height: 800 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
})

test('MO-UI-09 ST23: a model an admin-changed level uses cannot be removed', async ({ page }) => {
  const { admin } = await mockLevels(page)
  admin.standard = 'large-coder'
  let deletes = 0
  await page.route('**/api/models/large-coder/setup', route => { deletes += 1; return route.fulfill({ status: 500, json: {} }) })
  await page.goto('/app/models')
  await page.getByRole('row', { name: /^large-coder/ }).getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByRole('dialog', { name: 'Edit large-coder' }).getByRole('button', { name: 'Remove model' }).click()
  const dialog = page.getByRole('dialog', { name: 'large-coder is still in use' })
  await expect(dialog.getByRole('listitem')).toHaveText(['Complexity level: Standard'])
  await expect(dialog).toContainText('Move these to another model first, then remove it.')
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).not.toBeVisible()
  expect(deletes).toBe(0)
})

type PersonaRule = { persona: string; name: string; model_id: string; model_set_up: boolean }

async function mockRules(page: Page) {
  const { admin } = await mockLevels(page)
  const personas = [{ persona: 'architect', name: 'Architect' }, { persona: 'developer', name: 'Developer' }, { persona: 'frontend', name: 'Frontend' }]
  const rules: Record<string, string> = {}
  const rows = (): PersonaRule[] => personas.filter(({ persona }) => persona in rules)
    .map(({ persona, name }) => ({ persona, name, model_id: rules[persona], model_set_up: true }))
  const models: Model[] = ['small-coder', 'large-coder'].map(id => ({ id, provider: 'Local runner', kind: 'real-local', approved: true,
    key_choice: 'none', approved_classes: [], owned_by_keeplane: true }))
  await page.route(url => url.pathname === '/api/models', route => route.fulfill({ json: {
    models, levels: [], persona_rules: rows(), personas,
  } }))
  const writes: unknown[] = []
  await page.route(url => url.pathname.startsWith('/api/persona-rules/'), route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().headers()['x-keeplane-action']).toBe('1')
    const persona = new URL(route.request().url()).pathname.split('/').pop()!
    const { model_id: modelId } = route.request().postDataJSON()
    writes.push({ persona, modelId })
    rules[persona] = modelId
    return route.fulfill({ json: { persona_rules: rows() } })
  })
  return { writes, rules, admin }
}

test('MO-UI-10 ST15: add a persona rule with the keyboard', async ({ page }) => {
  const { writes } = await mockRules(page)
  await page.goto('/app/models')
  const table = page.getByRole('region', { name: 'Persona rules table' })
  await expect(table).toContainText('No persona rules yet')
  await page.getByRole('button', { name: 'Add rule', exact: true }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Add persona rule' })
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate(element => element.getBoundingClientRect().width)).toBeLessThanOrEqual(560)
  for (const label of ['When the persona is', 'Route to']) {
    expect(await dialog.getByLabel(label, { exact: true }).evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44)
  }
  await dialog.getByLabel('When the persona is', { exact: true }).selectOption('architect')
  await dialog.getByLabel('Route to', { exact: true }).selectOption('large-coder')
  await dialog.getByRole('button', { name: 'Add rule', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(table.getByRole('row', { name: /Persona is Architect/ })).toContainText('large-coder')
  await expect(page.getByRole('status')).toHaveText("Architect's work now goes to large-coder.")
  expect(writes).toEqual([{ persona: 'architect', modelId: 'large-coder' }])
  await page.setViewportSize({ width: 320, height: 800 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
})

test('MO-UI-11 ST23: a model a persona rule uses cannot be removed', async ({ page }) => {
  const { rules } = await mockRules(page)
  rules.architect = 'large-coder'
  let deletes = 0
  await page.route('**/api/models/large-coder/setup', route => { deletes += 1; return route.fulfill({ status: 500, json: {} }) })
  await page.goto('/app/models')
  await page.getByRole('row', { name: /^large-coder/ }).getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByRole('dialog', { name: 'Edit large-coder' }).getByRole('button', { name: 'Remove model' }).click()
  const dialog = page.getByRole('dialog', { name: 'large-coder is still in use' })
  await expect(dialog.getByRole('listitem')).toHaveText(['Persona rule: Architect'])
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).not.toBeVisible()
  expect(deletes).toBe(0)
})
