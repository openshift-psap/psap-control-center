import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { fournosApi } from '../services/api'
import SchedulingCalendar from './SchedulingCalendar'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('renders every projected start in day view and requests the first daily starts in month view', async () => {
  vi.spyOn(fournosApi, 'listSlotHolds').mockResolvedValue([])
  const overview = vi.spyOn(fournosApi, 'getClusterOverview').mockImplementation(async (cluster, calendar) => ({
    cluster, current_jobs: [], locks: [],
    recurring_jobs: [
      { name: 'quarter-hour', project: 'demo', schedule: '*/15 * * * *', dispatch_pending: true,
        calendar_starts: { [calendar!.calendar_date]: calendar!.calendar_view === 'day' ? ['10:00', '10:15'] : ['00:00'] } },
      { name: 'monthly', project: 'demo', schedule: '0 12 1 * *', calendar_starts: {} },
    ],
  }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <SchedulingCalendar cluster="demo" readOnly initialView="day" variant="submit" onApply={() => {}} />
  </QueryClientProvider>)
  expect(await screen.findByText('quarter-hour (10:15, demo)')).toBeInTheDocument()
  expect(screen.getByText('Awaiting dispatch: quarter-hour')).toBeInTheDocument()
  expect(screen.getByText('quarter-hour (10:00, demo)')).toBeInTheDocument()
  expect(screen.queryByText(/monthly/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '← Month view' }))
  expect(await screen.findByText('recurring 00:00')).toBeInTheDocument()
  expect(overview).toHaveBeenLastCalledWith('demo', expect.objectContaining({
    calendar_view: 'month', calendar_date: expect.stringMatching(/-01$/),
  }))
})

it('explains active jobs without start times and omits stopped locks in day and month views', async () => {
  vi.spyOn(fournosApi, 'listSlotHolds').mockResolvedValue([])
  const now = new Date().toISOString()
  const lock = { cluster: 'demo', reason: '', owner: 'owner', lock_until: null, scheduled_start_time: null, created_at: now }
  vi.spyOn(fournosApi, 'getClusterOverview').mockResolvedValue({
    cluster: 'demo', as_of: now, recurring_jobs: [],
    current_jobs: [{ name: 'training', status: 'Running' }, { name: 'batch', status: 'Queued' }, { name: 'past-run', status: 'Succeeded' }],
    locks: [{ ...lock, name: 'maintenance', phase: 'Running' }, { ...lock, name: 'released', phase: 'Stopped' }],
  })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <SchedulingCalendar cluster="demo" readOnly initialView="day" variant="submit" onApply={() => {}} />
  </QueryClientProvider>)
  const activity = await screen.findByRole('region', { name: 'Current and upcoming cluster activity' })
  expect(within(activity).getByText('training · Running')).toBeInTheDocument()
  expect(within(activity).getByText('batch · Queued')).toBeInTheDocument()
  expect(screen.queryByText(/past-run/)).toBeNull()
  expect(screen.getByText('lock-owner-maintenance (held now)')).toBeInTheDocument()
  expect(screen.queryByText(/released/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '← Month view' }))
  expect(await screen.findAllByText('lock 00:00')).toHaveLength(1)
})
