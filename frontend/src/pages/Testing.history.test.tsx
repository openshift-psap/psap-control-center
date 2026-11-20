import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

    // Sign-out before the debounce expires must discard the first account's unsaved edit.
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search run history' }), { target: { value: 'first-user-only' } })
    clearSession()
    rerender(page())
    await waitFor(() => expect(screen.getByLabelText('Source repository')).toHaveValue(''))
    const otherState = { ...state, repository: 'another/repo', identity: 'Another owner' }
    vi.mocked(fournosApi.getHistoryPreference).mockResolvedValue({ state: otherState, schema_version: 1, updated_at: null })
    setSession({ username: 'another-user', role: 'user' })
    rerender(page())
    await waitFor(() => expect(screen.getByLabelText('Source repository')).toHaveValue(otherState.repository))
    expect(screen.getByLabelText('Owner or requester')).toHaveValue(otherState.identity)
    fireEvent.click(screen.getByRole('tab', { name: 'Live' }))
    expect(save).not.toHaveBeenCalled()
  })

  it.each(['Live tab', 'sidebar'])('saves the last edit when leaving History immediately through the %s', async navigation => {
    setSession({ username: 'viewer', role: 'user' })
    let finishWrite!: () => void
    const save = vi.spyOn(fournosApi, 'saveHistoryPreference').mockImplementation(state =>
      new Promise(resolve => { finishWrite = () => resolve({ state, schema_version: 1, updated_at: null }) }))
    vi.spyOn(fournosApi, 'listJobs').mockResolvedValue({ jobs: [], total: 0, page: 1, per_page: 100 })
    vi.spyOn(fournosApi, 'getHistoryFilterOptions').mockResolvedValue({
      identities: [], repositories: [], pr_numbers: [], source_shas: [], forge: [], tags: [], work_item_providers: [], work_item_keys: [],
    })
    vi.spyOn(clusterApi, 'list').mockResolvedValue({ clusters: [], total: 0 })
    vi.spyOn(fournosApi, 'listProjects').mockResolvedValue([])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/testing?tab=history&q=shared']}>
      <Link to="/testing?tab=live">Jobs sidebar link</Link>
      <Testing />
    </MemoryRouter></QueryClientProvider>)

    const leave = () => fireEvent.click(navigation === 'Live tab'
      ? screen.getByRole('tab', { name: 'Live' }) : screen.getByRole('link', { name: 'Jobs sidebar link' }))
    const search = () => screen.getByRole('searchbox', { name: 'Search run history' })
    expect(search()).toHaveValue('shared')
    fireEvent.change(search(), { target: { value: 'train' } })
    fireEvent.change(search(), { target: { value: 'training' } })
    leave()
    fireEvent.click(screen.getByRole('tab', { name: 'History' }))
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1))
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ query: 'training' }))
    expect(search()).toHaveValue('training')
    await act(async () => finishWrite())
    // Clearing the last filter also survives navigation, despite the empty URL.
    fireEvent.change(search(), { target: { value: '' } })
    leave()
    fireEvent.click(screen.getByRole('tab', { name: 'History' }))
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect(save).toHaveBeenLastCalledWith(expect.objectContaining({ query: '' }))
    expect(search()).toHaveValue('')
    await act(async () => finishWrite())
    expect(client.getQueryData(['fournos-history-preference', 'local:viewer'])).toMatchObject({ state: { query: '' } })
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
    expect(screen.getByRole('link', { name: 'Open in MLflow' })).toHaveAttribute('href', archived.mlflow_url)
    fireEvent.click(screen.getByRole('button', { name: 'Triggered By' }))
    expect(onSort).toHaveBeenCalledWith('triggered_by')
  })

  it('inspects the selected History row on demand and returns focus when collapsed, including signed out', async () => {
    const list = vi.spyOn(fournosApi, 'getMlflowDirectory').mockImplementation(async (job, path) => ({
      files: path
        ? [{ path: 'stage/status.yaml', is_dir: false, file_size: 8 }]
        : [{ path: job === archived.name ? 'stage' : 'other', is_dir: true, file_size: null }],
      next_page_token: null,
    }))
    const preview = vi.spyOn(fournosApi, 'getMlflowPreview').mockResolvedValue({ text: 'passed: true' })
    const jobs = [archived, { ...archived, name: 'second-run', mlflow_url: 'https://example.org/second' }]
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
      <JobsTable jobs={jobs} source="history" sort={{ by: 'date', dir: 'desc' }} onSort={vi.fn()} />
    </MemoryRouter></QueryClientProvider>)
    const [header, first, second] = screen.getAllByRole('row')
    const inspect = within(first).getByRole('button', { name: 'Inspect' })
    const external = within(first).getByRole('link', { name: 'Open in MLflow' })
    expect(external).toHaveAttribute('target', '_blank')
    expect(inspect.nextElementSibling).toBe(external)
    expect(list).not.toHaveBeenCalled()
    fireEvent.click(inspect)
    const panel = screen.getByRole('region', { name: 'MLflow artifacts' })
    expect(inspect).toHaveAttribute('aria-controls', panel.id)
    expect(panel.closest('tr')).toBe(first.nextElementSibling)
    expect(panel.closest('td')?.colSpan).toBe(within(header).getAllByRole('columnheader').length)
    fireEvent.click(await within(panel).findByRole('button', { name: 'stage/' }))
    fireEvent.click(await within(panel).findByRole('button', { name: 'status.yaml' }))
    expect(await within(panel).findByText('passed: true')).toBeVisible()
    expect(preview).toHaveBeenCalledWith(archived.name, 'stage/status.yaml', expect.any(AbortSignal))

    const inspectSecond = within(second).getByRole('button', { name: 'Inspect' })
    fireEvent.click(inspectSecond)
    expect(await screen.findByRole('button', { name: 'other/' })).toBeVisible()
    expect(screen.queryByText('passed: true')).toBeNull()
    expect(inspect).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('region', { name: 'MLflow artifacts' }).closest('tr')).toBe(second.nextElementSibling)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse file inspector' }))
    expect(inspectSecond).toHaveFocus()
    expect(inspectSecond).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region', { name: 'MLflow artifacts' })).toBeNull()
  })

  it('omits MLflow actions when the archived run has no usable link', () => {
    const jobs = [{ ...archived, mlflow_url: '' }, { ...archived, name: 'invalid', mlflow_url: 'broken' }]
    render(<MemoryRouter><JobsTable jobs={jobs} source="history" sort={{ by: 'date', dir: 'desc' }} onSort={vi.fn()} /></MemoryRouter>)
    expect(screen.queryByRole('button', { name: 'Inspect' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Open in MLflow' })).toBeNull()
  })

  it('shows recorded owners and handles missing owners and partial provenance when signed out', () => {
    const jobs = [
      { ...archived, forge_git_version: '', trigger_type: 'deferred' },
      { ...archived, name: 'older', owner: '', forge_git_version: '', forge_image_digest: '', forge_provenance_state: 'pending', trigger_type: 'manual' },
    ]
    render(<MemoryRouter><JobsTable jobs={jobs} source="history" sort={{ by: 'date', dir: 'desc' }} onSort={vi.fn()} /></MemoryRouter>)

    const [, deferred, older] = screen.getAllByRole('row')
    expect(within(deferred).getByText('Deferred')).toBeInTheDocument()
    expect(within(deferred).getByTitle('sha256:abcd')).toBeInTheDocument()
    expect(within(older).getByTitle('pending')).toHaveTextContent('-')
    expect(within(deferred).getByText('Example Owner')).toBeInTheDocument()
    expect(within(older).getAllByRole('cell')[2]).toHaveTextContent('-')
  })
})
