import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clusterApi } from '../services/api'
import Clusters from './Clusters'
import Dashboard from './Dashboard'

afterEach(() => vi.restoreAllMocks())

it.each([['Clusters', Clusters], ['Overview', Dashboard]] as const)(
  '%s shows the empty state only after a successful list request',
  async (_pageName, Page) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(['cluster-refresh-schedule'], {})
    client.setQueryData(['reservations', undefined], { reservations: [], total: 0 })
    client.setQueryData(['hearthClusters'], { available: true, clusters: [], total: 0 })
    client.setQueryData(['fournos-live-job-summary'], { total: 0, by_status: {}, by_cluster: {} })
    const list = vi.spyOn(clusterApi, 'list')
      .mockRejectedValueOnce(new Error('Request timed out'))
      .mockResolvedValueOnce({ clusters: [], total: 0 })

    render(<QueryClientProvider client={client}><MemoryRouter><Page /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load the cluster list')
    expect(screen.queryByText('No clusters configured')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('No clusters configured')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(list).toHaveBeenCalledTimes(2)
  },
)
