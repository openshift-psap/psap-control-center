import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { clusterApi } from '../services/api'
import { useClusterTopology } from './useClusterTopology'

const snapshot = { nodes: [], workers: [], control_plane: [], infra: [], total_nodes: 0, zones: ['east'] }
function visit(id: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(() => useClusterTopology(id), {
    wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  })
}

afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks() })

it('reuses a fresh snapshot on reload and keeps clusters separate', async () => {
  const get = vi.spyOn(clusterApi, 'getTopology').mockResolvedValue(snapshot)
  const first = visit('alpha')
  await waitFor(() => expect(first.result.current.data).toEqual(snapshot))
  first.unmount()
  const again = visit('alpha')
  expect(again.result.current.data).toEqual(snapshot)
  expect(get).toHaveBeenCalledTimes(1)
  again.unmount()
  const other = visit('beta')
  await waitFor(() => expect(other.result.current.data).toEqual(snapshot))
  expect(get).toHaveBeenCalledTimes(2)
})

it('shows the last successful graph while refreshing a stale snapshot and retains it on error', async () => {
  const record = { data: snapshot, updatedAt: Date.now() - 6 * 60_000 }
  sessionStorage.setItem('psap-topology-v1:alpha', JSON.stringify(record))
  vi.spyOn(clusterApi, 'getTopology').mockRejectedValue(new Error('unavailable'))
  const page = visit('alpha')
  expect(page.result.current.data).toEqual(snapshot)
  await waitFor(() => expect(page.result.current.isRefetchError).toBe(true))
  expect(JSON.parse(sessionStorage.getItem('psap-topology-v1:alpha')!)).toEqual(record)
})
