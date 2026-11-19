import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { clusterApi } from '../services/api'
import { clearSession, isAuthenticated, setSession } from '../stores/authStore'
import type { RefreshDisplayPreference } from '../types'
import { useClusterRefreshDisplayPreference, useSaveClusterRefreshDisplayPreference } from './useClusters'

afterEach(() => { clearSession(); vi.restoreAllMocks() })

it('keeps the refresh selector and a pending save with the account that made the change', async () => {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  vi.spyOn(clusterApi, 'getRefreshDisplayPreference').mockResolvedValue({ mode: 'countdown' })
  let finishSave!: (value: RefreshDisplayPreference) => void
  const save = vi.spyOn(clusterApi, 'saveRefreshDisplayPreference').mockImplementation(() =>
    new Promise(resolve => { finishSave = resolve }),
  )
  setSession({ username: 'first', role: 'user' })
  const hook = renderHook(() => ({
    preference: useClusterRefreshDisplayPreference(isAuthenticated()),
    change: useSaveClusterRefreshDisplayPreference(),
  }), { wrapper })
  await waitFor(() => expect(hook.result.current.preference.data?.mode).toBe('countdown'))
  act(() => hook.result.current.change.mutate('last_update'))
  await waitFor(() => expect(save).toHaveBeenCalledOnce())
  expect(hook.result.current.preference.data?.mode).toBe('last_update')
  clearSession()
  hook.rerender()
  expect(hook.result.current.preference.data).toBeUndefined()
  setSession({ username: 'second', role: 'user' })
  hook.rerender()
  await waitFor(() => expect(hook.result.current.preference.data?.mode).toBe('countdown'))
  await act(async () => finishSave({ mode: 'last_update' }))
  expect(hook.result.current.preference.data?.mode).toBe('countdown')
  setSession({ username: 'first', role: 'user' })
  hook.rerender()
  expect(hook.result.current.preference.data?.mode).toBe('last_update')
})
