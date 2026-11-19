import type { ReactNode } from 'react'
import { Disclosure, Menu } from '@headlessui/react'
import { ChevronDownIcon, EllipsisVerticalIcon, ServerStackIcon, TrashIcon } from '@heroicons/react/24/outline'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { format, formatDistanceToNowStrict } from 'date-fns'
import clsx from 'clsx'
import { clusterApi } from '../services/api'
import { useClusterCosts } from '../hooks/useClusterCost'
import type { Cluster, ClusterCostSummary, GpuPodInfo } from '../types'
import GpuDonutChart from './GpuDonutChart'

export default function ClusterCard({ cluster, latestCost, onRemove, removing }: {
  cluster: Cluster
  latestCost?: ClusterCostSummary | null
  onRemove?: () => void
  removing: boolean
}) {
  const { data: gpuData } = useQuery({
    queryKey: ['gpu-status', cluster.id],
    queryFn: () => clusterApi.getGpuStatus(cluster.id),
    enabled: cluster.status === 'healthy',
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const cTotal = gpuData?.total_gpus ?? parseInt(cluster.gpu_count || '0')
  const cUsed = gpuData?.allocated_gpus ?? 0
  const gpuNodeCount = gpuData?.gpu_types.reduce((sum, type) => sum + type.node_count, 0)

  const costSummary = latestCost
    ? `${billingMonth(latestCost.billing_month)} · ${money(latestCost.total_cost, latestCost.currency)}`
    : latestCost === null ? 'No billing data' : undefined

  return (
    <article aria-label={cluster.name} className="card min-w-0 p-6 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <div
            className={`h-12 w-12 shrink-0 rounded-xl flex items-center justify-center ${
              cluster.status === 'healthy'
                ? 'bg-green-100'
                : cluster.status === 'error'
                ? 'bg-orange-100'
                : 'bg-yellow-100'
            }`}
          >
            <ServerStackIcon
              className={`h-6 w-6 ${
                cluster.status === 'healthy'
                  ? 'text-green-600'
                  : cluster.status === 'error'
                  ? 'text-orange-600'
                  : 'text-yellow-600'
              }`}
            />
          </div>
          <div>
            <h3 className="break-words font-semibold text-gray-900">
              <Link to={`/clusters/${cluster.id}`} className="rounded-sm hover:underline focus-visible:outline-primary-600">
                {cluster.name}
              </Link>
            </h3>
            <span
              className={`badge mt-1 ${
                cluster.status === 'healthy'
                  ? 'badge-success'
                  : cluster.status === 'error'
                  ? 'badge-error'
                  : 'badge-warning'
              }`}
            >
              {cluster.status}
            </span>
          </div>
        </div>
        {onRemove && (
          <Menu as="div" className="relative ml-2 shrink-0">
            <Menu.Button aria-label={`Actions for ${cluster.name}`} className="rounded-md p-2 text-gray-500 hover:bg-gray-100 focus-visible:outline-primary-600">
              <EllipsisVerticalIcon className="h-5 w-5" />
            </Menu.Button>
            <Menu.Items className="absolute right-0 z-10 mt-1 w-44 rounded-md border border-gray-200 bg-white p-1 shadow-lg focus:outline-none">
              <Menu.Item disabled={removing}>
                {({ active }) => (
                  <button type="button" disabled={removing} onClick={onRemove}
                    className={clsx('flex w-full items-center gap-2 rounded px-3 py-2 text-sm text-orange-700', active && 'bg-orange-50')}>
                    <TrashIcon className="h-4 w-4" /> Remove cluster
                  </button>
                )}
              </Menu.Item>
            </Menu.Items>
          </Menu>
        )}
      </div>

      {cluster.description && (
        <p className="mt-4 text-sm text-gray-500 line-clamp-2">{cluster.description}</p>
      )}

      <div className="mt-4 flex items-center gap-4">
        {cTotal > 0 && (
          <GpuDonutChart used={cUsed} total={cTotal} size={72} strokeWidth={7} />
        )}
        <dl className="cluster-card-metrics">
          <div>
            <dt>Cluster nodes</dt>
            <dd>{cluster.node_count || 'N/A'}</dd>
          </div>
          <div>
            <dt title="Nodes with at least one detected GPU">GPU nodes</dt>
            <dd>{gpuNodeCount ?? 'N/A'}</dd>
          </div>
          <div>
            <dt>GPUs used</dt>
            <dd>{gpuData ? `${cUsed} / ${cTotal}` : `– / ${cTotal}`}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd>{cluster.cluster_version || 'N/A'}</dd>
          </div>
          <div className="col-span-full">
            <dt>Last Check</dt>
            <dd>
              {cluster.last_health_check
                ? format(new Date(cluster.last_health_check), 'MMM d, HH:mm')
                : 'Never'}
            </dd>
          </div>
        </dl>
      </div>

      {gpuData?.gpu_pods.length ? <ActiveGpuWorkloads pods={gpuData.gpu_pods} /> : null}
      <div className="mt-4 divide-y divide-gray-100 border-t border-gray-100">
        <CardDisclosure label="Past GPU workloads" summary="Up to 25 recent">
          <PastWorkloads clusterId={cluster.id} />
        </CardDisclosure>
        {cluster.provider === 'ibm' && (
          <CardDisclosure label="Cost history" summary={costSummary}>
            <CostHistory clusterId={cluster.id} />
          </CardDisclosure>
        )}
      </div>
    </article>
  )
}

function CardDisclosure({ label, summary, children }: {
  label: string
  summary?: ReactNode
  children: ReactNode
}) {
  return (
    <Disclosure as="div" className="min-w-0">
      <Disclosure.Button className="flex w-full items-center gap-2 rounded py-2.5 text-left text-sm focus-visible:outline-primary-600">
        {({ open }) => (
          <>
            <span className="min-w-0 break-words font-medium text-gray-800">{label}</span>
            {summary && <span className="ml-auto shrink-0 text-xs text-gray-600">{summary}</span>}
            <ChevronDownIcon className={clsx('h-4 w-4 shrink-0 text-gray-500', !summary && 'ml-auto', open && 'rotate-180')} />
          </>
        )}
      </Disclosure.Button>
      <Disclosure.Panel className="pb-3 text-sm">{children}</Disclosure.Panel>
    </Disclosure>
  )
}

function ActiveGpuWorkloads({ pods }: { pods: GpuPodInfo[] }) {
  const groups = new Map<string, GpuPodInfo[]>()
  for (const pod of pods) {
    const group = groups.get(pod.namespace)
    if (group) group.push(pod)
    else groups.set(pod.namespace, [pod])
  }

  return (
    <section className="mt-4 border-t border-gray-100 pt-3">
      <h4 className="text-xs font-medium text-gray-600">Active GPU workloads</h4>
      {Array.from(groups).sort(([a], [b]) => a.localeCompare(b)).map(([namespace, group]) => {
        const gpus = group.reduce((sum, pod) => sum + pod.gpu_count, 0)
        return (
          <CardDisclosure
            key={namespace}
            label={namespace}
            summary={
              <>
                {group.length} {group.length === 1 ? 'pod' : 'pods'} ·{' '}
                <span className="inline-block whitespace-nowrap rounded bg-blue-100 px-1.5 py-0.5 font-medium tabular-nums text-blue-800">
                  {gpuCount(gpus)}
                </span>
              </>
            }
          >
            <ul className="space-y-1.5">
              {group.map(pod => (
                <li key={pod.name} className="flex justify-between gap-3 text-xs">
                  <span className="min-w-0 break-all text-gray-700">{pod.name}</span>
                  <span className="shrink-0 text-purple-700">{gpuCount(pod.gpu_count)}</span>
                </li>
              ))}
            </ul>
          </CardDisclosure>
        )
      })}
    </section>
  )
}

function gpuCount(count: number) {
  return `${count} ${count === 1 ? 'GPU' : 'GPUs'}`
}

function PastWorkloads({ clusterId }: { clusterId: string }) {
  const query = useQuery({
    queryKey: ['gpu-pod-history', clusterId],
    queryFn: () => clusterApi.getGpuPodHistory(clusterId),
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
  if (!query.data) {
    if (query.isError) return <HistoryError label="workload history" retry={() => query.refetch()} />
    return <p role="status">Loading workloads…</p>
  }
  if (!query.data.pods.length) return <p>No past GPU workloads recorded.</p>
  return (
    <ul className="max-h-64 space-y-2 overflow-y-auto text-xs">
      {query.data.pods.map(pod => (
        <li key={`${pod.namespace}/${pod.name}`} className="flex justify-between gap-2">
          <span className="min-w-0 break-all text-gray-700">{pod.namespace}/{pod.name}</span>
          <span className="shrink-0 text-right text-gray-600">
            {gpuCount(pod.gpu_count)}<br />
            {pod.finished_at && <FinishedAt timestamp={pod.finished_at} />}
          </span>
        </li>
      ))}
    </ul>
  )
}

function FinishedAt({ timestamp }: { timestamp: string }) {
  // Historical records are UTC, including older API responses without an offset.
  const iso = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp) ? timestamp : timestamp + 'Z'
  const finished = new Date(iso)
  if (Number.isNaN(finished.getTime())) return null
  return <time dateTime={iso} title={finished.toLocaleString()}>{formatDistanceToNowStrict(finished, { addSuffix: true })}</time>
}

function money(amount: number, currency: string) {
  return amount.toLocaleString(undefined, { style: 'currency', currency })
}

function billingMonth(month?: string) {
  if (!month || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return month || 'Latest'
  return format(new Date(month + '-01T00:00:00'), 'MMM yyyy')
}

function CostHistory({ clusterId }: { clusterId: string }) {
  const query = useClusterCosts(clusterId)
  if (!query.data) {
    if (query.isError) return <HistoryError label="cost history" retry={() => query.refetch()} />
    return <p role="status">Loading costs…</p>
  }
  const valid = query.data.filter(cost => !cost.error && cost.total_cost != null)
  if (!valid.length) return <p>No billing data.</p>
  return (
    <dl className="space-y-1 text-sm">
      {valid.map(cost => (
        <div key={cost.billing_month || 'latest'} className="flex justify-between gap-2">
          <dt className="text-gray-600">{billingMonth(cost.billing_month)}</dt>
          <dd className="font-medium tabular-nums">{money(cost.total_cost!, cost.currency)}</dd>
        </div>
      ))}
    </dl>
  )
}

function HistoryError({ label, retry }: { label: string; retry: () => void }) {
  return (
    <p role="alert">
      Couldn’t load {label}.{' '}
      <button type="button" onClick={retry} className="text-primary-700 underline">Retry</button>
    </p>
  )
}
