import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Link, MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearSession, setSession } from '../stores/authStore'
import { clusterApi, fournosApi } from '../services/api'
import type { FournosJobSummary, HistoryViewState } from '../types'
import Testing, { JobsTable } from './Testing'

const archived = {
  name: 'nightly-run', status: 'Succeeded', trigger_type: 'recurring',
  triggered_by_schedule: 'nightly', forge_git_version: 'v1.2.3',
  forge_image_digest: 'sha256:abcd', duration_seconds: 60, owner: 'Example Owner',
  mlflow_url: 'https://example.org/run',
} as FournosJobSummary

describe('History table', () => {
  afterEach(() => { clearSession(); vi.restoreAllMocks() })

  it('shows the saved advanced filters and uses their values for the History request', async () => {
    setSession({ username: 'viewer', role: 'user' })
    const state: HistoryViewState = {
      query: '', project: '', cluster: '', status: '', requester_scope: 'all', identity: 'Example Owner',
      failure_outcome: 'failed', repository: 'example/repo', pr_number: 17, source_sha: 'abcd1234',
      forge: 'v1.2.3', work_item_provider: 'jira', work_item_key: 'TEST-7', tags: ['nightly'],
      history_date: '', from_time: '00:00', to_time: '23:59', sort_by: 'triggered_by', sort_dir: 'asc', per_page: 100,
    }
    vi.spyOn(fournosApi, 'getHistoryPreference').mockResolvedValue({ state, schema_version: 1, updated_at: null })
    const save = vi.spyOn(fournosApi, 'saveHistoryPreference').mockResolvedValue({ state, schema_version: 1, updated_at: null })
    vi.spyOn(fournosApi, 'getHistoryFilterOptions').mockResolvedValue({
      identities: [], repositories: [], pr_numbers: [], source_shas: [], forge: [], tags: [], work_item_providers: [], work_item_keys: [],
    })
    vi.spyOn(clusterApi, 'list').mockResolvedValue({ clusters: [], total: 0 })
    vi.spyOn(fournosApi, 'listProjects').mockResolvedValue([])
    const list = vi.spyOn(fournosApi, 'listJobs').mockResolvedValue({ jobs: [archived], total: 1, page: 1, per_page: 100 })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const page = () => <QueryClientProvider client={client}><MemoryRouter initialEntries={['/testing?tab=history']}>
      <Link to="/testing?tab=live">Jobs sidebar link</Link>
      <Testing />
    </MemoryRouter></QueryClientProvider>
    const { rerender } = render(page())

    fireEvent.click(screen.getByText('Filter list'))
    await waitFor(() => expect(screen.getByLabelText('Owner or requester')).toHaveValue(state.identity))
    for (const [label, value] of [
      ['Failure outcome', 'failed'], ['Source repository', 'example/repo'], ['Pull request number', '17'],
      ['Source commit SHA', 'abcd1234'], ['Forge version or image digest', 'v1.2.3'],
      ['Work-item provider', 'jira'], ['Work-item key', 'TEST-7'], ['Tags', 'nightly'],
    ]) expect(screen.getByLabelText(label)).toHaveValue(value)
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({
      tab: 'history', identity: state.identity, failure_outcome: 'failed', repository: state.repository,
      pr_number: 17, source_sha: state.source_sha, forge: state.forge, work_item_provider: 'jira',
      work_item_key: 'TEST-7', tags: 'nightly', sort_by: 'triggered_by',
    })))

    fireEvent.click(screen.getByRole('link', { name: 'Jobs sidebar link' }))
    fireEvent.click(screen.getByRole('tab', { name: 'History' }))
    await waitFor(() => expect(screen.getByLabelText('Source repository')).toHaveValue(state.repository))
    expect(screen.getByLabelText('Owner or requester')).toHaveValue(state.identity)

    clearSession()
    rerender(page())
    await waitFor(() => expect(screen.getByLabelText('Source repository')).toHaveValue(''))
    const otherState = { ...state, repository: 'another/repo', identity: 'Another owner' }
    vi.mocked(fournosApi.getHistoryPreference).mockResolvedValue({ state: otherState, schema_version: 1, updated_at: null })
    setSession({ username: 'another-user', role: 'user' })
    rerender(page())
    await waitFor(() => expect(screen.getByLabelText('Source repository')).toHaveValue(otherState.repository))
    expect(screen.getByLabelText('Owner or requester')).toHaveValue(otherState.identity)
    expect(save).not.toHaveBeenCalled()
  })

  it('shows the schedule and observed Forge version alongside duration and MLflow', () => {
    setSession({ username: 'viewer', role: 'user' })
    const onSort = vi.fn()
    render(<MemoryRouter><JobsTable jobs={[archived]} source="history" sort={{ by: 'date', dir: 'desc' }} onSort={onSort} /></MemoryRouter>)

    expect(screen.getByText('Example Owner')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'nightly' })).toHaveAttribute('href', '/testing/schedules/nightly/runs')
    expect(screen.getByText('v1.2.3')).toBeInTheDocument()
    expect(screen.getByTitle('sha256:abcd')).toBeInTheDocument()
    expect(screen.getByText('00h 01m 00s')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'MLflow' })).toHaveAttribute('href', archived.mlflow_url)
    fireEvent.click(screen.getByRole('button', { name: 'Triggered By' }))
    expect(onSort).toHaveBeenCalledWith('triggered_by')
  })

  it('handles partial provenance and hides previously fetched owners when signed out', () => {
    const jobs = [
      { ...archived, forge_git_version: '', trigger_type: 'deferred' },
      { ...archived, name: 'older', forge_git_version: '', forge_image_digest: '', forge_provenance_state: 'pending', trigger_type: 'manual' },
    ]
    render(<MemoryRouter><JobsTable jobs={jobs} source="history" sort={{ by: 'date', dir: 'desc' }} onSort={vi.fn()} /></MemoryRouter>)

    const [, deferred, older] = screen.getAllByRole('row')
    expect(within(deferred).getByText('Deferred')).toBeInTheDocument()
    expect(within(deferred).getByTitle('sha256:abcd')).toBeInTheDocument()
    expect(within(older).getByTitle('pending')).toHaveTextContent('-')
    expect(screen.getAllByText('Sign in to view')).toHaveLength(2)
    expect(screen.queryByText('Example Owner')).toBeNull()
  })
})
