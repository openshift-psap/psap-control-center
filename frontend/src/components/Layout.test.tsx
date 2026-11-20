import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterAll, expect, it, vi } from 'vitest'
import Layout from './Layout'
import Results from '../pages/Results'
import { clearSession, setSession } from '../stores/authStore'
import { authApi } from '../services/api'

vi.hoisted(() => {
  vi.stubEnv('VITE_PERFORMANCE_DASHBOARD_PRODUCTION_URL', 'https://inference.example.test')
  vi.stubEnv('VITE_PERFORMANCE_DASHBOARD_STAGING_URL', 'https://staging.example.test')
})
afterAll(() => vi.unstubAllEnvs())

function CurrentLocation() {
  const { pathname, search } = useLocation()
  return <output aria-label="Current location">{pathname}{search}</output>
}

function renderLayout(entry: string, client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })) {
  client.setQueryData(['auth-config'], { google_enabled: true, local_login_enabled: false })
  client.setQueryData(['hearthStatus'], { configured: false, available: false })
  return render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/results" element={<Results />} />
          <Route path="*" element={null} />
        </Route>
      </Routes>
      <CurrentLocation />
    </MemoryRouter>
  </QueryClientProvider>)
}

it('toggles Testing from its label without leaving the current view, and navigates from Jobs', () => {
  renderLayout('/testing?tab=queued')
  const location = screen.getByLabelText('Current location')

  fireEvent.click(screen.getByText('Testing', { exact: true }))
  expect(location).toHaveTextContent('/testing?tab=queued')
  const toggle = screen.getByRole('button', { name: 'Expand Testing' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('link', { name: 'Jobs' })).toBeNull()

  fireEvent.click(toggle)
  expect(toggle).toHaveAccessibleName('Collapse Testing')
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.queryByRole('link', { name: 'Testing' })).toBeNull()
  const jobs = screen.getByRole('link', { name: 'Jobs' })
  expect(jobs).toHaveAttribute('aria-current', 'page')
  fireEvent.click(jobs)
  expect(location).toHaveTextContent('/testing?tab=live')
})

it('opens Coming Soon and toggles the saved dashboard choice on each Results activation', () => {
  const setItem = vi.fn()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => key === 'psap-sidebar-guest' ? '{"performance":false}' : null,
    setItem,
  })
  try {
    renderLayout('/calendar')
    const section = screen.getByRole('link', { name: /^Results/ }).closest('li')!
    const results = within(section)
    expect(screen.queryByRole('button', { name: /Performance Dashboard/ })).toBeNull()
    expect(results.queryByRole('link', { name: /^Inference Dashboard/ })).toBeNull()
    const link = results.getByRole('link', { name: /^Results/ })
    expect(link).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(link)
    expect(screen.getByRole('heading', { name: 'Coming Soon' })).toBeVisible()
    expect(link).toHaveAttribute('aria-expanded', 'true')
    const dashboards = results.getAllByRole('link', { name: /^Inference Dashboard/ })
    expect(dashboards.map(link => link.textContent)).toEqual(['Inference Dashboard', 'Inference Dashboard (Staging)'])
    expect(dashboards.map(link => link.getAttribute('href'))).toEqual(['https://inference.example.test', 'https://staging.example.test'])
    expect(dashboards.every(link => link.getAttribute('target') === '_blank')).toBe(true)
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/results')
    expect(setItem).toHaveBeenCalledWith('psap-sidebar-guest', JSON.stringify({ performance: true }))
    fireEvent.click(link)
    expect(screen.getByRole('heading', { name: 'Coming Soon' })).toBeVisible()
    expect(link).toHaveAttribute('aria-expanded', 'false')
    expect(results.queryByRole('link', { name: /^Inference Dashboard/ })).toBeNull()
    expect(setItem).toHaveBeenLastCalledWith('psap-sidebar-guest', JSON.stringify({ performance: false }))
    fireEvent.click(screen.getByRole('link', { name: 'Calendar' }))
    fireEvent.click(results.getByRole('button', { name: 'Expand Results' }))
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/calendar')
    expect(link).toHaveAttribute('aria-expanded', 'true')
  } finally {
    vi.unstubAllGlobals()
  }
})

it('remembers both signed-in Results clicks when the first save is still pending', async () => {
  setSession({ username: 'viewer', role: 'user' })
  let finishFirstSave!: () => void
  const firstSave = new Promise<void>(resolve => { finishFirstSave = resolve })
  const save = vi.spyOn(authApi, 'saveSidebarChoice').mockResolvedValue(undefined).mockReturnValueOnce(firstSave)
  const client = new QueryClient()
  const key = ['sidebar-preferences', 'local:viewer']
  client.setQueryData(key, { performance: false })
  const view = renderLayout('/calendar', client)
  try {
    const link = screen.getByRole('link', { name: /^Results/ })
    fireEvent.click(link)
    expect(screen.getByRole('heading', { name: 'Coming Soon' })).toBeVisible()
    await waitFor(() => expect(save).toHaveBeenCalledWith('performance', true))
    fireEvent.click(link)
    finishFirstSave()
    await waitFor(() => expect(save.mock.calls).toEqual([['performance', true], ['performance', false]]))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Expand Results' })).toBeEnabled())
    expect(client.getQueryData(key)).toEqual({ performance: false })
  } finally {
    finishFirstSave()
    view.unmount()
    save.mockRestore()
    clearSession()
  }
})

it('keeps Reservations, its admin pending count, and Calendar inside Tools', () => {
  setSession({ username: 'test-admin', role: 'admin' })
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['sidebar-preferences', 'local:test-admin'], { tools: true })
  client.setQueryData(['reservations', { status: 'pending' }], { total: 2 })
  const view = renderLayout('/clusters', client)
  try {
    const tools = within(screen.getByRole('button', { name: 'Collapse Tools' }).closest('li')!)
    fireEvent.click(tools.getByRole('link', { name: 'Reservations 2 pending' }))
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/reservations')
    fireEvent.click(tools.getByRole('link', { name: 'Calendar' }))
    expect(tools.getByRole('link', { name: 'Calendar' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByLabelText('Current location')).toHaveTextContent('/calendar')
    expect(screen.getAllByRole('link', { name: /^Reservations/ })).toHaveLength(1)
  } finally {
    view.unmount()
    clearSession()
  }
})
