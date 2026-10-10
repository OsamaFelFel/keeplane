import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

test('DC-UI-01: the optional mode reveals starter classes and hides them again', async ({ page }) => {
  let enabled = false
  const classes = [
    { id: 'public', name: 'Public', approved_model_ids: [], project_count: 0 },
    { id: 'internal', name: 'Internal', approved_model_ids: [], project_count: 0 },
    { id: 'confidential', name: 'Confidential', approved_model_ids: [], project_count: 0 },
  ]
  await page.route('**/api/identity', route => route.fulfill({ json: {
    id: 'admin', username: 'first-admin', role: 'admin',
  } }))
  await page.route('**/api/data-classes', route => route.fulfill({ json: {
    enabled, classes: enabled ? classes : [],
  } }))
  await page.route('**/api/data-classes/mode', async route => {
    enabled = route.request().postDataJSON().enabled
    await route.fulfill({ json: { enabled } })
  })
  await page.goto('/app/data-classes')
  await expect(page.getByRole('heading', { name: 'Data classes' })).toBeVisible()
  await expect(page.getByRole('switch', { name: 'Use data classes' })).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Add class' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Data classes table' })).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready)
  await expect(page).toHaveScreenshot('data-classes-off-1280.png', { fullPage: true })
  await page.getByRole('switch', { name: 'Use data classes' }).check()
  await expect(page.getByRole('row', { name: /Public/ })).toBeVisible()
  await expect(page.getByRole('row', { name: /Internal/ })).toBeVisible()
  await expect(page.getByRole('row', { name: /Confidential/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add class' })).toBeVisible()
  await expect(page).toHaveScreenshot('data-classes-on-1280.png', { fullPage: true })
  await page.setViewportSize({ width: 320, height: 800 })
  const narrow = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(narrow).toBeLessThanOrEqual(320)
  await page.getByRole('switch', { name: 'Use data classes' }).uncheck()
  await expect(page.getByRole('region', { name: 'Data classes table' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add class' })).toHaveCount(0)
})

test('DC-UI-02: an admin can add a class without silently approving a model', async ({ page }) => {
  const classes = [
    { id: 'public', name: 'Public', approved_model_ids: [], project_count: 0 },
  ]
  await page.route('**/api/identity', route => route.fulfill({ json: {
    id: 'admin', username: 'first-admin', role: 'admin',
  } }))
  await page.route('**/api/data-classes', route => route.fulfill({ json: {
    enabled: true, classes,
  } }))
  await page.route('**/api/models', route => route.fulfill({ json: {
    models: [{ id: 'set-up-model', approved: true }],
  } }))
  await page.route('**/api/data-classes', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { enabled: true, classes } })
    const body = route.request().postDataJSON()
    expect(body).toEqual({ name: 'Restricted', approved_model_ids: [] })
    classes.push({ id: 'restricted', name: body.name, approved_model_ids: [], project_count: 0 })
    await route.fulfill({ status: 201, json: classes[1] })
  })
  await page.goto('/app/data-classes')
  await page.getByRole('button', { name: 'Add class' }).click()
  await page.getByLabel('Name').fill('Restricted')
  await expect(page.getByRole('checkbox', { name: 'set-up-model' })).not.toBeChecked()
  await page.getByRole('dialog').getByRole('button', { name: 'Add class' }).click()
  await expect(page.getByRole('row', { name: /Restricted/ })).toContainText('None')
})

test('DC-UI-03: Models hides every class field while the mode is off', async ({ page }) => {
  const password = readFileSync('/private/tmp/keeplane-accounts-trial/first-admin-password', 'utf8').trim()
  await page.goto('/app/')
  await page.getByLabel('Username').fill('first-admin')
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
  await page.route('**/api/data-classes', route => route.fulfill({ json: { enabled: false, classes: [] } }))
  await page.route('**/api/models', route => route.fulfill({ json: { models: [{
    id: 'outside-model', provider: 'Test fixture', kind: 'fixture', approved: false,
    approved_classes: [], owned_by_keeplane: false,
  }] } }))
  await page.goto('/')
  await expect(page.getByRole('row', { name: /outside-model/ })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Approved for' })).toBeHidden()
  await page.getByRole('button', { name: 'Add model' }).click()
  await expect(page.locator('#add-class-choices')).toBeHidden()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('button', { name: 'Set up' }).click()
  await expect(page.locator('#setup-class-choices')).toBeHidden()
})
