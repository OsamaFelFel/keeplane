import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataClassesPage } from '../../../components/admin-ui/src/features/data-classes/DataClassesPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const classes = [
  { id: 'public', name: 'Public', approved_model_ids: [], project_count: 0 },
  { id: 'internal', name: 'Internal', approved_model_ids: [], project_count: 0 },
  { id: 'confidential', name: 'Confidential', approved_model_ids: [], project_count: 0 },
]

function server(detection: { enabled: boolean; class_id: string | null; available?: boolean }) {
  const sent: object[] = []
  const request = vi.fn(async (path: string, init: RequestInit = {}) => {
    if (path === '/api/auth-options') return response({ csrf_token: 'token' })
    if (path === '/api/data-classes/detection') {
      const body = JSON.parse(String(init.body))
      sent.push(body); Object.assign(detection, body)
      return response({ enabled: detection.enabled, class_id: detection.class_id })
    }
    return response({ enabled: true, classes, detection: { ...detection } })
  })
  vi.stubGlobal('fetch', request)
  return sent
}

// DC-UI-05 (ST20): detection is off by default and handles requests as Confidential.
test('detection starts off with Confidential chosen', async () => {
  server({ enabled: false, class_id: 'confidential', available: true })
  render(<DataClassesPage />)
  const toggle = await screen.findByRole('switch', { name: 'Detect personal data in requests' })
  expect((toggle as HTMLInputElement).checked).toBe(false)
  expect(screen.getByRole('heading', { name: 'Personal data in requests' })).toBeTruthy()
  expect((screen.getByLabelText('Handle it as') as HTMLSelectElement).value).toBe('confidential')
})

// DC-UI-06: turning detection on and choosing another class send the setting.
test('an admin turns detection on and picks another class', async () => {
  const sent = server({ enabled: false, class_id: 'confidential', available: true })
  const user = userEvent.setup()
  render(<DataClassesPage />)
  await user.click(await screen.findByRole('switch', { name: 'Detect personal data in requests' }))
  await waitFor(() => expect(sent).toEqual([{ enabled: true, class_id: 'confidential' }]))
  expect(await screen.findByText('Personal-data detection turned on.')).toBeTruthy()
  await user.selectOptions(screen.getByLabelText('Handle it as'), 'internal')
  await waitFor(() => expect(sent.at(-1)).toEqual({ enabled: true, class_id: 'internal' }))
  expect(await screen.findByText('Detected requests are handled as Internal.')).toBeTruthy()
})

// DC-UI-07: the detection section is hidden while data classes are off.
test('detection is hidden while data classes are off', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ enabled: false, classes: [] })))
  render(<DataClassesPage />)
  await screen.findByRole('switch', { name: 'Use data classes' })
  expect(screen.queryByRole('switch', { name: 'Detect personal data in requests' })).toBeNull()
})

// DC-UI-08: without the detector the switch can't be turned on and the page says why.
test('detection that is not installed cannot be turned on', async () => {
  const sent = server({ enabled: false, class_id: 'confidential', available: false })
  render(<DataClassesPage />)
  const toggle = await screen.findByRole('switch', { name: 'Detect personal data in requests' }) as HTMLInputElement
  expect(toggle.disabled).toBe(true)
  expect(screen.getByText("Personal-data detection isn't installed. Install it, then turn this on.")).toBeTruthy()
  expect(sent).toEqual([])
})

// DC-UI-09: if it disappears after being on, the admin can still turn it off.
test('detection that is on stays switchable off when the detector is gone', async () => {
  const sent = server({ enabled: true, class_id: 'confidential', available: false })
  const user = userEvent.setup()
  render(<DataClassesPage />)
  const toggle = await screen.findByRole('switch', { name: 'Detect personal data in requests' }) as HTMLInputElement
  expect(toggle.disabled).toBe(false)
  await user.click(toggle)
  await waitFor(() => expect(sent).toEqual([{ enabled: false, class_id: 'confidential' }]))
})

// DC-UI-10 (ST21): the page says its changes and held requests are recorded.
test('the page says what Audit records while classes are on', async () => {
  const line = 'With the audit add-on on, every change here and every request detection holds back is recorded.'
  server({ enabled: false, class_id: 'confidential', available: true })
  render(<DataClassesPage />)
  expect(await screen.findByText(line)).toBeTruthy()
  cleanup()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ enabled: false, classes: [] })))
  render(<DataClassesPage />)
  await screen.findByRole('switch', { name: 'Use data classes' })
  expect(screen.queryByText(line)).toBeNull()
})
