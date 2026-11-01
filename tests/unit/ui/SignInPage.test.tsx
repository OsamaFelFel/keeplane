import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SignInPage } from '../../../components/admin-ui/src/features/auth/SignInPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })

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
  expect(screen.getByText('No account? Ask your admin.')).toBeTruthy()
})

test('UI-SIGN-02: when the server reports a connected provider, sign-in also offers single sign-on', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ sso_connected: true, csrf_token: 'masked' })))
  render(<SignInPage onSignedIn={() => {}} />)
  const sso = await screen.findByRole('link', { name: 'Sign in with single sign-on' })
  expect(sso.getAttribute('href')).toBe('/api/oidc/start')
  expect(screen.getByLabelText('Username')).toBeTruthy()
  expect(screen.getByText('No account? Signing in with single sign-on creates one. For a username and password, ask your admin.')).toBeTruthy()
  expect(screen.queryByText('No account? Ask your admin.')).toBeNull()
})

test('UI-SIGN-03: the card shows the Keeplane mark and name above the title "Sign in"', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ sso_connected: false, csrf_token: 'masked' })))
  const { container } = render(<SignInPage onSignedIn={() => {}} />)
  const title = screen.getByRole('heading', { level: 1 })
  expect(title.textContent).toBe('Sign in')
  const brand = screen.getByText('Keeplane')
  const mark = brand.querySelector('img')!
  expect(mark.getAttribute('alt')).toBe('')
  expect(mark.getAttribute('width')).toBe('40')
  // the mark and name come first, then the title
  expect(brand.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(container.textContent).not.toContain('Sign in to Keeplane')
})

test('UI-SIGN-04: a wrong password shows the failure message with a circle-alert icon and a weight-600 line', async () => {
  vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(path === '/api/session'
    ? response({ error: 'Invalid username or password' }, 401)
    : response({ sso_connected: false, csrf_token: 'masked' }))))
  const user = userEvent.setup()
  render(<SignInPage onSignedIn={() => {}} />)
  await user.type(screen.getByLabelText('Username'), 'missing-user')
  await user.type(screen.getByLabelText('Password'), 'a-test-password')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBe('The username or password is wrong.')
  expect(alert.querySelector('svg[data-icon="circle-alert"] circle')).toBeTruthy()
  expect(screen.getByText('The username or password is wrong.').className).toContain('font-semibold')
})
