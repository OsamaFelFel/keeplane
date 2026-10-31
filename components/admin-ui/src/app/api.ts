export type Identity = { id: string; username: string; role: 'admin' | 'developer' }
export type User = { id: string; username: string; role: 'admin' | 'developer'; sign_in: 'local' | 'oidc' | 'break-glass'; managed: boolean }
export type UserPage = { users: User[]; page: number; page_size: number; total: number; has_more: boolean }
export type UserOperation = { status: 'created' | 'not_found' | 'pending'; user?: User }

export class ApiError extends Error {
  status: number
  body: Record<string, unknown>
  constructor(status: number, message: string, body: Record<string, unknown> = {}) { super(message); this.status = status; this.body = body }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (new URL(path, window.location.href).origin !== window.location.origin) {
    throw new ApiError(0, 'Keeplane requests must use the same origin.')
  }
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes((init.method || 'GET').toUpperCase())) {
    const options = await api<{ csrf_token: string }>('/api/auth-options', { cache: 'no-store', signal: init.signal })
    if (!options.csrf_token) throw new ApiError(0, 'Could not prepare the request. Reload Keeplane.')
    headers.set('X-CSRFToken', options.csrf_token)
  }
  let response: Response
  try {
    response = await fetch(path, { ...init, credentials: 'same-origin', mode: 'same-origin', headers })
  } catch {
    throw new ApiError(0, 'Keeplane did not answer.')
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, body.error || `Keeplane returned ${response.status}.`, body)
  return body as T
}

export function action<T>(path: string, method: 'POST' | 'PUT', payload: object, signal?: AbortSignal): Promise<T> {
  return api<T>(path, { method, signal, headers: { 'Content-Type': 'application/json', 'X-Keeplane-Action': '1' }, body: JSON.stringify(payload) })
}
