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

/* Remembered checkout details.
   These are the student's own phone number and the campus' single delivery
   point — re-typing a 10-digit mobile on every visit is the single most
   annoying part of ordering, and it is what made people leave orders unpaid
   halfway. They live OUTSIDE the session key on purpose: clearLocalSession()
   logs the student out (and empties the cart), but the next person at the same
   kiosk should not have to re-enter a phone number to pay. Nothing sensitive
   beyond a phone number and a fixed gate, and it never leaves localStorage. */
const DEVICE_KEY = 'detomsite-checkout-profile'

export interface CheckoutProfile {
  phone?: string
  location?: string
}

export function getCheckoutProfile(): CheckoutProfile {
  try {
    const raw = localStorage.getItem(DEVICE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as CheckoutProfile
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function rememberCheckout(patch: CheckoutProfile) {
  try {
    const next = { ...getCheckoutProfile(), ...patch }
    // Only keep a plausible mobile / a non-empty location, so a bad value is
    // never persisted and then echoed back into an order.
    if (next.phone && !/^\+?[0-9]{10,15}$/.test(next.phone.replace(/\s/g, ''))) delete next.phone
    if (next.location && next.location.length > 300) delete next.location
    localStorage.setItem(DEVICE_KEY, JSON.stringify(next))
  } catch {
    /* private mode / quota — remembering is a nicety, never a blocker */
  }
}

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
