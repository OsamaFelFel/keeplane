import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../../../components/admin-ui/web/src/app/api'

afterEach(() => vi.unstubAllGlobals())
const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })

test('a mutation uses the fresh masked token and same-origin credentials', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ csrf_token: 'masked-token' }))
    .mockResolvedValueOnce(response({ saved: true }))
  vi.stubGlobal('fetch', fetch)
  await api('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls[0][0]).toBe('/api/auth-options')
  const sent = fetch.mock.calls[1][1]
  expect(sent.credentials).toBe('same-origin')
  expect(sent.mode).toBe('same-origin')
  expect(sent.headers.get('X-CSRFToken')).toBe('masked-token')
  expect(sent.headers.get('Content-Type')).toBe('application/json')
})

test('failed bootstrap prevents the mutation', async () => {
  const fetch = vi.fn().mockResolvedValue(response({ error: 'Unavailable' }, 503))
  vi.stubGlobal('fetch', fetch)
  await expect(api('/api/users', { method: 'POST', body: '{}' })).rejects.toThrow('Unavailable')
  expect(fetch).toHaveBeenCalledTimes(1)
})

test('a rejected or uncertain mutation is never repeated automatically', async () => {
  for (const result of [response({ error: 'Reload Keeplane' }, 403), new Error('Disconnected')]) {
    const fetch = vi.fn().mockResolvedValueOnce(response({ csrf_token: 'masked-token' }))
    if (result instanceof Error) fetch.mockRejectedValueOnce(result)
    else fetch.mockResolvedValueOnce(result)
    vi.stubGlobal('fetch', fetch)
    await expect(api('/api/users', { method: 'POST', body: '{}' })).rejects.toThrow()
    expect(fetch).toHaveBeenCalledTimes(2)
  }
})

test('no token or request is sent to a different origin', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await expect(api('https://foreign.example/api/users', { method: 'POST' })).rejects.toThrow('same origin')
  expect(fetch).not.toHaveBeenCalled()
})
