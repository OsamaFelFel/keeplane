import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { AuditPage } from '../../../components/admin-ui/src/features/audit/AuditPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object) => ({ ok: true, status: 200, json: async () => body })
const records = { records: [], total: 0, page: 1, page_size: 25, has_more: false }

function stubAudit() {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => String(url).startsWith('/api/audit/options')
    ? response({ options: { settings: false, held_requests: false, model_answers: false } })
    : response(records)))
}

// The switch's words as Audit.dc.html shows them.
const designed = [
  ['Changes to models, routing and data classes', 'Who changed what, and when.'],
  ['Requests held back by personal-data detection',
    'A reference to the request, whose it was, its project, the class it was handled as and why. The prompt is never stored.'],
  ['Which model each request was sent to', 'The model, the developer and the project, when a request is sent. No prompt or answer text.'],
  ['Sign-ins with the break-glass admin', 'When someone signed in with it.'],
]

test('UI-AUD-01: each record switch reads as designed', async () => {
  stubAudit()
  render(<AuditPage />)
  for (const [label, description] of designed) {
    const control = await screen.findByRole('switch', { name: label })
    expect(control.closest('div')?.parentElement?.querySelector('p')?.textContent).toBe(description)
  }
  expect(screen.getAllByRole('switch')).toHaveLength(designed.length)
})

test('UI-AUD-02: the model switch says a request was sent, never that a model answered', async () => {
  stubAudit()
  const { container } = render(<AuditPage />)
  await screen.findByRole('switch', { name: 'Which model each request was sent to' })
  const words = container.querySelector('[aria-labelledby="audit-options-title"]')?.textContent ?? ''
  expect(words).not.toMatch(/answered|each task/i)
})
