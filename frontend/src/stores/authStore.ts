import { createLogger } from '../utils/logger'

const logger = createLogger('AuthStore')

export type UserRole = 'admin' | 'user'

export interface AuthSession {
  username: string
  role: UserRole
  email?: string | null
  name?: string | null
  auth_provider?: 'local' | 'google' | string
}

// An existing session cookie can be in use before /auth/me returns.
let session: AuthSession | null | undefined

export function getSession(): AuthSession | null {
  return session ?? null
}

export function isAuthenticated(): boolean {
  return session != null
}

export function isAdmin(): boolean {
  return session?.role === 'admin'
}

export function getUsername(): string | null {
  return session?.username ?? null
}

export function getPreferenceAccount(): string | null {
  return session ? `${session.auth_provider || 'local'}:${session.username}` : null
}

export function getViewerCacheKey(): string | null {
  return session === undefined ? 'session-pending' : getPreferenceAccount()
}

export function getDisplayName(): string | null {
  return session?.name || session?.email || session?.username || null
}

export function getRole(): UserRole | null {
  return session?.role ?? null
}

export function setSession(user: AuthSession): void {
  session = user
  logger.info('User authenticated:', user.username, `(${user.role})`)
  window.dispatchEvent(new Event('auth-change'))
}

export function clearSession(): void {
  session = null
  logger.info('User logged out')
  window.dispatchEvent(new Event('auth-change'))
}
