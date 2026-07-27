import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { billingApi } from '../services/api'
import toast from 'react-hot-toast'

export function useBillingReports() {
  return useQuery({
    queryKey: ['billing', 'reports'],
    queryFn: billingApi.listReports,
    retry: false,
  })
}

export function useUploadBillingCsv() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ file, autoRefresh }: { file: File; autoRefresh: boolean }) =>
      billingApi.upload(file, autoRefresh),
    onSuccess: (data, { autoRefresh }) => {
      queryClient.invalidateQueries({ queryKey: ['billing', 'reports'] })
      if (autoRefresh) {
        queryClient.invalidateQueries({ queryKey: ['clusterCost'] })
        toast.success(`Billing report uploaded: ${data.billing_month} — refreshing cluster costs...`)
      } else {
        toast.success(`Billing report uploaded: ${data.billing_month} (${data.cluster_count} clusters)`)
      }
    },
    onError: (error: Error) => {
      toast.error(`Upload failed: ${error.message}`)
    },
  })
}

export function useDeleteBillingReport() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (billingMonth: string) => billingApi.deleteReport(billingMonth),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['billing', 'reports'] })
      toast.success('Billing report deleted')
    },
    onError: (error: Error) => {
      toast.error(`Delete failed: ${error.message}`)
    },
  })
}

export function useCostRefreshStatus(enabled: boolean) {
  const queryClient = useQueryClient()

  return useQuery({
    queryKey: ['billing', 'cost-refresh-status'],
    queryFn: billingApi.getCostRefreshStatus,
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data
      if (data?.in_progress) return 2000
      if (data && !data.in_progress && data.completed > 0) {
        queryClient.invalidateQueries({ queryKey: ['clusterCost'] })
      }
      return false
    },
  })
}
