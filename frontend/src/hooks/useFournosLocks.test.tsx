import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { fournosApi } from '../services/api'
import { clearSession, isAuthenticated, setSession } from '../stores/authStore'
import { useClusterLocks, useRecurringJobChildren, useRecurringJobs } from './useFournos'

afterEach(() => { clearSession(); vi.restoreAllMocks() })

it('drops signed-in lock holders from schedule and lock views immediately on sign-out', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const rows = async () => [{ owner: isAuthenticated() ? 'Holder' : '' }]
  vi.spyOn(fournosApi, 'listRecurringJobs').mockImplementation(rows)
  vi.spyOn(fournosApi, 'listClusterLocks').mockImplementation(rows)
  vi.spyOn(fournosApi, 'getRecurringJobChildren').mockImplementation(rows)
  setSession({ username: 'viewer', role: 'user' })
  const hook = renderHook(() => [
    useRecurringJobs('demo').data?.[0]?.owner,
    useClusterLocks('demo').data?.[0]?.owner,
    useRecurringJobChildren('monthly').data?.[0]?.owner,
  ], { wrapper })
  await waitFor(() => expect(hook.result.current).toEqual(['Holder', 'Holder', 'Holder']))
  clearSession()
  hook.rerender()
  expect(hook.result.current).toEqual([undefined, undefined, undefined])
  await waitFor(() => expect(hook.result.current).toEqual(['', '', '']))
})
