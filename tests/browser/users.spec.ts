import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

const users = [
  { id: 'break-glass', username: 'first-admin', role: 'admin', sign_in: 'break-glass', managed: true },
  { id: 'admin-1', username: 'admin-example', role: 'admin', sign_in: 'local', managed: false },
  { id: 'developer-1', username: 'developer-example', role: 'developer', sign_in: 'local', managed: false },
]

async function mockAdmin(page: Page, listedUsers = users) {
  await page.route('**/api/identity', route => route.fulfill({ json: {
    id: 'break-glass', username: 'first-admin', role: 'admin',
  } }))
  await page.route(url => url.pathname === '/api/users' && url.searchParams.has('page'),
    route => route.fulfill({ json: { users: listedUsers, page: 1, page_size: 25, total: listedUsers.length, has_more: false } }))
  await page.route('**/api/edition-note/consume', route => route.fulfill({ json: { show: false } }))
}

test('BR-01: local sign-in offers no SSO or self-registration', async ({ page }) => {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: 'Sign in to Keeplane' })).toBeVisible()
  await expect(page.getByLabel('Username')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByText('Sign in with single sign-on')).toHaveCount(0)
  await expect(page.getByText('Create an account')).toHaveCount(0)
})

test('BR-02: the live first admin can open Users but has no role action', async ({ page }) => {
  const password = readFileSync('/private/tmp/keeplane-accounts-trial/first-admin-password', 'utf8').trim()
  await page.goto('/app/')
  await page.getByLabel('Username').fill('first-admin')
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
  const firstAdmin = page.getByRole('row', { name: /first-admin/ })
  await expect(firstAdmin).toContainText('Break-glass, managed at infrastructure level')
  await expect(firstAdmin.getByRole('button', { name: 'Change role' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Create user' }).click()
  await expect(page.getByRole('dialog', { name: 'Create user' })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Developer' })).toBeChecked()
})

test('BR-03: desktop and narrow Users layouts match stable screenshots', async ({ page }) => {
  const externalRequests: string[] = []
  page.on('request', request => {
    if (new URL(request.url()).origin !== (process.env.KEEPLANE_BASE_URL ?? 'http://127.0.0.1:3000')) externalRequests.push(request.url())
  })
  await mockAdmin(page)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app/')
  await expect(page.getByRole('row', { name: /developer-example/ })).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
  await expect(page).toHaveScreenshot('users-1280.png', { fullPage: true })

  await page.setViewportSize({ width: 320, height: 800 })
  await expect(page.getByRole('button', { name: 'Menu' })).toBeVisible()
  const narrow = await page.evaluate(() => {
    const table = document.querySelector('[data-slot="table-container"]')
    const search = document.querySelector<HTMLInputElement>('#search-users')
    return {
      documentWidth: document.documentElement.scrollWidth,
      tableWidth: table?.scrollWidth,
      tableViewport: table?.clientWidth,
      searchHeight: search?.getBoundingClientRect().height,
    }
  })
  expect(narrow.documentWidth).toBeLessThanOrEqual(320)
  expect(narrow.tableWidth).toBeGreaterThan(narrow.tableViewport!)
  expect(narrow.searchHeight).toBeGreaterThanOrEqual(44)
  await expect(page).toHaveScreenshot('users-320.png', { fullPage: true })
  await page.getByRole('button', { name: 'Menu' }).click()
  await expect(page.getByRole('link', { name: 'Models and routing' })).toBeVisible()
  const width = await page.locator('[data-sidebar="sidebar"]').evaluate(
    element => getComputedStyle(element).width)
  expect(width).toBe('288px')
  await expect(page).toHaveScreenshot('users-320-menu.png', { fullPage: true })
  expect(externalRequests).toEqual([])
})

test('BR-04: a timed-out create can be checked and retried with one operation ID', async ({ page }) => {
  await mockAdmin(page)
  const attempts: string[] = []
  await page.route(url => url.pathname === '/api/users' && !url.searchParams.has('page'), async route => {
    const body = route.request().postDataJSON()
    attempts.push(body.operation_id)
    if (attempts.length === 1) {
      await new Promise(resolve => setTimeout(resolve, 11_000))
      await route.fulfill({ json: { error: 'delayed' } }).catch(() => {})
    } else {
      await route.fulfill({ status: 201, json: {
        id: 'created-1', username: body.username, role: body.role,
        sign_in: 'local', managed: false,
      } })
    }
  })
  await page.route('**/api/user-operations/*', route => route.fulfill({ json: { status: 'not_found' } }))
  await page.goto('/app/')
  await page.getByRole('button', { name: 'Create user' }).click()
  await page.getByLabel('Username', { exact: true }).fill('example-user')
  await page.getByLabel('Password', { exact: true }).fill('a-test-password-123456')
  await page.getByRole('dialog').getByRole('button', { name: 'Create user' }).click()
  await expect(page.getByText("It isn't clear whether example-user was created")).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Check' }).click()
  await expect(page.getByLabel('Username', { exact: true })).toHaveValue('example-user')
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('a-test-password-123456')
  await page.getByRole('dialog').getByRole('button', { name: 'Create user' }).click()
  await expect(page.getByRole('status')).toContainText('Created example-user.')
  expect(attempts).toHaveLength(2)
  expect(attempts[0]).toBe(attempts[1])
})

test('BR-05: Change role uses the account API and updates Users', async ({ page }) => {
  const listedUsers = users.map(user => ({ ...user }))
  await mockAdmin(page, listedUsers)
  await page.route('**/api/users/developer-1/role', async route => {
    const body = route.request().postDataJSON()
    expect(body.role).toBe('admin')
    listedUsers[2].role = 'admin'
    await route.fulfill({ json: listedUsers[2] })
  })
  await page.goto('/app/')
  await page.getByRole('row', { name: /developer-example/ }).getByRole('button', { name: 'Change role' }).click()
  await page.getByRole('radio', { name: 'Admin' }).check()
  await page.getByRole('button', { name: 'Save role' }).click()
  await expect(page.getByRole('status')).toContainText("Changed developer-example's role to admin.")
  await expect(page.getByRole('row', { name: /developer-example/ })).toContainText('Admin')
})

test('BR-06: Create user returns keyboard focus to its trigger', async ({ page }) => {
  await mockAdmin(page)
  await page.goto('/app/')
  const trigger = page.getByRole('button', { name: 'Create user' })
  await trigger.click()
  await expect(page.getByRole('dialog', { name: 'Create user' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Create user' })).toBeVisible()
})

test('BR-07: initial search settling does not undo a quick Next click', async ({ page }) => {
  await mockAdmin(page)
  await page.route(url => url.pathname === '/api/users' && url.searchParams.has('page'), route => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page'))
    const listedUsers = pageNumber === 2 ? [{
      id: 'last-user', username: 'last-page-user', role: 'developer', sign_in: 'local', managed: false,
    }] : [{ ...users[0] }, ...Array.from({ length: 24 }, (_, index) => ({
      id: `first-page-${index}`, username: `first-page-${index}`, role: 'developer',
      sign_in: 'local', managed: false,
    }))]
    return route.fulfill({ json: { users: listedUsers, page: pageNumber, page_size: 25,
      total: 26, has_more: pageNumber === 1 } })
  })
  await page.goto('/app/')
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('row', { name: /last-page-user/ })).toBeVisible()
  await page.waitForTimeout(350)
  await expect(page.getByText('Showing 26–26 of 26 users')).toBeVisible()
})
