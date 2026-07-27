import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clusterApi } from '../services/api'
import toast from 'react-hot-toast'

export function useClusterCost(id: string) {
  return useQuery({
    queryKey: ['clusterCost', id],
    queryFn: () => clusterApi.getCost(id),
    enabled: !!id,
    staleTime: 60000,
  })
}

export function useRefreshClusterCost() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: clusterApi.refreshCost,
    onSuccess: (data, id) => {
      queryClient.setQueryData(['clusterCost', id], data)
      if (data.error) {
        toast.error(`Failed to refresh cost: ${data.error}`)
      } else {
        toast.success('Cluster cost refreshed')
      }
    },
    onError: (error: Error) => {
      toast.error(`Failed to refresh cost: ${error.message}`)
    },
  })
}
