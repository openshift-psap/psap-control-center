import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { fournosApi } from '../services/api'
import { clearSession, getViewerCacheKey, setSession } from '../stores/authStore'
import Testing from './Testing'

afterEach(() => { cleanup(); clearSession(); vi.restoreAllMocks() })

function submitClient() {
  setSession({ username: 'viewer', role: 'user' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['clusters', { activeOnly: false }], { clusters: [], total: 0 })
  client.setQueryData(['forge-projects'], [])
  client.setQueryData(['fournos-pipelines'], ['forge-test-only'])
  client.setQueryData(['github-prs'], [])
  client.setQueryData(['github-sync-status'], {})
  client.setQueryData(['fournos-work-item-config'], { enabled: false })
  client.setQueryData(['fournos-run-groups', false], [])
  return client
}

it('keeps project settings when editing Basics and resets them when choosing a different project', async () => {
  const client = submitClient()
  client.setQueryData(['forge-projects'], [{ name: 'first' }, { name: 'second' }])
  for (const project of ['first', 'second']) {
    client.setQueryData(['project-ui-schema', project], {
      found: true, ui_schema: { project, modes: [{
        id: project, label: project === 'second' ? 'Benchmark sweep' : 'Single run',
        kind: project === 'second' ? 'matrix' : 'form', quick_presets: [],
        pipelines: project === 'second' ? [{
          key: 'small', models: [{ key: 'm1', label: 'Small model', overrides: {} }], workloads: ['baseline'],
        }] : [],
        sections: [{ id: 'parameters', fields: [{
          key: 'batch', type: 'text', label: 'Batch size', placeholder: 'Batch size', options: [], maps_to: 'batch',
        }] }],
      }] },
    })
  }
  vi.spyOn(fournosApi, 'getClusterOverview').mockImplementation(async cluster => ({
    cluster, locks: [], current_jobs: [], recurring_jobs: [],
  }))
  render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/testing?tab=submit&submit_type=forge&submit_step=2']}>
      <Testing />
    </MemoryRouter>
  </QueryClientProvider>)

  const selectProject = (name: string) => {
    const option = screen.getByRole<HTMLOptionElement>('option', { name })
    fireEvent.change(option.parentElement!, { target: { value: name } })
  }
  const next = () => fireEvent.click(screen.getByRole('button', { name: 'Next: Project Details' }))
  const back = () => fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  selectProject('first')
  fireEvent.change(screen.getByPlaceholderText('Search or type a cluster name...'), { target: { value: 'one' } })
  next()
  fireEvent.change(await screen.findByPlaceholderText('Batch size'), { target: { value: '32' } })
  back()
  fireEvent.change(screen.getByPlaceholderText('Search or type a cluster name...'), { target: { value: 'two' } })
  next()
  expect(await screen.findByPlaceholderText('Batch size')).toHaveValue('32')
  back()
  selectProject('second')
  next()
  expect(await screen.findByPlaceholderText('Batch size')).toHaveValue('')
  expect(screen.getByRole('heading', { name: 'Benchmark sweep' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'small' }).parentElement).toHaveValue('small')
  expect(screen.getByRole('checkbox', { name: 'Select model Small model' })).toBeChecked()
})

it('waits for fresh activity and opens the warning if an idle cluster becomes busy', async () => {
  const client = submitClient()
  const idle = { cluster: 'demo', current_jobs: [], locks: [], recurring_jobs: [] }
  const busy = { ...idle, as_of: '2026-11-19T10:00:00Z', recurring_jobs: [{
    name: 'quarter-hour', phase: 'Recurring', schedule: '*/15 * * * *',
    next_scheduled_time: '2026-11-19T10:15:00Z',
  }] }
  const key = ['fournos-cluster-overview', 'demo', getViewerCacheKey(), undefined]
  client.setQueryData(key, busy)
  let finishRead!: (data: typeof idle) => void
  const pending = new Promise<typeof idle>(resolve => { finishRead = resolve })
  const read = vi.spyOn(fournosApi, 'getClusterOverview').mockReturnValueOnce(pending).mockResolvedValue(busy)
  vi.spyOn(fournosApi, 'listSlotHolds').mockResolvedValue([])
  render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/testing?tab=submit&submit_type=forge&submit_step=2']}>
      <Testing />
    </MemoryRouter>
  </QueryClientProvider>)
  fireEvent.change(screen.getByPlaceholderText('Search or type a cluster name...'), { target: { value: 'demo' } })
  await waitFor(() => expect(read).toHaveBeenCalled())
  expect(screen.queryByRole('dialog')).toBeNull()
  await act(async () => { finishRead(idle); await pending })
  await screen.findByText('No jobs are queued, running, or scheduled on this accelerator.')
  expect(screen.queryByRole('dialog')).toBeNull()
  await act(async () => { await client.invalidateQueries({ queryKey: key, exact: true }) })
  expect(await screen.findByRole('dialog')).toHaveTextContent('Schedule for demo')
})
