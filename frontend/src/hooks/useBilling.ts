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
    mutationFn: (file: File) => billingApi.upload(file),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['billing', 'reports'] })
      toast.success(`Billing report uploaded: ${data.billing_month} (${data.cluster_count} clusters)`)
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
