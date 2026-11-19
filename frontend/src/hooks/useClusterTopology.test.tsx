import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { clusterApi } from '../services/api'
import { useClusterTopology } from './useClusterTopology'

const snapshot = {
  nodes: [], workers: [], control_plane: [], infra: [], total_nodes: 0, zones: [],
  last_changed_at: '2026-11-17T10:00:00Z', last_checked_at: '2026-11-19T10:00:00Z',
  check_due: false, last_check_failed: false,
}
function visit(visible = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(({ open }) => useClusterTopology('alpha', open), {
    initialProps: { open: visible },
    wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  })
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

it('reads on navigation, reuses a recent server check, and never polls while open', async () => {
  const get = vi.spyOn(clusterApi, 'getTopology').mockResolvedValue(snapshot)
  const check = vi.spyOn(clusterApi, 'checkTopology')
  const page = visit(false)
  expect(get).not.toHaveBeenCalled()
  page.rerender({ open: true })
  await waitFor(() => expect(page.result.current.data).toEqual(snapshot))
  vi.useFakeTimers()
  await act(() => vi.advanceTimersByTimeAsync(10 * 60_000))
  expect(get).toHaveBeenCalledTimes(1)
  vi.useRealTimers()
  page.rerender({ open: false })
  page.rerender({ open: true })
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
  expect(check).not.toHaveBeenCalled()
})

it('shows the saved graph during a due check and preserves it on a network failure', async () => {
  const saved = { ...snapshot, check_due: true }
  vi.spyOn(clusterApi, 'getTopology').mockResolvedValue(saved)
  let fail!: (error: Error) => void
  vi.spyOn(clusterApi, 'checkTopology').mockImplementation(() => new Promise((_, reject) => { fail = reject }))
  const page = visit()
  await waitFor(() => expect(page.result.current.data).toEqual(saved))
  expect(page.result.current.isFetching).toBe(true)
  act(() => fail(new Error('offline')))
  await waitFor(() => expect(page.result.current.isError).toBe(true))
  expect(page.result.current.data).toEqual(saved)
})

it('displays the backend timestamps after an explicit refresh', async () => {
  const get = vi.spyOn(clusterApi, 'getTopology').mockResolvedValue(snapshot)
  const updated = { ...snapshot, last_checked_at: '2026-11-19T12:00:00Z' }
  const check = vi.spyOn(clusterApi, 'checkTopology').mockResolvedValue({
    last_checked_at: updated.last_checked_at, last_changed_at: snapshot.last_changed_at,
    check_due: false, last_check_failed: false,
  })
  const page = visit()
  await waitFor(() => expect(page.result.current.data).toEqual(snapshot))
  get.mockResolvedValue({ ...snapshot, check_due: true })
  await act(async () => { await page.result.current.refetch() })
  await waitFor(() => expect(page.result.current.data).toEqual(updated))
  expect(check).toHaveBeenCalledTimes(1)
})
