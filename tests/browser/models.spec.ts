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
