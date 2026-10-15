import { expect, test, type Page } from '@playwright/test'

const firstRecord = { id: 1, kind: 'break_glass_sign_ins', when: '2026-10-10T00:00:00+00:00', who: 'first-admin', what: 'Break-glass admin signed in.' }
const secondRecord = { id: 2, kind: 'settings', when: '2026-10-10T00:01:00+00:00', who: 'admin-example', what: 'Turned data classes on' }
const firstPage = [firstRecord, ...Array.from({ length: 24 }, (_, index) => ({
  ...secondRecord, id: index + 2, who: `admin-example-${String(index + 1).padStart(2, '0')}`,
}))]

async function mockAudit(page: Page) {
  const options = { settings: false, held_requests: false, model_answers: false }
  await page.route('**/api/identity', route => route.fulfill({ json: { id: 'admin', username: 'first-admin', role: 'admin' } }))
  await page.route(url => url.pathname.startsWith('/api/audit/options'), async route => {
    if (route.request().method() === 'PUT') {
      expect(route.request().headers()['x-keeplane-action']).toBe('1')
      const kind = new URL(route.request().url()).pathname.split('/').at(-1) as keyof typeof options
      options[kind] = route.request().postDataJSON().enabled
    }
    await route.fulfill({ json: { options } })
  })
  await page.route(url => url.pathname === '/api/audit/records', route => {
    const query = new URL(route.request().url()).searchParams
    const kind = query.get('kind')
    const search = query.get('search')
    const pageNumber = Number(query.get('page'))
    const records = kind === 'break_glass_sign_ins' || search === 'first-admin' ? [firstRecord]
      : pageNumber === 2 ? [{ ...secondRecord, id: 26, who: 'admin-example-final' }] : firstPage
    const total = kind === 'break_glass_sign_ins' || search === 'first-admin' ? 1 : 26
    return route.fulfill({ json: { records, total, page: pageNumber, page_size: 25, has_more: total > pageNumber * 25 } })
  })
}

test('AU-UI-01: break-glass recording is visible and cannot be switched off', async ({ page }) => {
  await mockAudit(page)
  await page.goto('/app/audit')
  await expect(page.getByRole('heading', { name: 'Audit' })).toBeVisible()
  const mandatory = page.getByRole('switch', { name: 'Sign-ins with the break-glass admin' })
  await expect(mandatory).toBeChecked()
  await expect(mandatory).toBeDisabled()
  await expect(page.getByRole('switch', { name: 'Changes to models, routing and data classes' })).not.toBeChecked()
  await expect(page.getByRole('switch', { name: 'Requests held back by personal-data detection' })).not.toBeChecked()
  await expect(page.getByRole('switch', { name: 'Which model answered each task' })).not.toBeChecked()
  await expect(page.getByRole('option', { name: 'Break-glass sign-ins' })).toHaveCount(1)
})

test('AU-UI-02: optional recording changes one kind and persists on refresh', async ({ page }) => {
  await mockAudit(page)
  await page.goto('/app/audit')
  const settings = page.getByRole('switch', { name: 'Changes to models, routing and data classes' })
  await expect(settings).not.toBeChecked()
  await settings.check()
  await expect(page.getByRole('status')).toContainText('Recording turned on.')
  await expect(page.getByRole('switch', { name: 'Which model answered each task' })).not.toBeChecked()
  await page.reload()
  await expect(settings).toBeChecked()
  await expect(page.getByRole('switch', { name: 'Sign-ins with the break-glass admin' })).toBeChecked()
})

test('AU-UI-03: search, kind filter, paging and narrow table use the records API', async ({ page }) => {
  await mockAudit(page)
  await page.goto('/app/audit')
  await expect(page.getByRole('row', { name: /first-admin/ })).toBeVisible()
  await expect(page.getByText('Showing 1–25 of 26 records')).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
  await expect(page).toHaveScreenshot('audit-1280.png')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('row', { name: /admin-example-final/ })).toBeVisible()
  await expect(page.getByText('Showing 26–26 of 26 records')).toBeVisible()
  await page.getByLabel('Show').selectOption('break_glass_sign_ins')
  await expect(page.getByRole('row', { name: /first-admin/ })).toBeVisible()
  await expect(page.getByRole('row', { name: /admin-example/ })).toHaveCount(0)
  await page.getByLabel('Show').selectOption('all')
  await page.getByLabel('Search records').fill('first-admin')
  await expect(page.getByText('Showing 1–1 of 1 records')).toBeVisible()
  await page.setViewportSize({ width: 320, height: 800 })
  const sizes = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    table: document.querySelector('[data-slot="table-container"]')?.scrollWidth,
    viewport: document.querySelector('[data-slot="table-container"]')?.clientWidth,
    search: document.querySelector<HTMLInputElement>('#search-records')?.getBoundingClientRect().height,
    select: document.querySelector<HTMLSelectElement>('#record-kind')?.getBoundingClientRect().height,
  }))
  expect(sizes.document).toBeLessThanOrEqual(320)
  expect(sizes.table).toBeGreaterThan(sizes.viewport!)
  expect(sizes.search).toBeGreaterThanOrEqual(44)
  expect(sizes.select).toBeGreaterThanOrEqual(44)
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect(page).toHaveScreenshot('audit-320.png', { fullPage: true })
})

test('AU-UI-04: failed writes roll back and failed record loads do not show stale rows', async ({ page }) => {
  await mockAudit(page)
  await page.route('**/api/audit/options/settings', route => route.fulfill({
    status: 503, json: { error: 'Settings storage is unavailable' },
  }))
  await page.goto('/app/audit')
  const settings = page.getByRole('switch', { name: 'Changes to models, routing and data classes' })
  await expect(settings).not.toBeChecked()
  await settings.check()
  await expect(page.getByRole('alert')).toContainText('Settings storage is unavailable')
  await expect(settings).not.toBeChecked()
  await expect(page.getByRole('row', { name: /first-admin/ })).toBeVisible()
  await page.route(url => url.pathname === '/api/audit/records' && url.searchParams.get('kind') === 'settings',
    route => route.fulfill({ status: 503, json: { error: 'Audit storage is unavailable' } }))
  await page.getByLabel('Show').selectOption('settings')
  await expect(page.getByRole('alert').last()).toContainText('Audit storage is unavailable')
  await expect(page.getByRole('row', { name: /first-admin/ })).toHaveCount(0)
})

test('AU-UI-05: initial search settling does not undo a quick Next click', async ({ page }) => {
  await mockAudit(page)
  await page.goto('/app/audit')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('row', { name: /admin-example-final/ })).toBeVisible()
  await page.waitForTimeout(350)
  await expect(page.getByText('Showing 26–26 of 26 records')).toBeVisible()
})
