import { chromium, expect } from '@playwright/test'

// Invoked only by the optional isolated Django/CLI test, with synthetic accounts.
let browser
try {
  browser = await chromium.launch()
  const context = await browser.newContext({ serviceWorkers: 'block' })
  const page = await context.newPage()
  const writes = []
  await context.route('**/*', route => {
    const url = new URL(route.request().url())
    return url.protocol === 'http:' && url.hostname === '127.0.0.1'
      ? route.continue() : route.abort()
  })
  page.on('request', request => {
    if (request.method() === 'POST') writes.push(new URL(request.url()).pathname)
  })
  await page.goto(process.argv[2])
  await expect(page.getByRole('heading', { name: 'Sign in to Keeplane', exact: true })).toBeVisible()
  await page.getByLabel('Username', { exact: true }).fill('browser-developer')
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Allow CLI access?', exact: true })).toBeVisible()
  await expect(page.getByText('browser-developer', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('Return to the Keeplane CLI.', { exact: true })).toBeVisible()
  expect(writes).toEqual(['/api/session', '/oauth/authorize/'])
  console.log(JSON.stringify({ sign_in: true, consent: true, callback: true }))
} catch {
  // Never print callback URLs, page content or browser errors containing tokens.
  console.error('The rendered CLI sign-in journey failed.')
  process.exitCode = 1
} finally {
  await browser?.close()
}
