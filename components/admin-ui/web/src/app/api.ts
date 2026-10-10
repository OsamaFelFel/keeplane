export type Identity = { id: string; username: string; role: 'admin' | 'developer' }
export type User = { id: string; username: string; role: 'admin' | 'developer'; sign_in: 'local' | 'oidc' | 'break-glass'; managed: boolean }
export type UserPage = { users: User[]; page: number; page_size: number; total: number; has_more: boolean }
export type UserOperation = { status: 'created' | 'not_found' | 'pending'; user?: User }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { credentials: 'same-origin', ...init, headers: {
      Accept: 'application/json', ...init.headers,
    } })
  } catch {
    throw new ApiError(0, 'Keeplane did not answer.')
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, body.error || `Keeplane returned ${response.status}.`)
  return body as T
}

export function action<T>(path: string, method: 'POST' | 'PUT', payload: object, signal?: AbortSignal): Promise<T> {
  return api<T>(path, { method, signal, headers: { 'Content-Type': 'application/json', 'X-Keeplane-Action': '1' }, body: JSON.stringify(payload) })
}
