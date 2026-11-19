import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
      { name: 'quarter-hour', project: 'demo', schedule: '*/15 * * * *',
        calendar_starts: { [calendar!.calendar_date]: calendar!.calendar_view === 'day' ? ['10:00', '10:15'] : ['00:00'] } },
      { name: 'monthly', project: 'demo', schedule: '0 12 1 * *', calendar_starts: {} },
    ],
  }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <SchedulingCalendar cluster="demo" readOnly initialView="day" variant="submit" onApply={() => {}} />
  </QueryClientProvider>)
  expect(await screen.findByText('quarter-hour (10:15, demo)')).toBeInTheDocument()
  expect(screen.getByText('quarter-hour (10:00, demo)')).toBeInTheDocument()
  expect(screen.queryByText(/monthly/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '← Month view' }))
  expect(await screen.findByText('recurring 00:00')).toBeInTheDocument()
  expect(overview).toHaveBeenLastCalledWith('demo', expect.objectContaining({
    calendar_view: 'month', calendar_date: expect.stringMatching(/-01$/),
  }))
})
