import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export function firstAdminPassword() {
  const legacy = '/private/tmp/keeplane-accounts-trial'
  const directory = process.env.KEEPLANE_RUNTIME_DIR ?? (existsSync(legacy)
    ? legacy : fileURLToPath(new URL('../../.keeplane/local', import.meta.url)))
  return readFileSync(join(directory, 'first-admin-password'), 'utf8').trim()
}
