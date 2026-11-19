import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { clusterApi } from '../services/api'
import type { ClusterTopology } from '../types'

const FRESH_FOR = 5 * 60_000
const KEEP_FOR = 60 * 60_000
const storageKey = (id: string) => `psap-topology-v1:${id}`

function isTopology(data: Partial<ClusterTopology> | null | undefined): data is ClusterTopology {
  return !!data && Array.isArray(data.nodes) && Array.isArray(data.control_plane) &&
    Array.isArray(data.workers) && Array.isArray(data.infra) && Array.isArray(data.zones)
}

function readTopology(id: string): { data: ClusterTopology; updatedAt: number } | undefined {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey(id)) || 'null')
    const age = Date.now() - saved?.updatedAt
    if (age >= 0 && age < KEEP_FOR && isTopology(saved?.data)) return saved
    sessionStorage.removeItem(storageKey(id))
  } catch {
    // A live read also works when browser storage is unavailable.
  }
}

export function useClusterTopology(id: string) {
  const saved = useMemo(() => readTopology(id), [id])
  return useQuery({
    queryKey: ['clusterTopology', id],
    queryFn: async ({ signal }) => {
      const data = await clusterApi.getTopology(id, signal)
      if (!isTopology(data)) throw new Error('Incomplete cluster topology')
      try {
        sessionStorage.setItem(storageKey(id), JSON.stringify({ data, updatedAt: Date.now() }))
      } catch {
        // React Query still retains the latest successful response in memory.
      }
      return data
    },
    initialData: saved?.data,
    initialDataUpdatedAt: saved?.updatedAt,
    enabled: !!id,
    staleTime: FRESH_FOR,
    gcTime: KEEP_FOR,
    refetchInterval: FRESH_FOR,
  })
}
