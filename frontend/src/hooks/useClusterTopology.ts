import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clusterApi } from '../services/api'
import type { ClusterTopology, TopologyCheck } from '../types'

function applyCheck(result: ClusterTopology | TopologyCheck, saved?: ClusterTopology): ClusterTopology {
  if ('nodes' in result) return result
  if (saved && result.last_changed_at === saved.last_changed_at) return { ...saved, ...result }
  throw new Error('Topology check does not match the saved graph')
}

export function useClusterTopology(id: string, visible: boolean) {
  const client = useQueryClient()
  const queryKey = ['clusterTopology', id]

  return useQuery({
    queryKey,
    enabled: !!id && visible,
    queryFn: async ({ signal }) => {
      const previous = client.getQueryData<ClusterTopology>(queryKey)
      const saved = applyCheck(await clusterApi.getTopology(id, signal, previous?.last_changed_at), previous)
      if (!saved.check_due) return saved
      // Show the durable graph while the backend checks Kubernetes for changes.
      client.setQueryData(queryKey, saved)
      return applyCheck(await clusterApi.checkTopology(id, signal, saved.last_changed_at), saved)
    },
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  })
}
