// Tests for the ?project= permalink behavior on the Testing submit form
// (see SubmitForm in Testing.tsx): valid permalinks pre-select the project
// and skip the job-type step, unknown permalink names fall back to the
// empty selector without a re-apply loop, dropdown changes sync to the URL
// with replace-style navigation, and externally-changed permalinks
// (browser back/forward) are re-applied without duplicating history
// entries. All data hooks are mocked — no network, no QueryClient.

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { useSearchParams } from 'react-router-dom'
import { unstable_HistoryRouter as HistoryRouter } from 'react-router-dom'
import { createMemoryHistory, type MemoryHistory } from '@remix-run/router'
import Testing from './Testing'

const mocks = vi.hoisted(() => ({
  projects: [] as Array<{ name: string; cluster?: string }>,
  uiSchemaNames: [] as Array<string | undefined>,
}))

// Every hook the Testing page (or its transitively imported components)
// uses, stubbed with inert, synchronous data.
vi.mock('../hooks/useFournos', () => {
  const query = (extra: Record<string, unknown> = {}) => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...extra,
  })
  const mutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })
  return {
    useFournosJobs: () => query(),
    useFournosJob: () => query(),
    useFournosJobEvents: () => query(),
    useCancelJob: mutation,
    useRerunJob: mutation,
    useDeleteHistoryJob: mutation,
    useSubmitJob: mutation,
    useForgeProjects: () => query({ data: mocks.projects }),
    useProjectUiSchema: (name: string | undefined) => {
      mocks.uiSchemaNames.push(name)
      return query({ data: { found: false, project: name, ui_schema: null } })
    },
    useRefreshProjectUiSchema: mutation,
    usePipelines: () => query({ data: [] }),
    useRecurringJobs: () => query({ data: [] }),
    useRecurringJobChildren: () => query({ data: [] }),
    useTriggerRecurringJob: mutation,
    useDeleteRecurringJob: mutation,
    useClusterLocks: () => query({ data: [] }),
    useCreateClusterLock: mutation,
    useDeleteClusterLock: mutation,
    useClusterOverview: () => query(),
    useSlotHolds: () => query({ data: [] }),
    useHoldSlot: mutation,
    useReleaseSlot: mutation,
    useGithubPRs: () => query({ data: [] }),
    useRefreshGithubPRs: mutation,
    useGithubSyncStatus: () => query(),
    useRefreshGithubSync: mutation,
    useSubmitMatrix: mutation,
  }
})

vi.mock('../hooks/useClusters', () => ({
  useClusters: () => ({ data: { clusters: [] } }),
  useCluster: () => ({ data: undefined }),
  useClusterStatus: () => ({ data: undefined }),
  useCreateCluster: () => ({ mutate: vi.fn() }),
  useUpdateCluster: () => ({ mutate: vi.fn() }),
  useDeleteCluster: () => ({ mutate: vi.fn() }),
  useRefreshClusterStatus: () => ({ mutate: vi.fn() }),
  useUploadKubeconfig: () => ({ mutate: vi.fn() }),
  useClusterTopology: () => ({ data: undefined }),
  useOcpDetails: () => ({ data: undefined }),
  useClusterOperators: () => ({ data: undefined }),
  useClusterWorkloads: () => ({ data: undefined }),
}))

vi.mock('../stores/authStore', () => ({
  isAuthenticated: () => true,
  isAdmin: () => false,
  getUsername: () => 'tester',
  getDisplayName: () => 'Test User',
  getRole: () => 'user',
  getSession: () => null,
  setSession: vi.fn(),
  clearSession: vi.fn(),
}))

// Renders the current ?query string so tests can assert URL sync.
function UrlProbe() {
  const [searchParams] = useSearchParams()
  return <div data-testid="url-probe">{searchParams.toString()}</div>
}

function renderTesting(initialUrl: string): MemoryHistory {
  // v5Compat makes push/replace notify listeners, the way React Router's
  // own MemoryRouter wires its history.
  const history = createMemoryHistory({ initialEntries: [initialUrl], v5Compat: true }) as unknown as MemoryHistory
  render(
    <HistoryRouter history={history as never}>
      <UrlProbe />
      <Testing />
    </HistoryRouter>
  )
  return history as MemoryHistory
}

function projectSelect(): HTMLSelectElement {
  return screen.getByRole('option', { name: 'Select a project' }).closest('select') as HTMLSelectElement
}

beforeEach(() => {
  mocks.projects.length = 0
  mocks.projects.push({ name: 'rhaiis', cluster: 'cluster-a' }, { name: 'llm_d', cluster: '' })
  mocks.uiSchemaNames.length = 0
})

describe('Testing submit-form project permalink', () => {
  it('pre-selects a valid permalink project and skips the job-type step', async () => {
    renderTesting('/testing?tab=submit&project=rhaiis')

    await waitFor(() => {
      expect(projectSelect()).toHaveValue('rhaiis')
    })
    // The permalink skips straight to the forge "Basics" step.
    expect(screen.queryByText('What do you want to do?')).not.toBeInTheDocument()
    expect(screen.getByText('Basics')).toBeInTheDocument()
    expect(screen.getByTestId('url-probe')).toHaveTextContent('project=rhaiis')
    // A known project may drive the ui-schema fetch.
    expect(mocks.uiSchemaNames).toContain('rhaiis')
  })

  it('falls back to the empty selector for an unknown permalink, without a re-apply loop', async () => {
    renderTesting('/testing?tab=submit&project=ghost')

    // The unknown name is dropped from the selector and the URL, and a
    // notice explains why, once the project list has loaded.
    await waitFor(() => {
      expect(screen.getByText(/ghost/)).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(projectSelect()).toHaveValue('')
    })
    expect(screen.getByTestId('url-probe')).not.toHaveTextContent('project=ghost')
    // The raw permalink value never reaches the ui-schema fetch.
    expect(mocks.uiSchemaNames).not.toContain('ghost')
  })

  it('syncs dropdown changes to the URL without adding history entries', async () => {
    const history = renderTesting('/testing?tab=submit')

    // No permalink: the form starts on the job-type step.
    expect(screen.getByText('What do you want to do?')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Run a Forge Job'))
    await waitFor(() => {
      expect(projectSelect()).toBeInTheDocument()
    })

    fireEvent.change(projectSelect(), { target: { value: 'rhaiis' } })
    await waitFor(() => {
      expect(screen.getByTestId('url-probe')).toHaveTextContent('project=rhaiis')
    })
    // replace-style navigation: the permalink is shareable but Back still
    // leaves the form instead of stepping back through every selection.
    expect(history.index).toBe(0)
  })

  it('re-applies an externally-changed permalink without duplicating history entries', async () => {
    const history = renderTesting('/testing?tab=submit&project=rhaiis')
    await waitFor(() => {
      expect(projectSelect()).toHaveValue('rhaiis')
    })

    // Simulate browser back/forward (or any navigation the form did not
    // initiate) landing on a different project permalink.
    act(() => {
      history.push('/testing?tab=submit&project=llm_d')
    })
    await waitFor(() => {
      expect(projectSelect()).toHaveValue('llm_d')
    })
    // The URL already holds the value — applying it must not push again.
    expect(history.index).toBe(1)
    expect(screen.getByTestId('url-probe')).toHaveTextContent('project=llm_d')
  })
})
