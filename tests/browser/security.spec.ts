import { firstAdminPassword } from './credentials'
import { expect, test } from '@playwright/test'

const password = firstAdminPassword

test('BSEC-01: React sign-in and POST sign-out work with live CSRF checks', async ({ page }) => {
  const logoutMethods: string[] = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/sign-out') logoutMethods.push(request.method()) })
  await page.goto('/app/')
  await page.getByLabel('Username').fill('first-admin')
  await page.getByLabel('Password').fill(password())
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Users', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/sign-in$/)
  expect((await page.request.get('/api/identity')).status()).toBe(401)
  expect(logoutMethods).toEqual(['POST'])
})

test('BSEC-02: static sign-in, Editions changes and sign-out work with live CSRF checks', async ({ page }) => {
  const logoutMethods: string[] = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/sign-out') logoutMethods.push(request.method()) })
  await page.goto('/sign-in')
  await page.getByLabel('Username').fill('first-admin')
  await page.getByLabel('Password').fill(password())
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/editions')
  const control = page.getByRole('switch')
  await expect(control).toBeEnabled()
  const original = await control.isChecked()
  try {
    await control.setChecked(!original)
    await expect(control).toBeEnabled()
    expect((await (await page.request.get('/api/edition-note')).json()).enabled).toBe(!original)
  } finally {
    await control.setChecked(original)
    await expect(control).toBeEnabled()
    expect((await (await page.request.get('/api/edition-note')).json()).enabled).toBe(original)
  }
  await page.getByRole('link', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/sign-in$/)
  expect((await page.request.get('/api/identity')).status()).toBe(401)
  expect(logoutMethods).toEqual(['POST'])
})
