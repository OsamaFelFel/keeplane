import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChangeRoleDialog } from '../../../components/admin-ui/src/features/users/ChangeRoleDialog'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const developer = { id: 'developer-1', username: 'developer-example', role: 'developer' as const, sign_in: 'local', managed: false }

function fixture(write: () => Promise<object>) {
  const request = vi.fn((path: string) => {
    if (path === '/api/auth-options') return Promise.resolve(response({ csrf_token: 'masked' }))
    return write()
  })
  vi.stubGlobal('fetch', request)
  return request
}

async function saveAdmin(onOpenChange = vi.fn(), onChanged = vi.fn()) {
  const user = userEvent.setup()
  render(<ChangeRoleDialog user={developer} onOpenChange={onOpenChange} onChanged={onChanged} />)
  await user.click(screen.getByRole('radio', { name: 'Admin' }))
  await user.click(screen.getByRole('button', { name: 'Save role' }))
  return { onOpenChange, onChanged }
}

// The design system's failure message: a circle-alert icon (not the old triangle) and a weight-600 first line.
async function expectFailureMessage(title: string, second: string) {
  const heading = await screen.findByText(title)
  expect(heading.className).toContain('font-semibold')
  const alert = screen.getByRole('alert')
  expect(alert.textContent).toBe(title + second)
  const icons = alert.querySelectorAll('svg')
  expect(icons).toHaveLength(1)
  expect(icons[0].dataset.icon).toBe('circle-alert')
  expect(icons[0].querySelector('circle')).toBeTruthy()
  expect(icons[0].getAttribute('class')).toContain('size-5')
}

test("UI-ROLE-01: a refused change says \"[Username]'s role wasn't changed\" with the reason and keeps the dialog open", async () => {
  const request = fixture(async () => response({ error: 'Account not found' }, 404))
  const { onOpenChange, onChanged } = await saveAdmin()
  await expectFailureMessage("developer-example's role wasn't changed",
    'Account not found. Nothing was saved. Check the details and try again.')
  expect(onOpenChange).not.toHaveBeenCalled()
  expect(onChanged).not.toHaveBeenCalled()
  expect(screen.getByRole('radio', { name: 'Admin' }).getAttribute('aria-checked')).toBe('true')
  expect(request.mock.calls.filter(([path]) => path === '/api/users/developer-1/role')).toHaveLength(1)
})

test.each([
  ['a server error', async () => response({ error: 'Internal error' }, 503), "Keeplane couldn't confirm the result."],
  ['no answer', async () => { throw new TypeError('Failed to fetch') }, "Keeplane didn't answer in time."],
])('UI-ROLE-02: after %s the dialog says it isn\'t clear whether the role was changed, not that nothing was saved', async (_, write, reason) => {
  fixture(write)
  await saveAdmin()
  await expectFailureMessage("It isn't clear whether developer-example's role was changed",
    `${reason} Save the role again to make sure; it won't be changed twice.`)
  expect(screen.getByRole('button', { name: 'Save role' })).toHaveProperty('disabled', false)
})
