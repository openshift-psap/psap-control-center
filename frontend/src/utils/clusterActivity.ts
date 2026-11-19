import type { ClusterOverview, FournosJobSummary } from '../types'

const QUEUED_STATUSES = new Set(['pending', 'resolving', 'admitted', 'queued', 'submitting', 'created'])
const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'stopped', 'cancelled', 'canceled', 'completed'])

export function isTerminalPhase(phase: string | undefined): boolean {
  return TERMINAL_STATUSES.has((phase || '').trim().toLowerCase())
}

export interface ClusterActivityGroups {
  queued: FournosJobSummary[]
  running: FournosJobSummary[]
  scheduled: FournosJobSummary[]
  other: FournosJobSummary[]
}

export function groupClusterActivity(jobs: FournosJobSummary[], now = Date.now()): ClusterActivityGroups {
  const groups: ClusterActivityGroups = { queued: [], running: [], scheduled: [], other: [] }

  for (const job of jobs) {
    const status = job.status.trim().toLowerCase()
    if (TERMINAL_STATUSES.has(status)) continue

    const scheduledAt = job.scheduled_start_time ? Date.parse(job.scheduled_start_time) : Number.NaN
    if (status === 'running') {
      groups.running.push(job)
    } else if (Number.isFinite(scheduledAt) && scheduledAt > now) {
      groups.scheduled.push(job)
    } else if (QUEUED_STATUSES.has(status)) {
      groups.queued.push(job)
    } else {
      groups.other.push(job)
    }
  }

  return groups
}

export function upcomingClusterActivity(
  overview: ClusterOverview,
  now = overview.as_of ? Date.parse(overview.as_of) : Date.now(),
) {
  const windowMs = 4 * 60 * 60 * 1000
  const through = now + windowMs
  const { running, queued, other, scheduled } = groupClusterActivity(overview.current_jobs, now)
  return {
    jobs: [...running, ...queued, ...other, ...scheduled.filter(job =>
      job.scheduled_start_time && Date.parse(job.scheduled_start_time) <= through)],
    recurring: overview.recurring_jobs.filter(job => {
      if (isTerminalPhase(job.phase)) return false
      if (job.dispatch_pending) return true
      if (!job.next_scheduled_time) return false
      const next = Date.parse(job.next_scheduled_time)
      return next > now && next <= through
    }),
    locks: overview.locks.filter(lock =>
      !isTerminalPhase(lock.phase)
      && Date.parse(lock.scheduled_start_time || lock.created_at) <= through
      && (!lock.lock_until || Date.parse(lock.lock_until) > now)),
  }
}

export function hasUpcomingClusterActivity(overview: ClusterOverview, now?: number): boolean {
  const { jobs, recurring, locks } = upcomingClusterActivity(overview, now)
  return jobs.length > 0 || recurring.length > 0 || locks.length > 0
}
