import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { authApi } from '../services/api'
import { getPreferenceAccount } from '../stores/authStore'
import type { SidebarOption, SidebarPreferences } from '../types'

const guestKey = 'psap-sidebar-guest'

function readGuestChoices(): SidebarPreferences {
  try {
    return JSON.parse(localStorage.getItem(guestKey) || '{}') ?? {}
  } catch {
    return {}
  }
}

export function useSidebarPreferences() {
  const account = getPreferenceAccount()
  const key = ['sidebar-preferences', account]
  const client = useQueryClient()
  const [guest, setGuest] = useState(readGuestChoices)
  const query = useQuery({
    queryKey: key, queryFn: authApi.getSidebarPreferences, enabled: !!account,
    staleTime: Infinity, retry: 1,
  })
  const save = useMutation({
    mutationFn: ({ option, expanded }: { account: string; option: SidebarOption; expanded: boolean }) =>
      authApi.saveSidebarChoice(option, expanded),
    onSuccess: (_, { account, option, expanded }) => {
      const savedKey = ['sidebar-preferences', account]
      const needsReload = !client.getQueryData(savedKey)
      client.setQueryData<SidebarPreferences>(savedKey, current => ({ ...current, [option]: expanded }))
      if (needsReload) void client.invalidateQueries({ queryKey: savedKey })
    },
    onError: () => toast.error('Could not save your sidebar preference. Please try again.'),
  })
  const choices = account ? query.data : guest
  const isExpanded = (option: SidebarOption) => choices?.[option] ?? true
  const toggle = (option: SidebarOption) => {
    const expanded = !isExpanded(option)
    if (account) {
      save.mutate({ account, option, expanded })
    } else {
      const next = { ...guest, [option]: expanded }
      setGuest(next)
      try {
        localStorage.setItem(guestKey, JSON.stringify(next))
      } catch {
        // The guest can still use the sidebar with storage disabled.
      }
    }
  }
  return { isExpanded, toggle, busy: !!account && (query.isLoading || save.isPending) }
}
