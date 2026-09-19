/* Enhanced session management with auto-login support */

export type UserRoleChoice = 'student' | 'shopkeeper' | 'admin'

export interface LocalSession {
  role: UserRoleChoice
  email: string
  name: string
  phone?: string
  campus?: string
  default_delivery_location?: string
  shop_name?: string
  shop_category?: string
  loggedInAt?: string
}

const SESSION_KEY = 'detomsite-session'

export function getLocalSession(): LocalSession | null {
  try {
    const rawSession = localStorage.getItem(SESSION_KEY)
    if (!rawSession || !localStorage.getItem('access_token')) return null
    const session = JSON.parse(rawSession) as LocalSession
    // Validate required fields
    if (!session.role || !session.email) return null
    return session
  } catch {
    return null
  }
}

export function saveLocalSession(session: LocalSession) {
  const enriched = {
    ...session,
    loggedInAt: new Date().toISOString(),
  }
  localStorage.setItem(SESSION_KEY, JSON.stringify(enriched))
  window.dispatchEvent(new Event('detomsite-session-changed'))
}

export function clearLocalSession() {
  for (const key of [SESSION_KEY, 'access_token', 'refresh_token', 'detomsite-cart']) {
    localStorage.removeItem(key)
  }
  sessionStorage.removeItem('payment_pending')
  window.dispatchEvent(new Event('detomsite-session-changed'))
  window.dispatchEvent(new Event('detomsite-cart-updated'))
}

export function isSessionValid(): boolean {
  const session = getLocalSession()
  return session !== null && !!session.email && !!session.role
}

export function getDashboardPath(role: UserRoleChoice): string {
  switch (role) {
    // Students land on the SHOP list first (discovery), not a dashboard.
    case 'student': return '/shops'
    case 'shopkeeper': return '/shopkeeper-dashboard'
    case 'admin': return '/admin-dashboard'
    default: return '/'
  }
}
