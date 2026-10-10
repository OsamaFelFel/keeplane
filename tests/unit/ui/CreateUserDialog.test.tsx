import { afterEach, expect, test, vi } from 'vitest'
import { createRef } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreateUserDialog } from '../../../components/admin-ui/web/src/features/users/CreateUserDialog'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('UI-01: Developer is the default and invalid local accounts never reach the API', async () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  render(<CreateUserDialog open onOpenChange={() => {}} onCreated={() => {}} returnFocusRef={createRef<HTMLButtonElement>()} />)

  expect(screen.getByRole('radio', { name: 'Developer' }).getAttribute('aria-checked')).toBe('true')
  await user.type(screen.getByLabelText('Username'), 'ab')
  await user.type(screen.getByLabelText('Password'), 'short')
  await user.click(screen.getByRole('button', { name: 'Create user' }))

  expect(await screen.findByText(/Use 3–64 letters/)).toBeTruthy()
  expect(screen.getByText(/Use at least 12 characters/)).toBeTruthy()
  expect(request).not.toHaveBeenCalled()
})
