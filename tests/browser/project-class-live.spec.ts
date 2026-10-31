import { randomBytes, randomUUID } from 'node:crypto'
import { expect, request, test, type APIRequestContext } from '@playwright/test'
import { firstAdminPassword } from './credentials'

// Spec 005 ST19 "Set a class" against the running server: no network fixtures.
// It creates one developer and one project, then clears the class, removes the
// developer and restores the data-class mode. The project record itself stays,
// because Keeplane has no project removal; it is left with no class.

const base = process.env.KEEPLANE_BASE_URL ?? 'http://127.0.0.1:3000'

async function signedIn(username: string, password: string) {
  const api = await request.newContext({ baseURL: base, extraHTTPHeaders: { Origin: base } })
  const token = (await (await api.get('/api/auth-options')).json()).csrf_token
  const response = await api.post('/api/session', {
    data: { username, password },
    headers: { 'X-CSRFToken': token, 'X-Keeplane-Action': '1' },
  })
  expect(response.status()).toBe(200)
  return api
}

async function change(api: APIRequestContext, method: 'POST' | 'PUT' | 'DELETE', path: string, data: object) {
  const token = (await (await api.get('/api/auth-options')).json()).csrf_token
  return api.fetch(path, { method, data, headers: { 'X-CSRFToken': token, 'X-Keeplane-Action': '1' } })
}

test('PRJ-UI-05: an admin sets a class on a live project and Projects keeps it', async ({ page }) => {
  const password = firstAdminPassword()
  const admin = await signedIn('first-admin', password)
  const suffix = randomBytes(4).toString('hex')
  const projectId = randomUUID()
  const projectName = 'Class check ' + suffix
  const noGateway = 'Keeplane is running without a reachable model gateway; Set data class lists classes through it. Start the Docker preview.'
  const before = await admin.get('/api/data-classes')
  if (before.status() === 503) await admin.dispose()
  test.skip(before.status() === 503, noGateway)
  expect(before.status()).toBe(200)
  const originalMode = (await before.json()).enabled as boolean
  let developerId: string | null = null
  let classSet = false
  try {
    expect((await change(admin, 'PUT', '/api/data-classes/mode', { enabled: true })).status()).toBe(200)
    const listing = await admin.get('/api/data-classes')
    test.skip(listing.status() === 503, noGateway)
    expect(listing.status()).toBe(200)
    const developerPassword = randomBytes(18).toString('base64url')
    const created = await change(admin, 'POST', '/api/users', {
      username: 'class-check-' + suffix, role: 'developer', password: developerPassword,
    })
    expect(created.status()).toBe(201)
    developerId = (await created.json()).id
    const developer = await signedIn('class-check-' + suffix, developerPassword)
    const session = (await developer.storageState()).cookies.find(cookie => cookie.name === 'keeplane_session')
    expect(session).toBeTruthy()
    const registered = await developer.post('/api/runtime/projects', {
      data: { project_id: projectId, name: projectName },
      headers: { Authorization: 'Bearer ' + session!.value },
    })
    expect(registered.status()).toBe(200)
    await developer.dispose()

    await page.goto('/app/')
    await page.getByLabel('Username').fill('first-admin')
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
    await page.goto('/app/projects')
    await page.getByLabel('Search projects').fill(projectName)
    const row = page.getByRole('row', { name: new RegExp(projectName) })
    await expect(row).toBeVisible()
    await expect(page.getByRole('row')).toHaveCount(2)
    await row.getByRole('button', { name: 'Set class', exact: true }).click()
    await page.getByLabel('Data class', { exact: true }).selectOption('confidential')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    classSet = true
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(row.getByRole('cell', { name: 'Confidential', exact: true })).toBeVisible()

    await page.reload()
    await page.getByLabel('Search projects').fill(projectName)
    await expect(page.getByRole('row', { name: new RegExp(projectName) })
      .getByRole('cell', { name: 'Confidential', exact: true })).toBeVisible()
    const stored = await (await admin.get(`/api/projects/${projectId}/class`)).json()
    expect(stored.data_class).toEqual({ id: 'confidential', name: 'Confidential' })
  } finally {
    const failures: string[] = []
    if (classSet) {
      const cleared = await change(admin, 'PUT', `/api/projects/${projectId}/class`, { class_id: null })
      if (cleared.status() !== 200) failures.push('class clear returned ' + cleared.status())
    }
    if (developerId) {
      const removed = await change(admin, 'DELETE', `/api/users/${developerId}`, {})
      if (removed.status() !== 200) failures.push('developer removal returned ' + removed.status())
    }
    const restored = await change(admin, 'PUT', '/api/data-classes/mode', { enabled: originalMode })
    if (restored.status() !== 200) failures.push('mode restore returned ' + restored.status())
    await admin.dispose()
    expect(failures).toEqual([])
  }
})
