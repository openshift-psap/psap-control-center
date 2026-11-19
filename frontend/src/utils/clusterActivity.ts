import type { ClusterOverview, FournosJobSummary } from '../types'
import { cronFiresWithin } from './cronOccurrences'

const QUEUED_STATUSES = new Set(['pending', 'resolving', 'admitted', 'queued', 'submitting', 'created'])
const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'stopped', 'cancelled', 'canceled', 'completed'])

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
    if (Number.isFinite(scheduledAt) && scheduledAt > now) {
      groups.scheduled.push(job)
    } else if (status === 'running') {
      groups.running.push(job)
    } else if (QUEUED_STATUSES.has(status)) {
      groups.queued.push(job)
    } else {
      groups.other.push(job)
    }
  }

  return groups
}

export function hasUpcomingClusterActivity(overview: ClusterOverview, now = Date.now()): boolean {
  const windowMs = 4 * 60 * 60 * 1000
  const through = now + windowMs
  const { running, queued, scheduled } = groupClusterActivity(overview.current_jobs, now)
  return running.length > 0 || queued.length > 0
    || scheduled.some(job => job.scheduled_start_time && Date.parse(job.scheduled_start_time) <= through)
    || overview.recurring_jobs.some(job =>
      !TERMINAL_STATUSES.has(job.phase.toLowerCase()) && cronFiresWithin(job.schedule, new Date(now), windowMs),
    )
    || overview.locks.some(lock =>
      !TERMINAL_STATUSES.has(lock.phase.toLowerCase())
      && Date.parse(lock.scheduled_start_time || lock.created_at) <= through
      && (!lock.lock_until || Date.parse(lock.lock_until) > now),
    )
}
