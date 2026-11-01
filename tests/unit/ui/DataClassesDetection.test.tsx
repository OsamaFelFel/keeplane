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

function server(detection: { enabled: boolean; class_id: string | null }) {
  const sent: object[] = []
  const request = vi.fn(async (path: string, init: RequestInit = {}) => {
    if (path === '/api/auth-options') return response({ csrf_token: 'token' })
    if (path === '/api/data-classes/detection') {
      const body = JSON.parse(String(init.body))
      sent.push(body); Object.assign(detection, body)
      return response(detection)
    }
    return response({ enabled: true, classes, detection: { ...detection } })
  })
  vi.stubGlobal('fetch', request)
  return sent
}

// DC-UI-05 (ST20): detection is off by default and handles requests as Confidential.
test('detection starts off with Confidential chosen', async () => {
  server({ enabled: false, class_id: 'confidential' })
  render(<DataClassesPage />)
  const toggle = await screen.findByRole('switch', { name: 'Detect personal data in requests' })
  expect((toggle as HTMLInputElement).checked).toBe(false)
  expect(screen.getByRole('heading', { name: 'Personal data in requests' })).toBeTruthy()
  expect((screen.getByLabelText('Handle it as') as HTMLSelectElement).value).toBe('confidential')
})

// DC-UI-06: turning detection on and choosing another class send the setting.
test('an admin turns detection on and picks another class', async () => {
  const sent = server({ enabled: false, class_id: 'confidential' })
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
