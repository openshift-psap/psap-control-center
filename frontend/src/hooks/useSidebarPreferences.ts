import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { authApi } from '../services/api'
import { getPreferenceAccount } from '../stores/authStore'
import type { SidebarOption, SidebarPreferences } from '../types'

const guestKey = 'psap-sidebar-guest'

function sidebarExpanded(choices: SidebarPreferences | undefined, option: SidebarOption) {
  return choices?.[option] ?? (option !== 'tools')
}

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
    // A second activation can arrive while loading the preference or saving the first.
    // Apply each flip to the last confirmed choice for that account.
    scope: { id: `sidebar-preferences:${account}` },
    mutationFn: async ({ account, option }: { account: string; option: SidebarOption }) => {
      if (getPreferenceAccount() !== account) return
      const choices = await client.ensureQueryData({
        queryKey: ['sidebar-preferences', account], queryFn: authApi.getSidebarPreferences,
      })
      if (getPreferenceAccount() !== account) return
      const expanded = !sidebarExpanded(choices, option)
      await authApi.saveSidebarChoice(option, expanded)
      return expanded
    },
    onSuccess: (expanded, { account, option }) => {
      if (expanded === undefined) return
      const savedKey = ['sidebar-preferences', account]
      client.setQueryData<SidebarPreferences>(savedKey, current => ({ ...current, [option]: expanded }))
    },
    onError: () => toast.error('Could not save your sidebar preference. Please try again.'),
  })
  const choices = account ? query.data : guest
  const isExpanded = (option: SidebarOption) => sidebarExpanded(choices, option)
  const toggle = (option: SidebarOption) => {
    if (account) {
      save.mutate({ account, option })
    } else {
      const next = { ...guest, [option]: !isExpanded(option) }
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
