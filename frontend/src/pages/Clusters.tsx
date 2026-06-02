import { useState, Fragment } from 'react'
import { Link } from 'react-router-dom'
import { Dialog, Transition, Tab } from '@headlessui/react'
import {
  PlusIcon,
  ServerStackIcon,
  ArrowPathIcon,
  TrashIcon,
  EyeIcon,
  CloudArrowUpIcon,
  KeyIcon,
  EyeSlashIcon,
} from '@heroicons/react/24/outline'
import { useDropzone } from 'react-dropzone'
import { useQueries } from '@tanstack/react-query'
import { useClusters, useCreateCluster, useDeleteCluster } from '../hooks/useClusters'
import { clusterApi } from '../services/api'
import { format } from 'date-fns'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import type { GpuAllocationStatus } from '../types'

type AuthMethod = 'kubeconfig' | 'credentials'

export default function Clusters() {
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [authMethod, setAuthMethod] = useState<AuthMethod>('kubeconfig')
  const [showPassword, setShowPassword] = useState(false)
  const [newCluster, setNewCluster] = useState({ 
    name: '', 
    description: '', 
    kubeconfig: '',
    apiServer: '',
    username: '',
    password: '',
  })
  const [kubeconfigFile, setKubeconfigFile] = useState<File | null>(null)

  const { data, isLoading, refetch } = useClusters()
  const createCluster = useCreateCluster()
  const deleteCluster = useDeleteCluster()

  const clusters = data?.clusters || []

  const gpuStatusQueries = useQueries({
    queries: clusters.map((c) => ({
      queryKey: ['gpu-status', c.id],
      queryFn: () => clusterApi.getGpuStatus(c.id),
      enabled: c.status === 'healthy',
      staleTime: 30_000,
      refetchInterval: 60_000,
    })),
  })
  const gpuStatusByCluster = clusters.reduce<Record<string, GpuAllocationStatus | undefined>>((acc, c, i) => {
    acc[c.id] = gpuStatusQueries[i]?.data as GpuAllocationStatus | undefined
    return acc
  }, {})

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/x-yaml': ['.yaml', '.yml'], 'text/plain': ['.kubeconfig'] },
    multiple: false,
    onDrop: async (files) => {
      if (files[0]) {
        setKubeconfigFile(files[0])
        const content = await files[0].text()
        setNewCluster((prev) => ({ ...prev, kubeconfig: content }))
      }
    },
  })

  const resetForm = () => {
    setNewCluster({ 
      name: '', 
      description: '', 
      kubeconfig: '',
      apiServer: '',
      username: '',
      password: '',
    })
    setKubeconfigFile(null)
    setAuthMethod('kubeconfig')
    setShowPassword(false)
  }

  const handleCreate = async () => {
    if (!newCluster.name) {
      toast.error('Cluster name is required')
      return
    }

    if (authMethod === 'kubeconfig' && !newCluster.kubeconfig) {
      toast.error('Please upload a kubeconfig file')
      return
    }

    if (authMethod === 'credentials') {
      if (!newCluster.apiServer || !newCluster.username || !newCluster.password) {
        toast.error('API Server URL, username, and password are required')
        return
      }
    }

    try {
      if (authMethod === 'kubeconfig') {
        await createCluster.mutateAsync({
          name: newCluster.name,
          description: newCluster.description,
          kubeconfig_content: newCluster.kubeconfig,
        })
      } else {
        await createCluster.mutateAsync({
          name: newCluster.name,
          description: newCluster.description,
          api_server_url: newCluster.apiServer,
          username: newCluster.username,
          password: newCluster.password,
        })
      }

      setIsAddOpen(false)
      resetForm()
    } catch (error) {
      // Error is handled by the mutation
    }
  }

  const handleRemove = async (id: string, name: string) => {
    if (deleteCluster.isPending) return
    if (window.confirm(`Remove cluster "${name}" from the Control Center?\n\nThis will only remove tracking - the actual cluster will not be affected.`)) {
      try {
        await deleteCluster.mutateAsync(id)
      } catch (error) {
        // Error is handled by the mutation
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Clusters</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your OCP clusters and their kubeconfigs
          </p>
        </div>
        <div className="flex gap-3">
          <button onClick={() => refetch()} className="btn-secondary">
            <ArrowPathIcon className="h-4 w-4 mr-2" />
            Refresh
          </button>
          <button onClick={() => setIsAddOpen(true)} className="btn-primary">
            <PlusIcon className="h-4 w-4 mr-2" />
            Add Cluster
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="card p-12 text-center">
          <ArrowPathIcon className="h-8 w-8 animate-spin mx-auto text-gray-400" />
          <p className="mt-2 text-gray-500">Loading clusters...</p>
        </div>
      ) : clusters.length === 0 ? (
        <div className="card p-12 text-center">
          <ServerStackIcon className="h-16 w-16 mx-auto text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">No clusters configured</h3>
          <p className="mt-2 text-gray-500">
            Get started by adding your first cluster with its kubeconfig or credentials.
          </p>
          <button onClick={() => setIsAddOpen(true)} className="mt-6 btn-primary">
            <PlusIcon className="h-4 w-4 mr-2" />
            Add Cluster
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
          {clusters.map((cluster) => (
            <div key={cluster.id} className="card hover:shadow-md transition-shadow">
              <div className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`h-12 w-12 rounded-xl flex items-center justify-center ${
                        cluster.status === 'healthy'
                          ? 'bg-green-100'
                          : cluster.status === 'error'
                          ? 'bg-red-100'
                          : 'bg-yellow-100'
                      }`}
                    >
                      <ServerStackIcon
                        className={`h-6 w-6 ${
                          cluster.status === 'healthy'
                            ? 'text-green-600'
                            : cluster.status === 'error'
                            ? 'text-red-600'
                            : 'text-yellow-600'
                        }`}
                      />
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900">{cluster.name}</h3>
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
                </div>

                {cluster.description && (
                  <p className="mt-4 text-sm text-gray-500 line-clamp-2">{cluster.description}</p>
                )}

                <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-gray-500">Nodes</p>
                    <p className="font-semibold text-gray-900">{cluster.node_count || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">GPUs (used / total)</p>
                    <p className="font-semibold text-gray-900">
                      {gpuStatusByCluster[cluster.id]
                        ? `${gpuStatusByCluster[cluster.id]!.allocated_gpus} / ${gpuStatusByCluster[cluster.id]!.total_gpus}`
                        : `– / ${cluster.gpu_count || '0'}`}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-500">Version</p>
                    <p className="font-semibold text-gray-900 truncate">
                      {cluster.cluster_version || 'N/A'}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-500">Last Check</p>
                    <p className="font-semibold text-gray-900">
                      {cluster.last_health_check
                        ? format(new Date(cluster.last_health_check), 'MMM d, HH:mm')
                        : 'Never'}
                    </p>
                  </div>
                </div>

                {cluster.api_server_url && (
                  <div className="mt-4 pt-4 border-t border-gray-100">
                    <p className="text-xs text-gray-500">API Server</p>
                    <p className="text-sm text-gray-700 font-mono truncate">
                      {cluster.api_server_url}
                    </p>
                  </div>
                )}
              </div>

              <div className="px-6 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                <Link
                  to={`/clusters/${cluster.id}`}
                  className="text-sm font-medium text-primary-600 hover:text-primary-700 flex items-center gap-1"
                >
                  <EyeIcon className="h-4 w-4" />
                  View Details
                </Link>
                <button
                  onClick={() => handleRemove(cluster.id, cluster.name)}
                  disabled={deleteCluster.isPending}
                  className="text-sm font-medium text-red-600 hover:text-red-700 flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <TrashIcon className="h-4 w-4" />
                  {deleteCluster.isPending ? 'Removing...' : 'Remove'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Transition appear show={isAddOpen} as={Fragment}>
        <Dialog as="div" className="relative z-50" onClose={() => setIsAddOpen(false)}>
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-300"
            enterFrom="opacity-0"
            enterTo="opacity-100"
            leave="ease-in duration-200"
            leaveFrom="opacity-100"
            leaveTo="opacity-0"
          >
            <div className="fixed inset-0 bg-black/30 backdrop-blur-sm" />
          </Transition.Child>

          <div className="fixed inset-0 overflow-y-auto">
            <div className="flex min-h-full items-center justify-center p-4">
              <Transition.Child
                as={Fragment}
                enter="ease-out duration-300"
                enterFrom="opacity-0 scale-95"
                enterTo="opacity-100 scale-100"
                leave="ease-in duration-200"
                leaveFrom="opacity-100 scale-100"
                leaveTo="opacity-0 scale-95"
              >
                <Dialog.Panel className="w-full max-w-lg transform overflow-hidden rounded-2xl bg-white p-6 shadow-xl transition-all">
                  <Dialog.Title as="h3" className="text-lg font-semibold text-gray-900">
                    Add New Cluster
                  </Dialog.Title>

                  <div className="mt-6 space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700">
                        Cluster Name *
                      </label>
                      <input
                        type="text"
                        value={newCluster.name}
                        onChange={(e) => setNewCluster((prev) => ({ ...prev, name: e.target.value }))}
                        className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                        placeholder="e.g., production-gpu-cluster"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700">
                        Description
                      </label>
                      <textarea
                        value={newCluster.description}
                        onChange={(e) =>
                          setNewCluster((prev) => ({ ...prev, description: e.target.value }))
                        }
                        rows={2}
                        className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                        placeholder="Optional description for this cluster"
                      />
                    </div>

                    <Tab.Group onChange={(index) => setAuthMethod(index === 0 ? 'kubeconfig' : 'credentials')}>
                      <Tab.List className="flex space-x-1 rounded-xl bg-gray-100 p-1">
                        <Tab
                          className={({ selected }) =>
                            clsx(
                              'w-full rounded-lg py-2.5 text-sm font-medium leading-5 transition-colors',
                              'focus:outline-none',
                              selected
                                ? 'bg-white text-primary-700 shadow'
                                : 'text-gray-600 hover:bg-white/50 hover:text-gray-800'
                            )
                          }
                        >
                          <div className="flex items-center justify-center gap-2">
                            <CloudArrowUpIcon className="h-4 w-4" />
                            Kubeconfig File
                          </div>
                        </Tab>
                        <Tab
                          className={({ selected }) =>
                            clsx(
                              'w-full rounded-lg py-2.5 text-sm font-medium leading-5 transition-colors',
                              'focus:outline-none',
                              selected
                                ? 'bg-white text-primary-700 shadow'
                                : 'text-gray-600 hover:bg-white/50 hover:text-gray-800'
                            )
                          }
                        >
                          <div className="flex items-center justify-center gap-2">
                            <KeyIcon className="h-4 w-4" />
                            Kubeadmin Login
                          </div>
                        </Tab>
                      </Tab.List>
                      <Tab.Panels className="mt-4">
                        <Tab.Panel>
                          <div
                            {...getRootProps()}
                            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                              isDragActive
                                ? 'border-primary-500 bg-primary-50'
                                : kubeconfigFile
                                ? 'border-green-500 bg-green-50'
                                : 'border-gray-300 hover:border-gray-400'
                            }`}
                          >
                            <input {...getInputProps()} />
                            <CloudArrowUpIcon
                              className={`h-10 w-10 mx-auto ${
                                kubeconfigFile ? 'text-green-500' : 'text-gray-400'
                              }`}
                            />
                            {kubeconfigFile ? (
                              <p className="mt-2 text-sm text-green-700 font-medium">
                                {kubeconfigFile.name}
                              </p>
                            ) : (
                              <>
                                <p className="mt-2 text-sm text-gray-600">
                                  Drop your kubeconfig file here, or click to browse
                                </p>
                                <p className="mt-1 text-xs text-gray-500">
                                  Supports .yaml, .yml, and .kubeconfig files
                                </p>
                              </>
                            )}
                          </div>
                        </Tab.Panel>
                        <Tab.Panel className="space-y-4">
                          <div>
                            <label className="block text-sm font-medium text-gray-700">
                              API Server URL *
                            </label>
                            <input
                              type="text"
                              value={newCluster.apiServer}
                              onChange={(e) =>
                                setNewCluster((prev) => ({ ...prev, apiServer: e.target.value }))
                              }
                              className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                              placeholder="https://api.cluster.example.com:6443"
                            />
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700">
                              Username *
                            </label>
                            <input
                              type="text"
                              value={newCluster.username}
                              onChange={(e) =>
                                setNewCluster((prev) => ({ ...prev, username: e.target.value }))
                              }
                              className="mt-1 block w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                              placeholder="kubeadmin"
                            />
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700">
                              Password *
                            </label>
                            <div className="relative mt-1">
                              <input
                                type={showPassword ? 'text' : 'password'}
                                value={newCluster.password}
                                onChange={(e) =>
                                  setNewCluster((prev) => ({ ...prev, password: e.target.value }))
                                }
                                className="block w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 pr-10"
                                placeholder="Enter kubeadmin password"
                              />
                              <button
                                type="button"
                                onClick={() => setShowPassword(!showPassword)}
                                className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                              >
                                {showPassword ? (
                                  <EyeSlashIcon className="h-5 w-5" />
                                ) : (
                                  <EyeIcon className="h-5 w-5" />
                                )}
                              </button>
                            </div>
                          </div>
                          <p className="text-xs text-gray-500">
                            Credentials are used to authenticate with the OpenShift OAuth server
                            and generate an access token. The password is not stored.
                          </p>
                        </Tab.Panel>
                      </Tab.Panels>
                    </Tab.Group>
                  </div>

                  <div className="mt-6 flex justify-end gap-3">
                    <button
                      onClick={() => {
                        setIsAddOpen(false)
                        resetForm()
                      }}
                      className="btn-secondary"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleCreate}
                      disabled={createCluster.isPending}
                      className="btn-primary"
                    >
                      {createCluster.isPending ? 'Creating...' : 'Add Cluster'}
                    </button>
                  </div>
                </Dialog.Panel>
              </Transition.Child>
            </div>
          </div>
        </Dialog>
      </Transition>
    </div>
  )
}
