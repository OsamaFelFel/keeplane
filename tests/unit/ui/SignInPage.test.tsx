import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { SignInPage } from '../../../components/admin-ui/src/features/auth/SignInPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object) => ({ ok: true, status: 200, json: async () => body })

test('UI-SIGN-01: with no provider connected, sign-in offers only username and password and no way to sign up', async () => {
  const request = vi.fn().mockResolvedValue(response({ sso_connected: false, csrf_token: 'masked' }))
  vi.stubGlobal('fetch', request)
  render(<SignInPage onSignedIn={() => {}} />)
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/auth-options', expect.anything()))
  expect(screen.getByLabelText('Username')).toBeTruthy()
  expect(screen.getByLabelText('Password')).toBeTruthy()
  expect(screen.getAllByRole('button').map(button => button.textContent)).toEqual(['Sign in'])
  expect(screen.queryAllByRole('link')).toEqual([])
  expect(screen.queryByText(/single sign-on/i)).toBeNull()
  expect(screen.queryByText(/sign up|create an account|register/i)).toBeNull()
})

test('UI-SIGN-02: when the server reports a connected provider, sign-in also offers single sign-on', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ sso_connected: true, csrf_token: 'masked' })))
  render(<SignInPage onSignedIn={() => {}} />)
  expect(await screen.findByRole('link', { name: 'Sign in with single sign-on' })).toBeTruthy()
  expect(screen.getByLabelText('Username')).toBeTruthy()
})
