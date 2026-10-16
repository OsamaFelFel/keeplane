/** Only the existing CLI authorization route can resume after browser sign-in. */
export function signInReturn(search: string, origin: string): string | null {
  const values = new URLSearchParams(search).getAll('return_to')
  if (values.length !== 1) return null
  const value = values[0]
  if (value.length > 4096 || !value.startsWith('/oauth/authorize/?')) return null
  const unsafe = Array.from(value).some(character => character === String.fromCharCode(92)
    || character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127)
  if (unsafe) return null
  try {
    const target = new URL(value, origin)
    return target.origin === origin && target.pathname === '/oauth/authorize/' && !target.hash
      ? target.pathname + target.search : null
  } catch { return null }
}
