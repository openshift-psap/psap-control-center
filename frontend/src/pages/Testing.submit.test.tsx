import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { fournosApi } from '../services/api'
import { clearSession, setSession } from '../stores/authStore'
import Testing from './Testing'

afterEach(() => { cleanup(); clearSession(); vi.restoreAllMocks() })

it('keeps project settings when editing Basics and resets them when choosing a different project', async () => {
  setSession({ username: 'viewer', role: 'user' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['clusters', { activeOnly: false }], { clusters: [], total: 0 })
  client.setQueryData(['forge-projects'], [{ name: 'first' }, { name: 'second' }])
  client.setQueryData(['fournos-pipelines'], ['forge-test-only'])
  client.setQueryData(['github-prs'], [])
  client.setQueryData(['github-sync-status'], {})
  client.setQueryData(['fournos-work-item-config'], { enabled: false })
  client.setQueryData(['fournos-run-groups', false], [])
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
