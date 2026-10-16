import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { ModelsPage } from '../../../components/admin-ui/src/features/models/ModelsPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('MO-UI-COUNT: personal models show the server count without a shared-model count', async () => {
  const models = [0, 1, 2].map(count => ({
    id: `personal-${count}`, provider: 'OpenAI', kind: 'cloud', approved: true,
    key_choice: 'personal', developer_key_count: count,
  }))
  const request = vi.fn(async (path: string) => ({
    ok: true, status: 200, json: async () => path === '/api/models'
      ? { models: [...models, { id: 'shared-model', provider: 'OpenAI', kind: 'cloud', approved: true, key_choice: 'shared' }] }
      : { enabled: false, classes: [] },
  }))
  vi.stubGlobal('fetch', request)
  render(<ModelsPage />)
  for (const count of [0, 1, 2]) {
    const row = await screen.findByRole('row', { name: new RegExp(`personal-${count}`) })
    expect(within(row).getByText("Each developer's own")).toBeTruthy()
    expect(within(row).getByText(`${count} ${count === 1 ? 'developer has' : 'developers have'} added a key`)).toBeTruthy()
  }
  expect(within(screen.getByRole('row', { name: /shared-model/ })).queryByText(/added a key/)).toBeNull()
  expect(request).toHaveBeenCalledTimes(2)
})
