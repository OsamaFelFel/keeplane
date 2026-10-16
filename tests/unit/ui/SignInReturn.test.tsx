import { expect, test } from 'vitest'
import { signInReturn } from '../../../components/admin-ui/src/features/auth/signInReturn'

const origin = 'https://keeplane.example'
const search = (target: string) => '?' + new URLSearchParams({ return_to: target })

test('sign-in resumes only the same-origin CLI authorization route', () => {
  const target = '/oauth/authorize/?client_id=keeplane-cli&state=synthetic'
  expect(signInReturn(search(target), origin)).toBe(target)
  expect(signInReturn('', origin)).toBeNull()
  for (const unsafe of ['https://other.example/', '//other.example/', '/app/', '/oauth/token/',
    '/oauth/authorize/?state=a#fragment', '/oauth/authorize/?state=bad\nline',
    '/oauth/authorize/?state=bad' + String.fromCharCode(92), '/oauth/authorize/?x=' + 'a'.repeat(4096)]) {
    expect(signInReturn(search(unsafe), origin)).toBeNull()
  }
  expect(signInReturn(search('/oauth/authorize/?a=1') + '&return_to=%2Fapp%2F', origin)).toBeNull()
})
