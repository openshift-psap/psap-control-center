import { Fragment, useState, useEffect, useCallback } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { Dialog, Transition } from '@headlessui/react'
import {
  Bars3Icon,
  HomeIcon,
  ServerStackIcon,
  CalendarDaysIcon,
  ClipboardDocumentListIcon,
  BeakerIcon,
  ChartBarIcon,
  LockClosedIcon,
  LockOpenIcon,
  FireIcon,
} from '@heroicons/react/24/outline'
import clsx from 'clsx'
import LoginModal from './LoginModal'
import HearthConnectModal from './HearthConnectModal'
import { isAuthenticated, getSession, clearSession } from '../stores/authStore'
import { authApi } from '../services/api'
import { useHearthStatus, useDisconnectHearth } from '../hooks/useHearth'

const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: HomeIcon },
  { name: 'Clusters', href: '/clusters', icon: ServerStackIcon },
  { name: 'Reservations', href: '/reservations', icon: ClipboardDocumentListIcon },
  { name: 'Calendar', href: '/calendar', icon: CalendarDaysIcon },
  { name: 'Testing', href: '/testing', icon: BeakerIcon, comingSoon: true },
  { name: 'Results', href: '/results', icon: ChartBarIcon, comingSoon: true },
]

function HearthIndicator({
  onConnectClick,
}: {
  onConnectClick: () => void
}) {
  const { data: hearthStatus } = useHearthStatus()
  const disconnectHearth = useDisconnectHearth()

  const available = hearthStatus?.available ?? false
  const configured = hearthStatus?.configured ?? false

  if (!configured) {
    return (
      <button
        onClick={onConnectClick}
        className="w-full rounded-xl border border-dashed border-gray-300 p-3 hover:border-orange-400 hover:bg-orange-50 transition-colors group"
      >
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-gray-100 group-hover:bg-orange-100 flex items-center justify-center transition-colors">
            <FireIcon className="h-4 w-4 text-gray-400 group-hover:text-orange-500 transition-colors" />
          </div>
          <div className="text-left">
            <p className="text-xs font-semibold text-gray-600 group-hover:text-orange-700">Connect Hearth</p>
            <p className="text-[10px] text-gray-400">GPU cluster operator</p>
          </div>
        </div>
      </button>
    )
  }

  return (
    <div className={clsx(
      'rounded-xl p-3 border',
      available
        ? 'bg-gradient-to-br from-orange-50 to-amber-50 border-orange-200'
        : 'bg-gradient-to-br from-red-50 to-orange-50 border-red-200'
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className={clsx(
            'h-8 w-8 rounded-lg flex items-center justify-center',
            available ? 'bg-orange-100' : 'bg-red-100'
          )}>
            <FireIcon className={clsx(
              'h-4 w-4',
              available ? 'text-orange-600' : 'text-red-500'
            )} />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-semibold text-gray-700">Hearth</p>
              <span className="relative flex h-2 w-2">
                {available && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                )}
                <span className={clsx(
                  'relative inline-flex rounded-full h-2 w-2',
                  available ? 'bg-green-500' : 'bg-red-400'
                )} />
              </span>
            </div>
            <p className="text-[10px] text-gray-500">
              {available
                ? `${hearthStatus?.cluster_count || 0} clusters · ${hearthStatus?.total_gpus || 0} GPUs`
                : 'Connection error'}
            </p>
          </div>
        </div>
        <button
          onClick={() => disconnectHearth.mutate()}
          disabled={disconnectHearth.isPending}
          className="text-[10px] text-gray-400 hover:text-red-600 transition-colors px-1.5 py-0.5 rounded hover:bg-white/60"
          title="Disconnect Hearth"
        >
          {disconnectHearth.isPending ? '...' : 'Disconnect'}
        </button>
      </div>
    </div>
  )
}

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [hearthConnectOpen, setHearthConnectOpen] = useState(false)
  const [authed, setAuthed] = useState(isAuthenticated())
  const location = useLocation()

  const { data: hearthStatus } = useHearthStatus()

  const syncAuth = useCallback(() => setAuthed(isAuthenticated()), [])

  useEffect(() => {
    window.addEventListener('auth-change', syncAuth)
    return () => window.removeEventListener('auth-change', syncAuth)
  }, [syncAuth])

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {
      // clear locally even if the server call fails
    }
    clearSession()
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Transition.Root show={sidebarOpen} as={Fragment}>
        <Dialog as="div" className="relative z-50 lg:hidden" onClose={setSidebarOpen}>
          <Transition.Child
            as={Fragment}
            enter="transition-opacity ease-linear duration-300"
            enterFrom="opacity-0"
            enterTo="opacity-100"
            leave="transition-opacity ease-linear duration-300"
            leaveFrom="opacity-100"
            leaveTo="opacity-0"
          >
            <div className="fixed inset-0 bg-gray-900/80" />
          </Transition.Child>

          <div className="fixed inset-0 flex">
            <Transition.Child
              as={Fragment}
              enter="transition ease-in-out duration-300 transform"
              enterFrom="-translate-x-full"
              enterTo="translate-x-0"
              leave="transition ease-in-out duration-300 transform"
              leaveFrom="translate-x-0"
              leaveTo="-translate-x-full"
            >
              <Dialog.Panel className="relative mr-16 flex w-full max-w-xs flex-1">
                <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white px-6 pb-4">
                  <div className="flex h-16 shrink-0 items-center">
                    <div className="flex items-center gap-2">
                      <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-primary-600 to-primary-700 flex items-center justify-center">
                        <span className="text-white font-bold text-sm">P</span>
                      </div>
                      <span className="text-xl font-bold text-gray-900">PSAP Control Center</span>
                    </div>
                  </div>
                  <nav className="flex flex-1 flex-col">
                    <ul className="flex flex-1 flex-col gap-y-1">
                      {navigation.map((item) => (
                        <li key={item.name}>
                          <NavLink
                            to={item.href}
                            onClick={() => setSidebarOpen(false)}
                            className={({ isActive }) =>
                              clsx(
                                'group flex gap-x-3 rounded-lg p-3 text-sm font-medium transition-colors',
                                isActive
                                  ? 'bg-primary-50 text-primary-700'
                                  : 'text-gray-700 hover:bg-gray-50 hover:text-primary-600'
                              )
                            }
                          >
                            <item.icon className="h-5 w-5 shrink-0" />
                            {item.name}
                            {item.comingSoon && (
                              <span className="ml-auto text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                                Soon
                              </span>
                            )}
                          </NavLink>
                        </li>
                      ))}
                    </ul>
                  </nav>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </Dialog>
      </Transition.Root>

      <div className="hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-72 lg:flex-col">
        <div className="flex grow flex-col gap-y-5 overflow-y-auto border-r border-gray-200 bg-white px-6 pb-4">
          <div className="flex h-16 shrink-0 items-center">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-primary-600 to-primary-700 flex items-center justify-center shadow-lg shadow-primary-500/20">
                <span className="text-white font-bold text-lg">P</span>
              </div>
              <div>
                <h1 className="text-lg font-bold text-gray-900">PSAP Control Center</h1>
                <p className="text-xs text-gray-500">Cluster Management</p>
              </div>
            </div>
          </div>
          <nav className="flex flex-1 flex-col">
            <ul className="flex flex-1 flex-col gap-y-1">
              {navigation.map((item) => (
                <li key={item.name}>
                  <NavLink
                    to={item.href}
                    className={({ isActive }) =>
                      clsx(
                        'group flex gap-x-3 rounded-lg p-3 text-sm font-medium transition-all duration-200',
                        isActive
                          ? 'bg-primary-50 text-primary-700 shadow-sm'
                          : 'text-gray-700 hover:bg-gray-50 hover:text-primary-600'
                      )
                    }
                  >
                    <item.icon
                      className={clsx(
                        'h-5 w-5 shrink-0 transition-colors',
                        location.pathname.startsWith(item.href) ? 'text-primary-600' : 'text-gray-400 group-hover:text-primary-500'
                      )}
                    />
                    {item.name}
                    {item.comingSoon && (
                      <span className="ml-auto text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                        Soon
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>

            <div className="mt-auto pt-4 border-t border-gray-200 space-y-3">
              <HearthIndicator onConnectClick={() => setHearthConnectOpen(true)} />
              <div className="rounded-xl bg-gradient-to-br from-gray-50 to-gray-100 p-4">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Organization</p>
                <p className="mt-1 text-sm font-semibold text-gray-900">OpenShift PSAP</p>
                <p className="text-xs text-gray-500">Performance & Scale for AI Platforms</p>
              </div>
            </div>
          </nav>
        </div>
      </div>

      <div className="lg:pl-72">
        <div className="sticky top-0 z-40 flex h-16 shrink-0 items-center gap-x-4 border-b border-gray-200 bg-white/80 backdrop-blur-sm px-4 shadow-sm sm:gap-x-6 sm:px-6 lg:px-8">
          <button
            type="button"
            className="-m-2.5 p-2.5 text-gray-700 lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <span className="sr-only">Open sidebar</span>
            <Bars3Icon className="h-6 w-6" />
          </button>

          <div className="flex flex-1 gap-x-4 self-stretch lg:gap-x-6">
            <div className="flex flex-1" />
            <div className="flex items-center gap-x-4 lg:gap-x-6">
              {/* Hearth connection badge in header */}
              <button
                onClick={() => !hearthStatus?.configured && setHearthConnectOpen(true)}
                className={clsx(
                  'hidden sm:flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
                  hearthStatus?.available
                    ? 'bg-orange-50 text-orange-700 border border-orange-200'
                    : hearthStatus?.configured
                    ? 'bg-red-50 text-red-600 border border-red-200'
                    : 'bg-gray-100 text-gray-500 border border-gray-200 hover:border-orange-300 hover:text-orange-600 cursor-pointer'
                )}
                title={
                  hearthStatus?.available
                    ? `Hearth: ${hearthStatus.cluster_count} clusters, ${hearthStatus.total_gpus} GPUs`
                    : hearthStatus?.configured
                    ? `Hearth: ${hearthStatus?.error || 'Connection error'}`
                    : 'Click to connect Hearth'
                }
              >
                <FireIcon className="h-3.5 w-3.5" />
                <span className="relative flex h-1.5 w-1.5">
                  <span className={clsx(
                    'relative inline-flex rounded-full h-1.5 w-1.5',
                    hearthStatus?.available ? 'bg-green-500' : hearthStatus?.configured ? 'bg-red-400' : 'bg-gray-400'
                  )} />
                </span>
              </button>
              <div className="hidden lg:block lg:h-6 lg:w-px lg:bg-gray-200" />
              {authed ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1.5 text-sm text-gray-600">
                    <LockClosedIcon className="h-4 w-4 text-green-500" />
                    <span className="hidden sm:inline font-medium">{getSession()?.username}</span>
                  </span>
                  <button
                    onClick={handleLogout}
                    className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                  >
                    Sign Out
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setLoginOpen(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-500 shadow-sm transition-colors"
                >
                  <LockOpenIcon className="h-4 w-4" />
                  Sign In
                </button>
              )}
            </div>
          </div>
        </div>

        <main className="py-6 px-4 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>

      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
      <HearthConnectModal open={hearthConnectOpen} onClose={() => setHearthConnectOpen(false)} />
    </div>
  )
}
