import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectsPage } from '../../../components/admin-ui/src/features/projects/ProjectsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (body: object, status = 200) => ({ ok: status < 400, status, json: async () => body })
const page = (overrides: object = {}) => ({ projects: [{ id: 'project-one', name: 'Example', initialized: false,
  users: [{ id: 'person-one', username: 'developer-one' }], data_class: { id: 'confidential', name: 'Confidential' } }],
  classes_enabled: true, page: 1, page_size: 25, total: 1, has_more: false, ...overrides })

test('projects show first-use accounts and current class without claiming onboarding', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(page())))
  render(<ProjectsPage />)
  expect(await screen.findByText('Example')).toBeTruthy()
  expect(screen.getByText('developer-one')).toBeTruthy()
  expect(screen.getByText('Confidential')).toBeTruthy()
  expect(screen.getByText('Not yet')).toBeTruthy()
  expect(screen.getByRole('region', { name: 'Projects table' }).getAttribute('tabindex')).toBe('0')
  expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(true)
})

test('class fields are hidden while classes are off', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(page({ classes_enabled: false }))))
  render(<ProjectsPage />)
  await screen.findByText('Example')
  expect(screen.queryByRole('columnheader', { name: 'Data class' })).toBeNull()
  expect(screen.queryByText('Confidential')).toBeNull()
})

test('search resets paging and next sends the requested bounded page', async () => {
  const request = vi.fn().mockResolvedValue(response(page({ total: 30, has_more: true })))
  vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  render(<ProjectsPage />)
  await screen.findByText('Example')
  await user.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(new URL(request.mock.calls.at(-1)![0], 'http://localhost').searchParams.get('page')).toBe('2'))
  await user.type(screen.getByLabelText('Search projects'), 'Example')
  await waitFor(() => {
    const params = new URL(request.mock.calls.at(-1)![0], 'http://localhost').searchParams
    expect(params.get('page')).toBe('1'); expect(params.get('search')).toBe('Example')
    expect(params.get('page_size')).toBe('25')
  })
})

test('an unavailable server shows an error and clears stale project rows', async () => {
  const request = vi.fn().mockResolvedValueOnce(response(page()))
    .mockResolvedValue(response({ error: 'Storage unavailable' }, 503))
  vi.stubGlobal('fetch', request)
  const user = userEvent.setup()
  render(<ProjectsPage />)
  await screen.findByText('Example')
  await user.type(screen.getByLabelText('Search projects'), 'Other')
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('Example')).toBeNull()
})

test('an empty first-use registry has a clear empty state', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(page({ projects: [], total: 0 }))))
  render(<ProjectsPage />)
  expect(await screen.findByText('No projects found')).toBeTruthy()
})
