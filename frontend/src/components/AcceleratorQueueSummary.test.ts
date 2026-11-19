import { describe, expect, it } from 'vitest'
import { groupClusterActivity, hasUpcomingClusterActivity } from '../utils/clusterActivity'
import type { ClusterLock, ClusterOverview, FournosJobSummary, RecurringJob } from '../types'

function job(name: string, status: string, scheduled_start_time: string | null = null): FournosJobSummary {
  return { name, status, scheduled_start_time } as FournosJobSummary
}

describe('submission activity prompt', () => {
  const now = Date.parse('2026-10-26T22:00:00Z')
  const empty: ClusterOverview = { cluster: 'demo', current_jobs: [], recurring_jobs: [], locks: [] }

  it('only counts active work and scheduled starts within the next four hours', () => {
    const has = (...jobs: FournosJobSummary[]) => hasUpcomingClusterActivity({ ...empty, current_jobs: jobs }, now)
    expect(has()).toBe(false)
    expect(has(job('running', 'Running'))).toBe(true)
    expect(has(job('queued', 'Admitted'))).toBe(true)
    expect(has(job('near', 'Pending', '2026-10-27T02:00:00Z'))).toBe(true)
    expect(has(job('far', 'Pending', '2026-10-27T02:01:00Z'), job('finished', 'Succeeded'))).toBe(false)
  })

  it('checks recurring schedules across midnight and excludes expired locks', () => {
    const recurring = (schedule: string, phase = 'Pending') => ({ ...empty, recurring_jobs: [{ schedule, phase } as RecurringJob] })
    expect(hasUpcomingClusterActivity(recurring('0 1 * * *'), now)).toBe(true)
    expect(hasUpcomingClusterActivity(recurring('0 3 * * *'), now)).toBe(false)
    expect(hasUpcomingClusterActivity(recurring('0 1 * * *', 'Stopped'), now)).toBe(false)
    const lock = (start: string, until: string | null, phase = 'Running') => ({
      ...empty, locks: [{ created_at: start, lock_until: until, phase } as ClusterLock],
    })
    expect(hasUpcomingClusterActivity(lock('2026-10-26T17:00:00Z', null), now)).toBe(true)
    expect(hasUpcomingClusterActivity(lock('2026-10-26T17:00:00Z', null, 'Succeeded'), now)).toBe(false)
    expect(hasUpcomingClusterActivity(lock('2026-10-27T01:00:00Z', null), now)).toBe(true)
    expect(hasUpcomingClusterActivity(lock('2026-10-26T17:00:00Z', '2026-10-26T18:00:00Z'), now)).toBe(false)
  })
})

describe('groupClusterActivity', () => {
  const now = Date.parse('2026-10-26T18:00:00Z')

  it('separates queued and running jobs from terminal jobs', () => {
    const groups = groupClusterActivity([
      job('pending', 'Pending'),
      job('admitted', 'Admitted'),
      job('resolving', 'Resolving'),
      job('running', 'Running'),
      job('finished', 'Succeeded'),
    ], now)

    expect(groups.queued.map((item) => item.name)).toEqual(['pending', 'admitted', 'resolving'])
    expect(groups.running.map((item) => item.name)).toEqual(['running'])
    expect(groups.scheduled).toEqual([])
    expect(groups.other).toEqual([])
  })

  it('classifies future-start jobs as scheduled', () => {
    const groups = groupClusterActivity([
      job('later', 'Pending', '2026-10-26T19:00:00Z'),
      job('already-started', 'Pending', '2026-10-26T17:00:00Z'),
    ], now)

    expect(groups.scheduled.map((item) => item.name)).toEqual(['later'])
    expect(groups.queued.map((item) => item.name)).toEqual(['already-started'])
  })
})
