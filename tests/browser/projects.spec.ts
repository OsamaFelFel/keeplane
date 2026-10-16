import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/identity', route => route.fulfill({ json: { id: 'fixture-admin', username: 'preview-admin', role: 'admin' } }))
  await page.route('**/api/projects?*', route => route.fulfill({ json: {
    projects: [{ id: 'fixture-project', name: 'Example', initialized: false,
      users: [{ id: 'fixture-user', username: 'developer-one' }],
      data_class: { id: 'confidential', name: 'Confidential' } }],
    classes_enabled: true, page: 1, page_size: 25, total: 1, has_more: false,
  } }))
  await page.goto('/app/projects')
  await expect(page.getByText('developer-one', { exact: true })).toBeVisible()
})

test('PRJ-UI-01: Projects renders first-use records through the admin shell', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Projects', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('cell', { name: 'Not yet', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Confidential', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
})

test('PRJ-UI-02: Projects contains and keyboard-scrolls its table at320px', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const table = page.getByRole('region', { name: 'Projects table' })
  await table.focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => table.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Menu', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Projects', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
})

test('PRJ-UI-03: Set class saves once and returns focus to its row action', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await page.route('**/api/data-classes', route => route.fulfill({ json: { enabled: true, classes: [{ id: 'public', name: 'Public' }, { id: 'confidential', name: 'Confidential' }] } }))
  await page.route('**/api/auth-options', route => route.fulfill({ json: { csrf_token: 'fixture-masked-token' } }))
  let writes = 0
  await page.route('**/api/projects/fixture-project/class', route => {
    writes += 1
    expect(route.request().postDataJSON()).toEqual({ class_id: 'public' })
    return route.fulfill({ json: { id: 'fixture-project', name: 'Example', data_class: { id: 'public', name: 'Public' } } })
  })
  await page.getByRole('button', { name: 'Set class', exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByLabel('Data class', { exact: true }).selectOption('public')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('cell', { name: 'Public', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Set class', exact: true })).toBeFocused()
  expect(writes).toBe(1)
})

test('PRJ-UI-04: A lost response checks current state without repeating the write', async ({ page }) => {
  await page.route('**/api/data-classes', route => route.fulfill({ json: { enabled: true, classes: [{ id: 'public', name: 'Public' }] } }))
  await page.route('**/api/auth-options', route => route.fulfill({ json: { csrf_token: 'fixture-masked-token' } }))
  let writes = 0
  await page.route('**/api/projects/fixture-project/class', route => {
    if (route.request().method() === 'PUT') { writes += 1; return route.abort('connectionreset') }
    return route.fulfill({ json: { id: 'fixture-project', name: 'Example', classes_enabled: true, data_class: { id: 'public', name: 'Public' } } })
  })
  await page.getByRole('button', { name: 'Set class', exact: true }).click()
  await page.getByLabel('Data class', { exact: true }).selectOption('public')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Check', exact: true })).toBeVisible()
  await expect(page.getByLabel('Data class', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Check', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('cell', { name: 'Public', exact: true })).toBeVisible()
  expect(writes).toBe(1)
})
