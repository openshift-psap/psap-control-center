import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clusterApi, type PanelParams } from '../services/api'
import { getPreferenceAccount } from '../stores/authStore'
import type { Cluster, PanelObservation, PanelResponse, RefreshDisplayMode, RefreshDisplayPreference } from '../types'
import toast from 'react-hot-toast'
import { createLogger } from '../utils/logger'

const logger = createLogger('Clusters')

export function useClusters(activeOnly = false, enabled = true) {
  return useQuery({
    queryKey: ['clusters', { activeOnly }],
    queryFn: () => clusterApi.list(activeOnly),
    enabled,
  })
}

const refreshPreferenceKey = () => ['cluster-refresh-display-preference', getPreferenceAccount()] as const

export function useClusterRefreshDisplayPreference(enabled = true) {
  return useQuery<RefreshDisplayPreference>({
    queryKey: refreshPreferenceKey(),
    queryFn: clusterApi.getRefreshDisplayPreference,
    enabled,
    staleTime: Infinity,
    retry: 1,
  })
}

export function useSaveClusterRefreshDisplayPreference() {
  const queryClient = useQueryClient()

  return useMutation<
    RefreshDisplayPreference,
    Error,
    RefreshDisplayMode,
    { key: ReturnType<typeof refreshPreferenceKey>; previous?: RefreshDisplayPreference }
  >({
    mutationFn: clusterApi.saveRefreshDisplayPreference,
    onMutate: async (mode) => {
      const key = refreshPreferenceKey()
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<RefreshDisplayPreference>(key)
      queryClient.setQueryData<RefreshDisplayPreference>(key, { ...previous, mode })
      return { key, previous }
    },
    onError: (error, _mode, context) => {
      if (context) queryClient.setQueryData(context.key, context.previous ?? { mode: 'countdown' })
      toast.error(`Failed to save refresh display preference: ${error.message}`)
    },
    onSuccess: (data, _mode, context) => {
      if (context) queryClient.setQueryData(context.key, data)
    },
  })
}

export function useCluster(id: string) {
  return useQuery({
    queryKey: ['cluster', id],
    queryFn: () => clusterApi.get(id),
    enabled: !!id,
    refetchInterval: 60000,
  })
}

export function useCreateCluster() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: clusterApi.create,
    onSuccess: (data) => {
      logger.info('Cluster created:', data.name)
      queryClient.invalidateQueries({ queryKey: ['clusters'] })
      toast.success('Cluster created successfully')
    },
    onError: (error: Error) => {
      logger.error('Failed to create cluster:', error)
      toast.error(`Failed to create cluster: ${error.message}`)
    },
  })
}

export function useUpdateCluster() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Cluster> }) =>
      clusterApi.update(id, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['clusters'] })
      queryClient.invalidateQueries({ queryKey: ['cluster', data.id] })
      toast.success('Cluster updated successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to update cluster: ${error.message}`)
    },
  })
}

export function useDeleteCluster() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: clusterApi.delete,
    onSuccess: (_data, clusterId) => {
      logger.info('Cluster deleted:', clusterId)
      queryClient.invalidateQueries({ queryKey: ['clusters'] })
      toast.success('Cluster removed from Control Center')
    },
    onError: (error: Error) => {
      logger.error('Failed to delete cluster:', error)
      toast.error(`Failed to remove cluster: ${error.message}`)
    },
  })
}

export function useRefreshClusterStatus() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: clusterApi.refreshStatus,
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['cluster', id] })
      queryClient.invalidateQueries({ queryKey: ['clusters'] })
      toast.success('Cluster status refreshed')
    },
    onError: (error: Error) => {
      toast.error(`Failed to refresh status: ${error.message}`)
    },
  })
}

export function useUploadKubeconfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) =>
      clusterApi.uploadKubeconfig(id, file),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['clusters'] })
      queryClient.invalidateQueries({ queryKey: ['cluster', data.id] })
      for (const section of ['clusterTopology', 'ocpDetails', 'clusterOperators', 'clusterWorkloads']) {
        queryClient.resetQueries({ queryKey: [section, data.id] })
      }
      toast.success('Kubeconfig uploaded successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to upload kubeconfig: ${error.message}`)
    },
  })
}

interface PanelState<T> {
  value: T | null
  observation: PanelObservation
}

function useClusterPanel<T extends object>(
  key: string[], enabled: boolean, fetchPanel: (params: PanelParams) => Promise<PanelResponse<T>>,
) {
  const client = useQueryClient()
  return useQuery({
    queryKey: key, enabled, staleTime: 0, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false,
    queryFn: async ({ signal }) => {
      let state = client.getQueryData<PanelState<T>>(key)
      const read = async (savedOnly: boolean): Promise<PanelState<T>> => {
        const reply = await fetchPanel({ signal, saved_only: savedOnly, known_changed_at: state?.observation.last_changed_at })
        if ('unchanged' in reply) {
          if (!state?.value || state.observation.last_changed_at !== reply.observation.last_changed_at) {
            throw new Error('Cluster observation no longer matches this panel')
          }
          return { value: state.value, observation: reply.observation }
        }
        return { value: 'empty' in reply ? null : reply, observation: reply.observation }
      }
      state = await read(true)
      if (!state.observation.check_due) return state
      client.setQueryData(key, state)
      return read(false)
    },
  })
}

export function useOcpDetails(id: string, enabled: boolean) {
  return useClusterPanel(['ocpDetails', id], !!id && enabled, params => clusterApi.getOcpDetails(id, params))
}

export function useClusterOperators(id: string, enabled: boolean) {
  return useClusterPanel(['clusterOperators', id], !!id && enabled, params => clusterApi.getOperators(id, params))
}

export function useClusterWorkloads(id: string, enabled: boolean) {
  return useClusterPanel(['clusterWorkloads', id], !!id && enabled, params => clusterApi.getWorkloads(id, params))
}
