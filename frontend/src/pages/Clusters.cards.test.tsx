import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clusterApi } from '../services/api'
import { clearSession, setSession } from '../stores/authStore'
import type { Cluster } from '../types'
import Clusters from './Clusters'

afterEach(() => { cleanup(); clearSession(); vi.restoreAllMocks() })

function renderClusters(admin = false) {
  if (admin) setSession({ username: 'operator', role: 'admin' })
  const clusters: Cluster[] = ['alpha', 'beta'].map(name => ({
    id: name, name, status: 'healthy', is_active: true, color: '', provider: 'ibm',
    created_at: '', updated_at: '',
  }))
  vi.spyOn(clusterApi, 'list').mockResolvedValue({
    clusters, total: 2,
    latest_costs: { alpha: { billing_month: '2026-10', total_cost: 0, currency: 'USD' } },
  })
  vi.spyOn(clusterApi, 'getRefreshSchedule').mockResolvedValue({
    server_time: '', last_refresh: null, next_refresh: null, in_progress: false, total: 2, completed: 2,
  })
  vi.spyOn(clusterApi, 'getRefreshDisplayPreference').mockResolvedValue({ mode: 'countdown' })
  vi.spyOn(clusterApi, 'getGpuStatus').mockResolvedValue({
    gpu_allocation_mode: 'legacy', dra_available: false, total_gpus: 8, allocated_gpus: 4,
    free_gpus: 4, gpu_types: [], gpu_pods: [
      { name: 'training-a', namespace: 'bench', gpu_count: 2 },
      { name: 'training-b', namespace: 'bench', gpu_count: 1 },
      { name: 'serving', namespace: 'inference', gpu_count: 1 },
    ],
  })
  const history = vi.spyOn(clusterApi, 'getGpuPodHistory').mockResolvedValue({ total: 0, pods: [] })
  const cost = vi.spyOn(clusterApi, 'getCost').mockResolvedValue([
    { billing_month: '2026-10', total_cost: 0, currency: 'USD' },
  ])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><Clusters /></MemoryRouter></QueryClientProvider>)
  return { client, history, cost }
}

it('groups active pods by namespace and only fetches each history while its panel is open', async () => {
  const { client, history, cost } = renderClusters()
  const card = within(await screen.findByRole('article', { name: 'alpha' }))
  const other = within(screen.getByRole('article', { name: 'beta' }))
  const bench = await card.findByRole('button', { name: /bench.*2 pods · 3 GPUs/ })
  expect(card.getByRole('button', { name: /inference.*1 pod · 1 GPU/ })).toBeVisible()
  expect(card.queryByText('training-a')).toBeNull()
  fireEvent.click(bench)
  expect(card.getByText('training-a')).toBeVisible()
  expect(card.getByText('training-b')).toBeVisible()
  expect(other.queryByText('training-a')).toBeNull()
  const past = card.getByRole('button', { name: /Past GPU workloads/ })
  const billing = card.getByRole('button', { name: /Cost history.*Oct 2026.*\$0\.00/ })
  expect(other.getByRole('button', { name: /Cost history.*No billing data/ })).toBeVisible()
  expect(history).not.toHaveBeenCalled()
  expect(cost).not.toHaveBeenCalled()

  fireEvent.click(past)
  await card.findByText('No past GPU workloads recorded.')
  expect(history.mock.calls).toEqual([['alpha']])
  expect(cost).not.toHaveBeenCalled()
  fireEvent.click(billing)
  await card.findByText('$0.00', { selector: 'dd' })
  expect(cost.mock.calls).toEqual([['alpha']])
  await act(async () => { await client.invalidateQueries({ queryKey: ['clusters'] }) })
  expect(past).toHaveAttribute('aria-expanded', 'true')
  expect(billing).toHaveAttribute('aria-expanded', 'true')
  expect(other.getByRole('button', { name: /Past GPU workloads/ })).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(past)
  expect(client.getQueryCache().find({ queryKey: ['gpu-pod-history', 'alpha'] })?.getObserversCount()).toBe(0)
  expect(billing).toHaveAttribute('aria-expanded', 'true')
  fireEvent.click(past)
  expect(history).toHaveBeenCalledTimes(1)
  expect(card.getByRole('link', { name: 'alpha' })).toHaveAttribute('href', '/clusters/alpha')
  expect(card.queryByRole('button', { name: /Actions for/ })).toBeNull()
})

it('shows a retry for a failed request and displays archived pods on recovery', async () => {
  const { history } = renderClusters()
  history.mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce({ total: 1, pods: [
    { name: 'finished', namespace: 'bench', gpu_count: 2, first_seen: '', last_seen: '', finished_at: '2026-09-01T15:00:00' },
  ] })
  const card = within(await screen.findByRole('article', { name: 'alpha' }))
  fireEvent.click(card.getByRole('button', { name: /Past GPU workloads/ }))
  fireEvent.click(await card.findByRole('button', { name: 'Retry' }))
  expect(await card.findByText('bench/finished')).toBeVisible()
  expect(card.getByText(/ago$/, { selector: 'time' })).toHaveAttribute('datetime', '2026-09-01T15:00:00Z')
})

it('keeps removal inside the admin menu and honors a cancelled confirmation', async () => {
  const remove = vi.spyOn(clusterApi, 'delete').mockResolvedValue(undefined)
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  renderClusters(true)
  const card = within(await screen.findByRole('article', { name: 'alpha' }))
  expect(card.queryByRole('menuitem')).toBeNull()
  fireEvent.click(card.getByRole('button', { name: 'Actions for alpha' }))
  fireEvent.click(await card.findByRole('menuitem', { name: 'Remove cluster' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith(expect.stringContaining('"alpha"')))
  expect(remove).not.toHaveBeenCalled()
})
