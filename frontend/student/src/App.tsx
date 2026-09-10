import { useState, useEffect, FormEvent, useMemo, useCallback, useRef } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, Navigate, useNavigate, useSearchParams, useParams, useLocation } from 'react-router-dom'
import api from './services/api'
import { QRCodeSVG } from 'qrcode.react'

/* ─── Auth guard: blocks every protected page unless the token is valid ─── */
/* Last-validated token check. Skips the /users/profile round-trip on every
   navigation so clicking around the portal feels instant; re-validates when
   the check is 10+ minutes old or the token changes. */
const AUTH_CHECK_KEY = 'detomsite-auth-check'
function RequireAuth({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false)
  const [ok, setOk] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setChecked(true)
      setOk(false)
      return
    }
    // Validated this same token recently? Go straight in — no network call.
    try {
      const cached = JSON.parse(localStorage.getItem(AUTH_CHECK_KEY) || 'null')
      if (cached && cached.token === token && Date.now() - cached.t < 10 * 60 * 1000) {
        setChecked(true)
        setOk(true)
        return
      }
    } catch { /* fall through to the real check */ }
    // Validate the token against the backend — a stale/leftover token fails here
    api.get('/users/profile')
      .then(() => {
        try { localStorage.setItem(AUTH_CHECK_KEY, JSON.stringify({ token, t: Date.now() })) } catch { /* ignore */ }
        setChecked(true); setOk(true)
      })
      .catch(() => {
        localStorage.removeItem('access_token')
        localStorage.removeItem('user_data')
        localStorage.removeItem(AUTH_CHECK_KEY)
        setChecked(true)
        setOk(false)
      })
  }, [])

  if (!checked) {
    return <div className="flex min-h-screen items-center justify-center bg-gray-50 text-sm font-medium text-gray-400">Loading...</div>
  }
  if (!ok) return <Navigate to="/login" replace />
  return <>{children}</>
}

/* ─── Types ─── */
interface Shop { id: string; name: string; category: string; description: string; rating: number; opening_time: string; closing_time: string; present: number; status: string; approval_status: string; shopkeeper_email: string; shopkeeper_name: string; phone: string; upi_id: string; upi_enabled: number; cod_enabled: number; orders_today: number; revenue_today: number; current_token: number }
interface Product { id: string; shop_id: string; name: string; description: string; price: number; pending_price: number | null; category: string; inventory: number; prep_time: number; available: number }
interface Order { id: string; token: number; student_name: string; student_phone: string; shop_id: string; shop_name: string; items: string; total: number; delivery_location: string; delivery_slot: string; status: string; payment_method?: string; created_at: string }
interface Payment { id: string; order_id: string; amount: number; method: string; status: string; utr_number: string | null; screenshot_name: string | null; created_at: string }
interface CartItem { product_id: string; shop_id: string; shop_name: string; name: string; price: number; quantity: number; category: string }
interface Notification { id: string; title: string; message: string; order_id: string | null; status: string | null; is_read: number; created_at: string }
interface PaymentSettings { manual_enabled: boolean; upi_id: string; receiver_name: string; instructions: string }

/* ─── Helpers ─── */
const CART_KEY = 'detomsite-cart'
function getCart(): CartItem[] { try { return JSON.parse(localStorage.getItem(CART_KEY) || '[]') } catch { return [] } }
function saveCart(items: CartItem[]) { localStorage.setItem(CART_KEY, JSON.stringify(items)); window.dispatchEvent(new Event('cart-updated')) }
function clearCart() { saveCart([]) }

/* UPI transaction limit — Indian banks cap UPI at ₹1,00,000 per transaction.
   Above that the bank rejects the payment (money is NOT debited) with the
   "exceeded the bank limit … retry with a smaller amount" error. We warn the
   student before they ever see that confusing failure. */
const UPI_LIMIT = 100000

/* Client-side cache for the shops list (60s TTL) so the dashboard and shops
   pages render instantly instead of waiting on the network every click. */
const SHOPS_CACHE_KEY = 'detomsite-shops-cache'
function cachedShops(): Shop[] | null {
  try {
    const raw = localStorage.getItem(SHOPS_CACHE_KEY)
    if (!raw) return null
    const { t, data } = JSON.parse(raw)
    if (Date.now() - t > 60000) return null
    return data
  } catch { return null }
}
function fetchShopsCached() {
  const hit = cachedShops()
  if (hit) return Promise.resolve(hit)
  return api.get<Shop[]>('/local/shops', { params: { public_only: true } })
    .then(r => { try { localStorage.setItem(SHOPS_CACHE_KEY, JSON.stringify({ t: Date.now(), data: r.data })) } catch { /* storage full — ignore */ } return r.data })
    .catch(() => cachedShops() || [])
}

/* Same idea for the user's order list — a 30s TTL keeps the dashboard and the
   orders page snappy without going stale mid-session. */
const ORDERS_CACHE_KEY = 'detomsite-orders-cache'
function cachedOrders(): Order[] | null {
  try {
    const raw = localStorage.getItem(ORDERS_CACHE_KEY)
    if (!raw) return null
    const { t, data } = JSON.parse(raw)
    if (Date.now() - t > 30000) return null
    return data
  } catch { return null }
}
function fetchOrdersCached() {
  const hit = cachedOrders()
  if (hit) return Promise.resolve(hit)
  return api.get<Order[]>('/local/orders')
    .then(r => { try { localStorage.setItem(ORDERS_CACHE_KEY, JSON.stringify({ t: Date.now(), data: r.data })) } catch { /* ignore */ } return r.data })
    .catch(() => cachedOrders() || [])
}
/* Drop the cached orders list — call after an order changes (e.g. a student
   cancels an order) so the next view always shows the fresh state. */
function invalidateOrdersCache() { try { localStorage.removeItem(ORDERS_CACHE_KEY) } catch { /* ignore */ } }

/* ─── Inline SVG icons (no emoji, no icon library — tiny & consistent) ─── */
type IconProps = { className?: string }
const iconSvg = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, viewBox: '0 0 24 24' }
const Icon = {
  home: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1v-9.5Z" /></svg>,
  store: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M4 10v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V10M3 6l1.2-3h15.6L21 6a2.4 2.4 0 0 1-4.8 0 2.4 2.4 0 0 1-4.8 0A2.4 2.4 0 0 1 6.6 6 2.4 2.4 0 0 1 3 6Z" /><path d="M9 21v-6h6v6" /></svg>,
  package: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" /><path d="M3 8l9 5 9-5M12 13v8" /></svg>,
  cart: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><circle cx="9" cy="20" r="1.5" /><circle cx="17" cy="20" r="1.5" /><path d="M3 3h2l2.6 12.4a1 1 0 0 0 1 .8h7.9a1 1 0 0 0 1-.8L20 8H6" /></svg>,
  star: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="m12 3 2.7 5.6 6.1.8-4.5 4.3 1.1 6-5.4-2.9-5.4 2.9 1.1-6L3.2 9.4l6.1-.8L12 3Z" /></svg>,
  user: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" /></svg>,
  support: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3" /></svg>,
  bell: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" /><path d="M10 20a2.2 2.2 0 0 0 4 0" /></svg>,
  phone: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>,
  lock: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>,
  graduation: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="m2 9 10-5 10 5-10 5L2 9Z" /><path d="M6 11.5V16c0 1.5 2.7 3 6 3s6-1.5 6-3v-4.5M22 9v5" /></svg>,
  search: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>,
  alert: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17.5v.5" /></svg>,
  mapPin: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" /></svg>,
  check: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="m4 12.5 5 5L20 6.5" /></svg>,
  chevronRight: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="m9 6 6 6-6 6" /></svg>,
  card: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M2 10h20" /></svg>,
  cash: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><rect x="2" y="6" width="20" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /><path d="M6 12h.01M18 12h.01" /></svg>,
  eye: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>,
  eyeOff: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><path d="m1 1 22 22" /></svg>,
  sun: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>,
  moon: (p: IconProps) => <svg {...iconSvg} className={p.className || 'h-4 w-4'}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>,
}
const IconH = { user: Icon.user, lock: Icon.lock, graduation: Icon.graduation, bell: Icon.bell, cart: Icon.cart, store: Icon.store, package: Icon.package, home: Icon.home, star: Icon.star, support: Icon.support, search: Icon.search, alert: Icon.alert, phone: Icon.phone, mapPin: Icon.mapPin, check: Icon.check, chevronRight: Icon.chevronRight, card: Icon.card, cash: Icon.cash, eye: Icon.eye, eyeOff: Icon.eyeOff, sun: Icon.sun, moon: Icon.moon }
function addToCart(p: Product, s: Shop) { const c = getCart(); const e = c.find(i => i.product_id === p.id); saveCart(e ? c.map(i => i.product_id === p.id ? { ...i, quantity: i.quantity + 1 } : i) : [...c, { product_id: p.id, shop_id: s.id, shop_name: s.name, name: p.name, price: p.price, quantity: 1, category: p.category }]) }
function updateQty(pid: string, q: number) { const c = getCart(); saveCart(q <= 0 ? c.filter(i => i.product_id !== pid) : c.map(i => i.product_id === pid ? { ...i, quantity: q } : i)) }
function billBreakdown(items: CartItem[]) { const total = items.reduce((a, i) => a + i.price * i.quantity, 0); return { subtotal: total, tax: 0, platformFee: 0, delivery: 0, total: total } }
/* UPI amounts MUST be clean numbers with at most 2 decimal places. Raw float
   totals (e.g. 99.5 * 3 = 298.50000000000006 from decimal product prices)
   make banks reject the payment — often with a confusing "exceeded bank
   limit" message — while the same order via QR (no amount) goes through fine.
   Round before putting the amount into the upi:// URI. */
function upiAmount(am: number) { const n = Number(am); return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0 }
/* Build a spec-compliant UPI deep link. am always uses exactly 2 decimal
   places (e.g. 100.00) like the links PhonePe/GPay generate; pa and
   pn are trimmed (a stray space silently breaks VPA resolution); and mode=04
   marks this as a standard UPI Collect request so the bank routes it exactly
   like a scanned QR. */
function buildUpiUri(pa: string, pn: string, am: number, tn: string, tr?: string) {
  const payee = String(pa || '').trim()
  const name = String(pn || '').trim()
  const note = String(tn || '').trim()
  const ref = (tr || '').trim() ? `&tr=${encodeURIComponent(String(tr).trim())}` : ''
  return `upi://pay?pa=${encodeURIComponent(payee)}&pn=${encodeURIComponent(name)}&am=${upiAmount(am).toFixed(2)}&cu=INR&mode=04&tn=${encodeURIComponent(note)}${ref}`
}
/* One-tap delivery-location presets shown on the checkout page. Students can
   still type any custom location, but these cover the spots they actually
   order to every day. Edit this list to match your campus's nearby spots. */
const QUICK_LOCATIONS = ['VIT AP Campus', 'Inavolu', 'Amravati', 'Guntur']

  /* Indian mobile input — the user types their 10-digit number; the value is
     stored with the +91 country code (E.164) so the backend receives +91 + number. */
  function isValidMobile(v: string) { const d = v.replace(/\D/g, ''); return d.length === 10 || (d.length === 12 && d.startsWith('91')) }
  function toE164(v: string) {
    let d = v.replace(/\D/g, '')
    if (d.length > 10 && d.startsWith('91')) d = d.slice(2)   // drop a pasted country code
    d = d.slice(-10)
    return d ? `+91${d}` : ''
  }
  /* Show only the user's 10 digits — never the +91 prefix. The stored value is
     E.164 ("+919…"), so strip the prefix back off before echoing it into the
     field, otherwise the 91 leaks into the display on every keystroke. */
  function displayDigits(v: string) {
    let d = v.replace(/\D/g, '')
    const raw = String(v || '')
    if (d.startsWith('91') && (raw.startsWith('+91') || d.length > 10)) d = d.slice(2)
    return d.slice(-10)
  }
  function PhoneField({ value, onChange, placeholder = '98765 43210' }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
    const digits = displayDigits(value)
    // No maxLength — a browser would truncate a pasted "+91…" number before
    // toE164 can strip the country code. toE164 clamps to the last 10 digits.
    return (
      <input type="tel" inputMode="numeric" autoComplete="off" value={digits} required
        onChange={e => onChange(toE164(e.target.value))}
        placeholder={placeholder}
        className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary-light/200" />
    )
  }
  /* Password input with a show/hide toggle — every login/signup form uses it. */
  function PasswordField({ value, onChange, placeholder = '••••••', autoComplete, required = true, className = '' }: { value: string; onChange: (v: string) => void; placeholder?: string; autoComplete?: string; required?: boolean; className?: string }) {
    const [show, setShow] = useState(false)
    return (
      <div className="relative">
        <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)}
          placeholder={placeholder} autoComplete={autoComplete} required={required}
          className={`w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 pr-11 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary-light/200 focus:shadow-card ${className}`} />
        <button type="button" onClick={() => setShow(!show)} tabIndex={-1} aria-label={show ? 'Hide password' : 'Show password'}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-sm p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-primary">
          {show ? IconH.eyeOff({ className: 'h-5 w-5' }) : IconH.eye({ className: 'h-5 w-5' })}
        </button>
      </div>
    )
  }

/* Mirrors the backend's orderability check (approved + present + open). The
   vendor's Start/Stop toggle is the source of truth — shop hours are shown to
   students as information only and do not block ordering.
   NOTE: use Boolean(present) — Supabase returns present as true/false while
   SQLite returned 1/0, so a strict `=== 1` check would always be false. */
/* The vendor's Start/Stop toggle is the single source of truth for whether a
   shop accepts orders — once started it stays open until the vendor stops it.
   Opening/closing hours are shown to students as information only and do NOT
   block ordering. NOTE: use Boolean(present) — Supabase returns present as
   true/false while SQLite returned 1/0, so a strict `=== 1` check would always
   be false. */
function isShopOrderable(s: Shop) {
  return s.approval_status === 'Approved' && Boolean(s.present) && s.status === 'Open'
}
function shopStatusReason(s: Shop): string {
  if (s.approval_status !== 'Approved') return 'Waiting for admin approval'
  if (!Boolean(s.present) || s.status !== 'Open') return 'Not accepting orders right now'
  return 'Open now'
}

/* Parse a stored timestamp into a Date. SQLite stores IST wall-clock time
   without an offset; Supabase stores UTC ISO. Both become a real Date. */
function toDate(createdAt?: string): Date | null {
  const raw = String(createdAt || '').trim()
  if (!raw) return null
  let iso = raw
  if (!/T/.test(raw) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(raw)) iso = raw.replace(' ', 'T') + '+05:30'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? null : d
}
function formatPlacedAt(createdAt?: string): string {
  const d = toDate(createdAt)
  if (!d) return String(createdAt || '').slice(0, 16)
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(d)
}

/* The day is split into two delivery windows — Morning until 12:30 PM and
   Afternoon until 6:00 PM (IST). Orders placed inside a window are accepted
   automatically, and the student can cancel one until that window closes.
   Orders placed after 6:00 PM (or already completed/cancelled) are locked. */
function istClock(d: Date): { h: number; m: number } {
  const s = new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  return { h: s.getHours(), m: s.getMinutes() }
}
function canCancelOrder(o: Order | null): boolean {
  if (!o || ['Completed', 'Cancelled', 'Failed'].includes(o.status)) return false
  const placed = toDate(o.created_at)
  if (!placed) return false
  const placedMin = istClock(placed).h * 60 + istClock(placed).m
  const nowMin = istClock(new Date()).h * 60 + istClock(new Date()).m
  const cutoff = placedMin < 12 * 60 + 30 ? 12 * 60 + 30 : placedMin < 18 * 60 + 30 ? 18 * 60 + 30 : -1
  return cutoff !== -1 && nowMin < cutoff
}

/* ─── Layout ─── */
function Layout({ children }: { children: React.ReactNode }) {
  const [menu, setMenu] = useState(false)
  const [cartCount, setCartCount] = useState(getCart().reduce((s, i) => s + i.quantity, 0))
  const [notifs, setNotifs] = useState<Notification[]>([])
  const [notifOpen, setNotifOpen] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  const path = useLocation().pathname

  /* Close the notification dropdown when clicking outside it */
  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

  useEffect(() => {
    const sync = () => setCartCount(getCart().reduce((s, i) => s + i.quantity, 0))
    window.addEventListener('cart-updated', sync)
    return () => window.removeEventListener('cart-updated', sync)
  }, [])

  useEffect(() => {
    // Students only see order notifications — vendor/product alerts go to the admin.
    // Poll only while the tab is visible so a backgrounded tab stops calling the API.
    const load = () => { if (document.visibilityState === 'visible') api.get<Notification[]>('/local/notifications', { params: { role: 'student' } }).then(r => setNotifs(r.data)).catch(() => {}) }
    load(); const t = setInterval(load, 30000); return () => clearInterval(t)
  }, [])

  const logout = () => { localStorage.removeItem('access_token'); localStorage.removeItem('user_data'); window.location.href = '/login' }

  /* A nav item is active on its own page and every page below it, so
     /shop/:id lights up "Shops" and /order/:id lights up "Orders". */
  const onShops = path === '/' || path.startsWith('/shop')
  const isActive = (p: string) => (p === '/shops' && onShops) || (p !== '/dashboard' && path.startsWith(p)) || (p === '/orders' && path.startsWith('/order'))
  const nav = [
    { p: '/shops', l: 'Shops', i: IconH.store },
    { p: '/dashboard', l: 'Dashboard', i: IconH.home },
    { p: '/orders', l: 'Orders', i: IconH.package },
    { p: '/cart', l: `Cart${cartCount ? ` (${cartCount})` : ''}`, i: IconH.cart },
    { p: '/reviews', l: 'Reviews', i: IconH.star },
    { p: '/account', l: 'Account', i: IconH.user },
    { p: '/support', l: 'Support', i: IconH.support },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-lg">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link to="/shops" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-btn bg-primary text-sm font-black text-gold">D</span>
            <span className="text-lg font-black text-primary-dark max-sm:hidden">Student Portal</span>
          </Link>
          <div className="hidden items-center gap-1 md:flex">
            {nav.map(item => (
              <Link key={item.p} to={item.p} className={`flex items-center gap-1.5 rounded-pill px-3 py-2 text-sm font-semibold transition-all ${isActive(item.p) ? 'bg-primary text-white shadow-sm' : 'text-gray-600 hover:bg-primary-light/30 hover:text-primary'}`}>{item.i({ className: 'h-4 w-4' })}{item.l}</Link>
            ))}
            <div ref={notifRef} className="relative">
            <button onClick={() => setNotifOpen(!notifOpen)} className="relative rounded-pill px-2 py-2 text-sm text-gray-600 hover:bg-primary-light/30">
              {IconH.bell({ className: 'h-5 w-5' })}
              {notifs.length > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-pill bg-gold px-1 text-[10px] font-black text-white">{notifs.length}</span>}
            </button>
            {notifOpen && (
              <div className="absolute right-0 top-14 z-50 w-80 rounded-card border bg-white p-3 shadow-2xl">
                <h3 className="mb-2 px-1 text-sm font-bold text-primary">Notifications</h3>
                <div className="max-h-72 space-y-1 overflow-y-auto">
                  {notifs.map(n => (
                    <Link key={n.id} to={n.order_id ? `/order/${n.order_id}` : '/shops'} onClick={() => setNotifOpen(false)} className="block rounded-btn bg-primary-light/30 px-3 py-2.5 text-sm hover:bg-primary-light">
                      <p className="font-semibold text-primary">{n.title}</p>
                      <p className="text-xs text-gray-500">{n.message}</p>
                    </Link>
                  ))}
                  {notifs.length === 0 && <p className="px-3 py-2 text-sm text-gray-400">No notifications</p>}
                </div>
              </div>
            )}
            </div>
            {user?.name && (
              <button onClick={logout} className="ml-2 rounded-pill bg-red-50 px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-100">
                Logout
              </button>
            )}
          </div>
          <button className="rounded-pill p-2 text-gray-600 md:hidden" onClick={() => setMenu(!menu)}>{menu ? '✕' : '☰'}</button>
        </div>
        {menu && (
          <div className="border-t px-4 py-3 md:hidden">
            {nav.map(item => (
              <Link key={item.p} to={item.p} onClick={() => setMenu(false)} className={`flex items-center gap-2.5 rounded-btn px-4 py-2.5 text-sm font-semibold ${isActive(item.p) ? 'bg-primary text-white' : 'text-gray-600'}`}>{item.i({ className: 'h-4 w-4' })}{item.l}</Link>
            ))}
            <button onClick={logout} className="block w-full rounded-btn px-4 py-2.5 text-left text-sm font-semibold text-red-600">Logout</button>
          </div>
        )}
      </nav>
      <main>{children}</main>
      {/* Floating cart button — always one tap away on mobile */}
      <Link to="/cart" aria-label="Open cart"
        className="fixed bottom-5 right-5 z-40 flex h-14 w-14 items-center justify-center rounded-pill bg-primary text-white shadow-xl transition-all hover:bg-primary-dark active:scale-95 md:hidden">
        {IconH.cart({ className: 'h-6 w-6' })}
        {cartCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-6 min-w-6 items-center justify-center rounded-pill bg-gold px-1.5 text-xs font-black text-white shadow">{cartCount}</span>
        )}
      </Link>
      <footer className="mt-16 border-t border-gray-200 bg-white py-8 text-center text-sm text-gray-400">© 2026 DETOMSITE · Student Portal</footer>
    </div>
  )
}

/* ─── Pages ─── */

/* Register */
function Register() {
  const navigate = useNavigate()
  const [f, setF] = useState({ username: '', email: '', phone: '', password: '', confirm: '' })
  const [err, setErr] = useState(''); const [loading, setLoading] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    if (f.password !== f.confirm) { setErr('Passwords do not match'); return }
    if (!isValidMobile(f.phone)) { setErr('Please enter a valid 10-digit mobile number'); return }
    setLoading(true)
    try {
      await api.post('/users/register', { username: f.username, email: f.email, password: f.password, name: f.username, phone: f.phone })
      navigate('/login?registered=true')
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Registration failed') }
    finally { setLoading(false) }
  }
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 to-white px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-card bg-primary text-white shadow-lg">{IconH.graduation({ className: 'h-8 w-8' })}</span>
          <h1 className="mt-4 text-2xl font-bold text-primary-dark">Student Registration</h1>
          <p className="text-sm text-gray-500">Create your campus food account</p>
        </div>
        <div className="rounded-card bg-white p-8 shadow-lg border">
          {err && <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600">{err}</div>}
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">{IconH.user({ className: 'h-3.5 w-3.5' })}Username</label>
              <input type="text" value={f.username} onChange={e => setF({...f, username: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-primary-light/200 focus:shadow-card" placeholder="Your username" required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Email</label>
              <input type="email" value={f.email} onChange={e => setF({...f, email: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-primary-light/200 focus:shadow-card" placeholder="you@campus.edu" required />
              <p className="mt-1 text-[11px] text-gray-400">Use your campus email — you may need it to recover your password later.</p>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">{IconH.phone({ className: 'h-3.5 w-3.5 inline' })} Mobile Number</label>
              <PhoneField value={f.phone} onChange={v => setF({...f, phone: v})} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">{IconH.lock({ className: 'h-3.5 w-3.5 inline' })} Password</label>
                <PasswordField value={f.password} onChange={v => setF({...f, password: v})} placeholder="Min 4 characters" autoComplete="new-password" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Confirm</label>
                <PasswordField value={f.confirm} onChange={v => setF({...f, confirm: v})} placeholder="Repeat" autoComplete="new-password" />
              </div>
            </div>
            <button type="submit" disabled={loading} className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white transition-all hover:bg-primary-dark active:scale-[0.99] disabled:opacity-40">{loading ? 'Creating...' : 'Create Account'}</button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-400">Already have an account? <Link to="/login" className="font-bold text-primary">Sign In</Link></p>
        </div>
      </div>
    </div>
  )
}

/* Login */
function Login() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [err, setErr] = useState(''); const [loading, setLoading] = useState(false)
  const registered = params.get('registered') === 'true'
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setLoading(true)
    try {
      const res = await api.post('/users/login', { username, password })
      localStorage.setItem('access_token', res.data.access_token)
      localStorage.setItem('user_data', JSON.stringify(res.data.user))
      navigate('/shops')
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Login failed') }
    finally { setLoading(false) }
  }
  return (
    <div className="relative min-h-screen lg:grid lg:grid-cols-2">
      {/* Mobile background — faded food photo (visible below lg only) */}
      <div className="absolute inset-0 overflow-hidden lg:hidden">
        <img
          src="https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=1000&q=80"
          alt=""
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="h-full w-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-emerald-50/80 via-white/60 to-white/80" />
      </div>
      {/* Left — brand panel with campus-food photo (desktop only) */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden bg-gradient-to-br from-emerald-950 via-emerald-800 to-emerald-900 p-12 text-white">
        <img
          src="https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=1000&q=80"
          alt="Fresh campus food"
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="absolute inset-0 h-full w-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-emerald-950/95 via-emerald-900/50 to-emerald-950/20" />
        <div className="relative">
          <span className="inline-flex items-center gap-2 rounded-pill border border-white/15 bg-white/10 px-4 py-1.5 text-xs font-bold uppercase tracking-widest text-primary/50 backdrop-blur-sm">{IconH.graduation({ className: 'h-4 w-4' })} DETOMSITE</span>
          <h2 className="mt-8 max-w-md text-4xl font-black leading-tight">Campus food,<br />delivered to your hostel.</h2>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-primary/50/90">Order from the shops on your campus, track your order live, and pay by scanning a QR or on delivery.</p>
          <ul className="mt-8 space-y-4 text-sm text-primary-light">
            {[
              ['Order in seconds', 'Browse live menus from your campus shops'],
              ['Track your order live', 'Know exactly when your food arrives'],
              ['Pay your way', 'Scan the UPI QR or pay cash on delivery'],
            ].map(([t, s]) => (
              <li key={t} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-emerald-400/20 text-primary/80">{IconH.check({ className: 'h-3.5 w-3.5' })}</span>
                <span><b>{t}</b><span className="block text-xs font-normal text-primary/50/70">{s}</span></span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-primary/60/60">© {new Date().getFullYear()} DETOMSITE · Student Portal</p>
      </div>
      {/* Right — login form (sits above the faded mobile photo) */}
      <div className="relative flex min-h-screen items-center justify-center bg-gradient-to-br from-emerald-50/90 to-white/95 px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 text-center">
            <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-card bg-primary text-white shadow-lg">{IconH.graduation({ className: 'h-8 w-8' })}</span>
            <h1 className="mt-4 text-2xl font-bold text-primary-dark">Student Login</h1>
            <p className="text-sm text-gray-500">Sign in to browse and order</p>
          </div>
          <div className="rounded-card bg-white p-8 shadow-lg border">
            {registered && <div className="mb-4 flex items-center gap-2 rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3 text-sm font-semibold text-primary">{IconH.check({ className: 'h-4 w-4' })}Account created! Please sign in.</div>}
            {err && <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600">{err}</div>}
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">{IconH.user({ className: 'h-3.5 w-3.5' })}Username</label>
                <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-primary-light/200 focus:shadow-card" placeholder="Your username" required />
              </div>
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">{IconH.lock({ className: 'h-3.5 w-3.5' })}Password</label>
                <PasswordField value={password} onChange={setPassword} placeholder="Your password" autoComplete="current-password" />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white transition-all hover:bg-primary-dark active:scale-[0.99] disabled:opacity-40">{loading ? 'Signing in...' : 'Sign In'}</button>
              <div className="text-center">
                <Link to="/forgot-password" className="text-xs font-bold text-primary transition-colors hover:text-primary">Forgot password?</Link>
              </div>
            </form>
            <p className="mt-6 text-center text-sm text-gray-400">Don't have an account? <Link to="/register" className="font-bold text-primary">Register</Link></p>
          </div>
        </div>
      </div>
    </div>
  )
}

/* Forgot Password — DOUBLE email verification: a first OTP proves you own the
   email, then a SECOND OTP (emailed after the first is accepted) unlocks the
   password change. */
function ForgotPassword() {
  const [step, setStep] = useState<'request' | 'otp'>('request')
  const [identifier, setIdentifier] = useState('')
  const [otp, setOtp] = useState('')
  const [pw, setPw] = useState(''); const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState(''); const [info, setInfo] = useState(''); const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  /* Step 1 — send ONE 6-digit code to the registered email. The code is never
     shown in the app; it arrives only by email. */
  const requestOtp = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setInfo(''); setLoading(true)
    try {
      const res = await api.post('/users/forgot-password', { identifier })
      setInfo(res.data?.message || 'A 6-digit code was sent to your registered email.')
      setStep('otp')
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Request failed') }
    finally { setLoading(false) }
  }

  /* Step 2 — the backend verifies the code and updates the password in the DB. */
  const resetPw = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setInfo('')
    if (pw !== confirm) { setErr('Passwords do not match'); return }
    if (pw.length < 4) { setErr('Password must be at least 4 characters'); return }
    setLoading(true)
    try {
      await api.post('/users/reset-password', { identifier, otp, new_password: pw })
      setDone(true)
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Reset failed') }
    finally { setLoading(false) }
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 to-white px-4">
        <div className="w-full max-w-sm rounded-card bg-white p-8 shadow-lg border text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-pill bg-primary-light text-primary">{IconH.check({ className: 'h-7 w-7' })}</span>
          <h1 className="mt-4 text-2xl font-bold text-primary-dark">Password Updated!</h1>
          <p className="mt-2 text-sm text-gray-500">You can now sign in with your new password.</p>
          <Link to="/login" className="mt-6 block w-full rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white hover:bg-primary-dark">Go to Login</Link>
        </div>
      </div>
    )
  }

  const inputCls = "w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-primary-light/200 focus:shadow-card"
  const stepTitle = step === 'request' ? 'Reset your password' : 'Enter the code & set a new password'

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 to-white px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-card bg-primary text-white shadow-lg">{IconH.lock({ className: 'h-8 w-8' })}</span>
          <h1 className="mt-4 text-2xl font-bold text-primary-dark">Forgot Password</h1>
          <p className="text-sm text-gray-500">Step {step === 'request' ? 1 : 2} of 2 · {stepTitle}</p>
        </div>
        <div className="rounded-card bg-white p-8 shadow-lg border">
          {err && <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600">{err}</div>}
          {info && <div className="mb-4 rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3 text-sm font-semibold text-primary">{info}</div>}
          {step === 'request' && (
            <form onSubmit={requestOtp} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Username or Email</label>
                <input type="text" value={identifier} onChange={e => setIdentifier(e.target.value)} className={inputCls} placeholder="Your username or registered email" required />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white transition-all hover:bg-primary-dark active:scale-[0.99] disabled:opacity-40">{loading ? 'Sending...' : 'Send Code'}</button>
            </form>
          )}
          {step === 'otp' && (
            <form onSubmit={resetPw} className="space-y-4">
              <p className="text-xs leading-relaxed text-gray-500">We emailed a <b>6-digit code</b> to the email on your account. Enter it with your new password below — the code expires in 15 minutes.</p>
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">6-Digit Code (from your email)</label>
                <input type="text" inputMode="numeric" value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} className={`${inputCls} text-center text-2xl font-black tracking-[0.4em]`} placeholder="••••••" required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">New Password</label>
                <PasswordField value={pw} onChange={setPw} placeholder="Min 4 characters" autoComplete="new-password" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Confirm Password</label>
                <PasswordField value={confirm} onChange={setConfirm} placeholder="Repeat password" autoComplete="new-password" />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white transition-all hover:bg-primary-dark active:scale-[0.99] disabled:opacity-40">{loading ? 'Saving...' : 'Verify Code & Update Password'}</button>
            </form>
          )}
          {step !== 'request' && (
            <p className="mt-5 text-center">
              <button type="button" onClick={() => { setStep('request'); setErr(''); setInfo(''); }} className="text-xs font-bold text-primary hover:text-primary">← Start over</button>
            </p>
          )}
          <p className="mt-5 text-center text-sm text-gray-400">Remembered it? <Link to="/login" className="font-bold text-primary">Sign In</Link></p>
        </div>
      </div>
    </div>
  )
}

/* Dashboard */
function Dashboard() {
  const [shops, setShops] = useState<Shop[]>([]); const [orders, setOrders] = useState<Order[]>([]); const [loading, setLoading] = useState(true)
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  useEffect(() => {
    Promise.all([
      fetchShopsCached(),
      fetchOrdersCached(),
    ]).then(([s, o]) => { setShops(s); setOrders(o) }).finally(() => setLoading(false))
  }, [])
  const myOrders = orders.filter(o => o.student_name.toLowerCase() === (user.name || '').toLowerCase())
  const active = myOrders.filter(o => o.status !== 'Completed' && o.status !== 'Cancelled')
  const total = myOrders.reduce((s, o) => s + o.total, 0)

  if (loading) return <div className="flex items-center justify-center py-20 text-gray-400">Loading...</div>

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6"><h1 className="text-2xl font-bold text-primary-dark">Dashboard</h1><p className="text-sm text-gray-500">Welcome, {user.name || 'Student'}</p></div>
      {/* 2×2 grid on phones so all four stats sit on one screen */}
      <div className="mb-6 grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
        {[['Total Orders', myOrders.length], ['Active Orders', active.length], ['Total Spent', `₹${total}`], ['Shops Available', shops.length]].map(([l, v]) => (
          <div key={l} className="rounded-btn bg-white p-3.5 shadow-sm border sm:p-4">
            <p className="text-[11px] font-semibold text-gray-500 sm:text-xs">{l}</p>
            <p className="mt-0.5 text-xl font-bold text-primary-dark sm:mt-1 sm:text-2xl">{v}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-btn bg-white p-5 shadow-sm border">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-primary">{IconH.store({ className: 'h-5 w-5' })}Shops</h2>
          <div className="space-y-3">
            {shops.slice(0, 6).map(s => (
              <Link key={s.id} to={`/shop/${s.id}`} className="flex items-center justify-between rounded-btn border p-4 transition-all hover:bg-primary-light/30">
                <div><p className="font-bold text-primary-dark">{s.name}</p><p className="text-xs text-gray-500">{s.category} · {s.rating.toFixed(1)} {IconH.star({ className: 'h-3 w-3 inline text-gold-dark' })}</p></div>
                <span className={`shrink-0 rounded-pill px-2.5 py-1 text-xs font-bold ${isShopOrderable(s) ? 'bg-primary-light text-primary' : 'bg-gray-100 text-gray-500'}`}>
                  <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-pill ${isShopOrderable(s) ? 'bg-primary' : 'bg-gray-400'}`} />{isShopOrderable(s) ? 'Open' : 'Closed'}
                </span>
              </Link>
            ))}
          </div>
        </section>
        <section className="rounded-btn bg-white p-5 shadow-sm border">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-primary">{IconH.package({ className: 'h-5 w-5' })}Recent Orders</h2>
          <div className="space-y-3">
            {myOrders.slice(0, 5).map(o => (
              <Link key={o.id} to={`/order/${o.id}`} className="flex items-center justify-between rounded-btn border p-4 transition-all hover:bg-primary-light/30">
                <div><p className="font-bold text-primary-dark">{o.shop_name}</p><p className="text-xs text-gray-500">{o.items.slice(0, 40)}</p></div>
                <span className={`rounded-sm px-2 py-0.5 text-xs font-bold ${o.status === 'Completed' ? 'bg-primary-light text-primary' : 'bg-gold-light text-gold-dark'}`}>{o.status}</span>
              </Link>
            ))}
            {myOrders.length === 0 && <p className="text-sm text-gray-400">No orders yet. <Link to="/shops" className="text-primary font-semibold">Start ordering!</Link></p>}
          </div>
        </section>
      </div>
    </div>
  )
}

/* Shops listing — search covers shop names, categories, AND food items */
function ShopsPage() {
  const [shops, setShops] = useState<Shop[]>([]); const [search, setSearch] = useState(''); const [loading, setLoading] = useState(true)
  const [allProducts, setAllProducts] = useState<Product[]>([])
  useEffect(() => {
    fetchShopsCached().then(s => setShops(s)).finally(() => setLoading(false))
    /* Pre-fetch products from all shops so item search works instantly */
    api.get<Product[]>('/local/products').then(r => setAllProducts(r.data || [])).catch(() => {})
  }, [])
  /* If the search query matches any product name/description/category, include
     the parent shop in the results — students can search "biryani" and see every
     shop that sells it. */
  const q = search.toLowerCase().trim()
  const shopIdsWithMatchingProduct = q ? [...new Set(allProducts.filter(p =>
    `${p.name} ${p.description || ''} ${p.category || ''}`.toLowerCase().includes(q)
  ).map(p => p.shop_id))] : []
  const filtered = shops.filter(s => {
    if (!q) return true
    /* Match on shop name or category first */
    if (`${s.name} ${s.category}`.toLowerCase().includes(q)) return true
    /* Match on any food item belonging to this shop */
    if (shopIdsWithMatchingProduct.includes(s.id)) return true
    return false
  })
  if (loading) return <div className="flex items-center justify-center py-20 text-gray-400">Loading...</div>
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-primary-dark">Shops on Campus</h1>
        <p className="mt-1 text-sm text-gray-500">{user.name ? `Hi ${user.name.split(' ')[0]}, ` : ''}order from a campus shop — live menu, fast delivery.</p>
        <div className="relative mt-4 w-full max-w-md">
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400">{IconH.search({ className: 'h-4 w-4' })}</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search shops, or food like 'dosa'..." className="w-full rounded-btn border-2 border-gray-200 py-3 pl-10 pr-4 text-sm outline-none transition-all focus:border-primary-light/200 focus:shadow-card" />
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 sm:gap-5 lg:grid-cols-3">
        {filtered.map(s => (
          <Link key={s.id} to={`/shop/${s.id}`} className="group rounded-card border bg-white p-5 shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg sm:p-6">
            {/* min-w-0 + truncate keep long shop names from overflowing the card */}
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0"><h3 className="truncate font-bold text-primary-dark text-lg" title={s.name}>{s.name}</h3><p className="truncate text-sm text-gray-500">{s.category}</p></div>
              <span className="flex shrink-0 items-center gap-1 rounded-pill bg-primary-light/30 px-2.5 py-1 text-xs font-bold text-primary">{IconH.star({ className: 'h-3.5 w-3.5 text-gold-dark' })}{s.rating.toFixed(1)}</span>
            </div>
            <p className="mt-2.5 line-clamp-2 text-sm text-gray-500">{s.description}</p>
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="font-semibold text-primary">{s.opening_time} - {s.closing_time}</span>
              <div className="flex items-center gap-2">
                <span className={`rounded-pill px-2.5 py-1 text-xs font-bold ${isShopOrderable(s) ? 'bg-primary-light text-primary' : 'bg-gray-100 text-gray-500'}`}>
                  <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-pill ${isShopOrderable(s) ? 'bg-primary' : 'bg-gray-400'}`} />{isShopOrderable(s) ? 'Open' : 'Closed'}
                </span>
                <span className="flex items-center gap-0.5 font-bold text-primary group-hover:underline">Menu{IconH.chevronRight({ className: 'h-4 w-4' })}</span>
              </div>
            </div>
          </Link>
        ))}
        {filtered.length === 0 && (
          <div className="sm:col-span-2 lg:col-span-3 rounded-btn border border-dashed border-gray-300 bg-white p-10 text-center">
            <p className="text-sm text-gray-500">No shops match "{search}". Try a different name — or check back later.</p>
          </div>
        )}
      </div>
    </div>
  )
}

/* Shop Detail */
function ShopDetailPage() {
  const { shopId } = useParams()
  const [shop, setShop] = useState<Shop | null>(null); const [products, setProducts] = useState<Product[]>([]); const [msg, setMsg] = useState('')
  const [search, setSearch] = useState('')
  useEffect(() => {
    if (!shopId) return
    Promise.all([api.get<Shop>(`/local/shops/${shopId}`), api.get<Product[]>('/local/products', { params: { shop_id: shopId } })])
      .then(([s, p]) => { setShop(s.data); setProducts(p.data) }).catch(() => {})
  }, [shopId])
  if (!shop) return <div className="flex items-center justify-center py-20 text-gray-400">Loading...</div>
  const orderable = isShopOrderable(shop)
  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <div className="mb-6 rounded-card bg-gradient-to-br from-emerald-800 to-emerald-700 p-6 text-white">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            {/* break-words stops long shop names overflowing the header on phones */}
            <h1 className="break-words text-2xl font-black leading-tight sm:text-3xl">{shop.name}</h1>
            <p className="mt-1 flex items-center gap-1 text-primary/50">{shop.category} · {shop.rating.toFixed(1)} {IconH.star({ className: 'h-3.5 w-3.5 text-gold' })}</p>
            <p className="mt-2 text-sm text-primary/50/80">{shop.description}</p>
            <p className="mt-2 flex items-center gap-1.5 text-sm">{IconH.phone({ className: 'h-3.5 w-3.5' })}{shop.opening_time} - {shop.closing_time} · {shop.phone}</p>
          </div>
          <span className={`shrink-0 rounded-pill px-3 py-1.5 text-xs font-bold ${orderable ? 'bg-white/20 text-white' : 'bg-white/10 text-primary/50'}`}>
            <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-pill ${orderable ? 'bg-emerald-300' : 'bg-gray-300'}`} />{orderable ? 'Open Now' : 'Closed'}
          </span>
        </div>
      </div>
      {!orderable && (
        <div className="mb-4 flex items-start gap-2 rounded-btn border border-gold-light/60 bg-amber-50 px-4 py-3 text-sm font-semibold text-gold-dark">
          {IconH.alert({ className: 'h-4 w-4 mt-0.5 shrink-0' })}<span>{shopStatusReason(shop)}. You can still browse the menu — ordering opens when the shop is accepting.</span>
        </div>
      )}
      {msg && <div className="mb-4 rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3 text-sm font-semibold text-primary">{msg}</div>}
      <div className="mb-4 relative">
        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400">{IconH.search({ className: 'h-4 w-4' })}</span>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search products..." className="w-full rounded-btn border-2 border-gray-200 py-3 pl-10 pr-4 text-sm outline-none transition-all focus:border-primary-light/200 focus:shadow-card" />
      </div>
      <div className="space-y-3">
        {products.filter(p => p.available && (!search || `${p.name} ${p.description} ${p.category}`.toLowerCase().includes(search.toLowerCase()))).map(p => (
          <div key={p.id} className="rounded-btn border bg-white p-4 flex items-center justify-between">
            <div><h3 className="font-bold text-primary-dark">{p.name}</h3><p className="text-sm text-gray-500">{p.description}</p><p className="mt-1 font-bold text-primary">₹{p.price}</p></div>
            <button onClick={() => { addToCart(p, shop); setMsg(`${p.name} added to cart!`) }} disabled={!orderable} className={`rounded-btn px-4 py-2 text-sm font-bold text-white ${orderable ? 'bg-primary hover:bg-primary-dark' : 'cursor-not-allowed bg-gray-300'}`}>{orderable ? 'Add +' : 'Unavailable'}</button>
          </div>
        ))}
        {products.filter(p => p.available && (!search || `${p.name} ${p.description} ${p.category}`.toLowerCase().includes(search.toLowerCase()))).length === 0 && <p className="text-center text-gray-400 py-8">{search ? 'No products match your search' : 'No products available yet'}</p>}
      </div>
    </div>
  )
}

/* Cart */
function CartPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<CartItem[]>(() => getCart())
  useEffect(() => { const sync = () => setItems(getCart()); window.addEventListener('cart-updated', sync); return () => window.removeEventListener('cart-updated', sync) }, [])
  const bill = billBreakdown(items)
  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-bold text-primary-dark">Your Cart</h1>
      {items.length === 0 ? (
        <div className="rounded-btn bg-white p-8 text-center shadow-sm border">
          <p className="mb-4 text-lg font-semibold text-gray-600">Your cart is empty</p>
          <Link to="/shops" className="inline-flex rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white hover:bg-primary-dark">Browse Shops →</Link>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <div className="space-y-4">
            {/* Group cart items by shop */}
            {(() => {
              const grouped: Record<string, CartItem[]> = {}
              for (const item of items) {
                if (!grouped[item.shop_name]) grouped[item.shop_name] = []
                grouped[item.shop_name].push(item)
              }
              return Object.entries(grouped).map(([shopName, shopItems]) => {
                const shopSubtotal = shopItems.reduce((a, i) => a + i.price * i.quantity, 0)
                return (
                  <div key={shopName} className="rounded-btn bg-white p-4 shadow-sm border">
                    <div className="mb-3 flex items-center justify-between border-b border-gray-100 pb-2">
                      <h3 className="flex items-center gap-2 font-bold text-primary-dark">{IconH.store({ className: 'h-4 w-4 text-primary' })}{shopName}</h3>
                      <span className="text-xs font-semibold text-primary">Subtotal ₹{shopSubtotal}</span>
                    </div>
                    <div className="space-y-2">
                      {shopItems.map(item => (
                        <div key={item.product_id} className="flex items-center justify-between rounded-sm bg-gray-50 px-3 py-2.5">
                          <div className="min-w-0"><h4 className="truncate font-semibold text-primary-dark">{item.name}</h4><p className="text-xs text-gray-500">₹{item.price} each</p></div>
                          <div className="flex items-center gap-3">
                            <div className="flex items-center rounded-btn border"><button onClick={() => { updateQty(item.product_id, item.quantity - 1); setItems(getCart()) }} className="px-3 py-1.5 text-sm font-bold">−</button><span className="min-w-[2rem] text-center text-sm font-bold">{item.quantity}</span><button onClick={() => { updateQty(item.product_id, item.quantity + 1); setItems(getCart()) }} className="px-3 py-1.5 text-sm font-bold">+</button></div>
                            <span className="min-w-[4rem] text-right font-bold text-primary">₹{item.price * item.quantity}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })
            })()}
          </div>
          <div className="h-fit rounded-btn bg-white p-5 shadow-sm border">
            <h2 className="mb-4 text-lg font-bold text-primary-dark">Bill Details</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span>Subtotal</span><span className="font-semibold">₹{bill.subtotal}</span></div>
              <div className="flex justify-between border-t pt-3 text-lg font-bold">Total<span>₹{bill.total}</span></div>
            </div>
            <button onClick={() => navigate('/payment')} className="mt-5 w-full rounded-btn bg-primary px-5 py-3 text-sm font-bold text-white hover:bg-primary-dark">Proceed to Payment →</button>
          </div>
        </div>
      )}
    </div>
  )
}

/* Orders */
function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([])
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  useEffect(() => { fetchOrdersCached().then(list => setOrders(list.filter(o => o.student_name.toLowerCase() === (user.name || '').toLowerCase()))).catch(() => {}) }, [user.name])
  /* A student can cancel an order while its delivery window is still open
     (morning orders by 12:30 PM, afternoon orders by 6:00 PM) — orders are
     auto-accepted inside the windows, so the window is the cancel rule. */
  const cancelOrder = async (o: Order) => {
    if (!window.confirm(`Cancel order #${o.token} from ${o.shop_name}? You can cancel until this delivery window closes.`)) return
    try {
      await api.post(`/local/orders/${o.id}/cancel`)
      invalidateOrdersCache()
      setOrders(prev => prev.map(x => x.id === o.id ? { ...x, status: 'Cancelled' } : x))
    } catch (err: any) { window.alert(err?.response?.data?.detail || 'Could not cancel the order') }
  }
  const grouped = { pending: orders.filter(o => o.status === 'Pending Acceptance'), active: orders.filter(o => ['Accepted', 'Confirmed', 'Preparing', 'Ready'].includes(o.status)), completed: orders.filter(o => ['Completed', 'Cancelled'].includes(o.status)) }
  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-bold text-primary-dark">My Orders</h1>
      {['pending', 'active', 'completed'].map(key => {
        const items = grouped[key as keyof typeof grouped]
        if (!items.length) return null
        return (
          <section key={key} className="mb-6">
            <h2 className="mb-3 text-lg font-bold capitalize text-primary">{key} ({items.length})</h2>
            <div className="space-y-3">
              {items.map(o => (
                <Link key={o.id} to={`/order/${o.id}`} className="block rounded-btn border bg-white p-4 transition-all hover:bg-gray-50">
                  <div className="flex items-start justify-between">
                    <span className="text-lg font-bold text-primary-dark">{o.shop_name}</span>
                    <div className="flex items-center gap-2">
                      <span className={`rounded-sm px-2 py-0.5 text-xs font-bold ${o.payment_method === 'COD' ? 'bg-gold-light text-gold-dark' : 'bg-blue-100 text-blue-700'}`}>{o.payment_method === 'COD' ? 'COD' : 'UPI'}</span>
                      <span className="rounded-sm bg-gray-100 px-2 py-0.5 text-xs font-bold">{o.status}</span>
                    </div>
                  </div>
                  <ul className="mt-1 space-y-1">
                    {o.items.split(', ').filter(Boolean).map((it, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-gray-600"><span className="inline-block h-1.5 w-1.5 rounded-pill bg-primary" />{it}</li>
                    ))}
                  </ul>
                  <p className="mt-1 text-sm text-gray-400">{o.delivery_location} · {o.delivery_slot} · Placed {formatPlacedAt(o.created_at)}</p>
                  <p className="mt-1 font-bold text-primary">₹{o.total}</p>
                  {canCancelOrder(o) && (
                    <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); void cancelOrder(o) }}
                      className="mt-2 rounded-sm border border-red-200 px-3 py-1.5 text-xs font-bold text-red-600 transition-colors hover:bg-red-50">
                      Cancel Order
                    </button>
                  )}
                </Link>
              ))}
            </div>
          </section>
        )
      })}
      {orders.length === 0 && <div className="rounded-btn bg-white p-8 text-center border"><p className="text-gray-500">No orders yet</p></div>}
    </div>
  )
}

/* Payment */
function PaymentPage() {
  const navigate = useNavigate()
  const [ps, setPs] = useState<PaymentSettings | null>(null); const [shop, setShop] = useState<Shop | null>(null)
  const [method, setMethod] = useState<'qr' | 'cod'>('qr')
  const [loc, setLoc] = useState(''); const [slot, setSlot] = useState('Evening'); const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false); const [err, setErr] = useState('')
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  const items = getCart(); const bill = billBreakdown(items)

  // Resolve the UPI target: the shop's own UPI ID first, then the global
  // (admin) UPI ID as a fallback. Money goes to the shop the order is from.
  const shopUpi = shop?.upi_id?.trim() || ''
  const globalUpi = ps?.upi_id?.trim() || ''
  const upi = shopUpi || globalUpi
  /* UPI is only offered when THIS shop has a UPI ID (or the admin enabled the
     global fallback). Vendors without a UPI ID → Cash on Delivery only. */
  /* The shop's Settings decide which payment methods are offered: UPI only
     when the vendor has it enabled AND a UPI target exists (the shop's own
     UPI ID, or the admin's global fallback). COD only when enabled. */
  /* !! handles both DB representations: SQLite returns 0/1 integers while
     Supabase (Postgres) returns real booleans. The old `!== 0` check broke on
     Supabase — `false !== 0` is `true` — which made a shop that turned UPI
     off still show UPI at checkout. */
  const upiOn = shop ? !!shop.upi_enabled : true
  const codOn = shop ? !!shop.cod_enabled : true
  const upiAvailable = upiOn && (Boolean(shopUpi) || Boolean(ps?.manual_enabled && globalUpi))
  const codAvailable = codOn
  const payOn = upiAvailable || codAvailable
  /* Only fall back to COD once BOTH the shop and the payment settings have
     loaded — before that we can't know if UPI/QR is really unavailable, and
     flipping early would silently force every checkout onto COD even for
     shops that accept UPI. QR stays the default whenever it's available. */
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [shopLoaded, setShopLoaded] = useState(false)
  /* The shop may have been stopped/closed AFTER the items were added to the
     cart (vendor pressed Stop, or the shop got removed) — check orderability
     before letting the student pay, so they never hit a confusing backend
     rejection mid-payment. */
  const orderable = shopLoaded ? (shop ? isShopOrderable(shop) : true) : true
  useEffect(() => {
    if (!settingsLoaded || !shopLoaded) return
    if (!upiAvailable && codAvailable) setMethod('cod')
    else if (upiAvailable && !codAvailable) setMethod('qr')
    else if (!upiAvailable && !codAvailable) setMethod('qr')
  }, [settingsLoaded, shopLoaded, upiAvailable, codAvailable])

  /* The QR the student scans — the shop's UPI ID with the bill amount
     pre-filled (exactly the link that already works perfectly when scanned).
     It has no order reference yet; the order page shows a fresh one with the
     order id after the order is placed. */
  const payerName = (shopUpi ? shop?.name : ps?.receiver_name) || 'DETOMSITE'
  const qrUri = upi ? buildUpiUri(upi, payerName, bill.total, 'DETOMSITE Order') : ''

  useEffect(() => { api.get<PaymentSettings>('/local/payment-settings').then(r => setPs(r.data)).catch(() => {}).finally(() => setSettingsLoaded(true)) }, [])
  useEffect(() => {
    if (!items.length) return
    api.get<Shop>(`/local/shops/${items[0].shop_id}`).then(r => setShop(r.data)).catch(() => {}).finally(() => setShopLoaded(true))
  }, [items[0]?.shop_id])

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); if (!items.length) { setErr('Cart empty'); return }
    if (!isValidMobile(phone)) { setErr('Please enter a valid 10-digit mobile number'); return }
    if (shopLoaded && shop && !isShopOrderable(shop)) { setErr('This shop is currently closed — the vendor hasn\'t started accepting orders right now. Please try again later.'); return }
    if (!payOn) { setErr('This shop is not accepting any payments right now — the vendor has turned off UPI and Cash on Delivery. Please try again later.'); return }
    if (method === 'qr' && !upiAvailable) { setErr(upiOn ? 'This shop has not set up UPI payments yet — ask the vendor to add their UPI ID' : 'This shop has turned off UPI payments — choose Cash on Delivery instead'); return }
    if (method === 'cod' && !codAvailable) { setErr('This shop has turned off Cash on Delivery — please pay via UPI instead'); return }
    setLoading(true)
    try {
      /* Group items by shop so each shop gets its own sub-order */
      const shopGroups: Record<string, CartItem[]> = {}
      for (const item of items) {
        if (!shopGroups[item.shop_id]) shopGroups[item.shop_id] = []
        shopGroups[item.shop_id].push(item)
      }
      const shopIds = Object.keys(shopGroups)
      let lastOrder: Order | null = null
      for (const shopId of shopIds) {
        const shopItems = shopGroups[shopId]
        const shopTotal = shopItems.reduce((a, i) => a + i.price * i.quantity, 0)
        const order = await api.post<Order>('/local/orders', {
          shop_id: shopId,
          items: shopItems.map(i => ({ product_id: i.product_id, quantity: i.quantity })),
          student_name: user.name || 'Student',
          student_phone: toE164(phone),
          delivery_location: loc,
          delivery_slot: slot,
          payment_method: method === 'cod' ? 'COD' : 'UPI',
          total: shopTotal,
        })
        lastOrder = order.data
        /* Record payment for each sub-order */
        await api.post('/local/payments', { order_id: order.data.id, amount: shopTotal, method: method === 'cod' ? 'COD' : 'Manual UTR', utr_number: '', screenshot_name: '' })
      }

      if (method === 'cod') {
        clearCart()
        /* Navigate to last order's result page */
        if (lastOrder) navigate(`/order/${lastOrder.id}`)
        return
      }

      clearCart()
      if (lastOrder) navigate(`/order/${lastOrder.id}`)
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Failed') }
    finally { setLoading(false) }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-bold text-primary-dark">Checkout</h1>
      {items.length === 0 ? (
        <div className="rounded-btn bg-white p-8 text-center border"><p className="text-lg text-gray-500">Cart empty</p><Link to="/shops" className="mt-3 inline-flex rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white">Browse →</Link></div>
      ) : (
        <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_360px] lg:items-start">
          {/* Left column — shop banner + delivery details + payment. The
              summary card sits to the right on desktop (sticky) and stacks
              below on phones. */}
          <div className="min-w-0 space-y-6">
          {shop && (
            <div className="relative overflow-hidden rounded-card bg-gradient-to-br from-emerald-800 via-emerald-700 to-teal-600 p-5 text-white shadow-lg sm:p-6">
              <span className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-pill bg-white/10 blur-2xl" />
              <span className="pointer-events-none absolute -bottom-14 left-1/3 h-32 w-32 rounded-pill bg-teal-300/10 blur-xl" />
              <div className="relative flex flex-wrap items-center gap-4">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-card bg-white/15 text-white ring-1 ring-white/20">{IconH.store({ className: 'h-7 w-7' })}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary/50/90">Ordering from</p>
                  <p className="truncate text-xl font-black sm:text-2xl">{shop.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-primary/50/85">
                    <span>{shop.category}</span>
                    <span className="inline-block h-1 w-1 rounded-pill bg-primary-light/60" />
                    <span className="inline-flex items-center gap-0.5">⭐ {Number(shop.rating || 0).toFixed(1)}</span>
                  </p>
                </div>
                <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-pill px-3 py-1.5 text-xs font-bold ${isShopOrderable(shop) ? 'bg-primary-dark/40 text-primary-light ring-1 ring-emerald-200/40' : 'bg-white/15 text-white/80 ring-1 ring-white/20'}`}>
                  <span className={`h-2 w-2 rounded-pill ${isShopOrderable(shop) ? 'animate-pulse bg-emerald-300' : 'bg-white/50'}`} />
                  {isShopOrderable(shop) ? 'Open' : 'Closed'}
                </span>
              </div>
            </div>
          )}
          <div className="rounded-btn bg-white p-5 shadow-sm border">
            <h2 className="mb-4 text-lg font-bold">Delivery Details</h2>
            <div className="space-y-4 mb-6">
              <div>
                <label className="mb-1 block text-xs font-bold text-gray-500">Delivery location</label>
                <input value={loc} onChange={e => setLoc(e.target.value)} className="w-full rounded-btn border-2 px-4 py-2.5 text-sm outline-none focus:border-primary-light/200" placeholder="Type your location (e.g. Hostel 3, Room 204)" required />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {QUICK_LOCATIONS.map(ql => (
                    <button key={ql} type="button" onClick={() => setLoc(ql)}
                      className={`rounded-pill border px-3 py-1.5 text-xs font-bold transition-all ${loc === ql ? 'border-emerald-600 bg-primary text-white shadow-sm' : 'border-primary-light/50 bg-primary-light/30 text-primary hover:bg-primary-light'}`}>
                      📍 {ql}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-gray-500">Phone (10-digit mobile)</label>
                <PhoneField value={phone} onChange={setPhone} />
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-gray-500">Delivery slot</label>
                <select value={slot} onChange={e => setSlot(e.target.value)} className="w-full rounded-btn border-2 px-4 py-2.5 text-sm outline-none focus:border-primary-light/200">{['Morning', 'Afternoon', 'Evening', 'Night'].map(s => <option key={s}>{s}</option>)}</select>
              </div>
            </div>
            <h2 className="mb-4 text-lg font-bold">Payment</h2>
            {/* Stack the two method cards on phones so each gets full width; side-by-side from sm up */}
            <div className="flex flex-col gap-3 mb-4 sm:flex-row">
              {upiAvailable && (
                <button type="button" onClick={() => setMethod('qr')} className={`flex-1 rounded-btn border-2 p-4 text-center transition-all ${method === 'qr' ? 'border-primary-light/200 bg-primary-light/30 shadow-sm' : 'border-gray-200 hover:border-emerald-300'}`}>
                  <span className="mx-auto flex h-9 w-9 items-center justify-center rounded-pill bg-primary-light text-primary"><svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M14 14h3v3h-3zM18 18h3v3h-3zM14 21v-1M21 14v-1" /></svg></span>
                  <span className="mt-1.5 block text-sm font-bold">Scan &amp; Pay (UPI QR)</span>
                  <span className="block text-[11px] text-gray-500">Scan the QR with GPay / PhonePe / Paytm</span>
                </button>
              )}
              {codAvailable && (
              <button type="button" onClick={() => setMethod('cod')} className={`flex-1 rounded-btn border-2 p-4 text-center transition-all ${method === 'cod' ? 'border-amber-500 bg-amber-50 shadow-sm' : 'border-gray-200 hover:border-gold/40'}`}>
                <span className="mx-auto flex h-9 w-9 items-center justify-center rounded-pill bg-gold-light text-gold-dark">{IconH.cash({ className: 'h-5 w-5' })}</span>
                <span className="mt-1.5 block text-sm font-bold">Cash on Delivery</span>
                <span className="block text-[11px] text-gray-500">Pay when your order arrives</span>
              </button>
              )}
            </div>
            {shopLoaded && shop && !orderable && (
              <p className="mb-4 flex items-start gap-2 rounded-btn border-2 border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold text-red-600">
                {IconH.alert({ className: 'h-4 w-4 mt-0.5 shrink-0' })}<span>This shop is currently <b>closed</b> — the vendor hasn't started accepting orders right now. Your cart is saved; you can pay once the shop is back.</span>
              </p>
            )}
            {!payOn && (
              <p className="mb-4 flex items-start gap-2 rounded-btn border-2 border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold text-red-600">
                {IconH.alert({ className: 'h-4 w-4 mt-0.5 shrink-0' })}<span>This shop isn't accepting <b>any payments</b> right now — the vendor has turned off UPI and Cash on Delivery. Try again later.</span>
              </p>
            )}
            {!upiAvailable && codAvailable && (
              <p className="mb-4 flex items-start gap-2 rounded-btn border-2 border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-xs text-gray-500">
                {IconH.alert({ className: 'h-4 w-4 mt-0.5 shrink-0 text-gold-dark' })}<span>{upiOn ? "This shop hasn't set up UPI payments yet — only <b>Cash on Delivery</b> is available. The vendor can add a UPI ID from their portal." : "This shop has turned off <b>UPI payments</b> — only <b>Cash on Delivery</b> is available right now."}</span>
              </p>
            )}
            {upiAvailable && !codAvailable && (
              <p className="mb-4 flex items-start gap-2 rounded-btn border-2 border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-xs text-gray-500">
                {IconH.alert({ className: 'h-4 w-4 mt-0.5 shrink-0 text-gold-dark' })}<span>This shop has turned off <b>Cash on Delivery</b> — please pay via <b>UPI / QR</b> instead.</span>
              </p>
            )}
            {bill.total > UPI_LIMIT && (
              <div className="mb-4 flex items-start gap-2.5 rounded-btn border-2 border-gold/40 bg-amber-50 p-4">
                {IconH.alert({ className: 'h-5 w-5 shrink-0 text-gold-dark' })}
                <div className="text-xs leading-relaxed text-gold-dark">
                  <p className="font-bold">₹{bill.total.toLocaleString('en-IN')} is above the UPI transaction limit (₹{UPI_LIMIT.toLocaleString('en-IN')}).</p>
                  <p className="mt-1">Indian banks cap UPI per payment — above the limit the bank rejects the transaction with “exceeded the bank limit … retry with a smaller amount”, and <b>no money is debited</b>. {codAvailable ? <>Please choose <b>Cash on Delivery</b>, or place two smaller orders.</> : <>Please place two smaller orders instead.</>}</p>
                </div>
              </div>
            )}
            {method === 'qr' && (
              <div className="space-y-3">
                {upiAvailable ? (
                  <div className="rounded-btn border-2 border-primary-light/50 bg-primary-light/30 p-4">
                    <p className="text-xs font-semibold text-primary">Pay ₹{bill.total} to {shop?.name || 'this shop'} by scanning the QR</p>
                    <p className="mt-1 font-mono font-bold text-primary-dark">{upi}</p>
                    <p className="mt-1 text-xs text-primary">{shopUpi ? (shop?.shopkeeper_name ? `Receiver: ${shop.shopkeeper_name}` : 'Direct to shop') : (ps?.receiver_name ? `Receiver: ${ps.receiver_name}` : '')}</p>
                    <div className="mt-4 flex w-full flex-col items-center gap-4 rounded-card border-2 border-dashed border-emerald-300 bg-white p-4 sm:flex-row sm:justify-center sm:gap-6">
                      {qrUri && <QRCodeSVG value={qrUri} size={160} level="M" bgColor="#ffffff" fgColor="#065F46" className="h-auto w-full max-w-[170px] shrink-0" />}
                      <p className="flex items-center gap-1.5 text-center text-xs font-bold text-primary sm:max-w-[240px] sm:text-left">{IconH.phone({ className: 'h-3.5 w-3.5 shrink-0' })}Scan with your UPI app — amount ₹{bill.total} pre-filled</p>
                    </div>
                    <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-relaxed text-gold-dark">{IconH.alert({ className: 'h-3.5 w-3.5 mt-0.5 shrink-0' })}<span><b>Step 1:</b> tap "Place Order" below. <b>Step 2:</b> scan this QR (it also appears on your order page) with GPay / PhonePe / Paytm and pay ₹{bill.total}. The shop confirms your order once your payment arrives. <b>No money is deducted until you scan and confirm the payment.</b> If a payment ever shows <b>"exceeded bank limit"</b>, that comes from <b>your bank</b> — no money is debited — so try again later or choose <b>Cash on Delivery</b>.</span></p>
                  </div>
                ) : (
                  <p className="flex items-start gap-2 rounded-btn border-2 border-gold-light/60 bg-amber-50 px-4 py-3 text-sm text-gold-dark">
                    {IconH.alert({ className: 'h-4 w-4 mt-0.5 shrink-0' })}<span>This shop hasn't added a UPI ID yet. You can still order with <b>Cash on Delivery</b>.</span>
                  </p>
                )}
              </div>
            )}
            {method === 'cod' && (
              <div className="rounded-btn border-2 border-gold-light/60 bg-amber-50 p-4">
                <p className="flex items-center gap-2 text-sm font-bold text-gold-dark">{IconH.cash({ className: 'h-4 w-4' })}Pay ₹{bill.total} when your order is delivered</p>
                <p className="mt-1 text-xs text-gold-dark">Cash on Delivery — no online payment needed. The shop confirms your order, and you pay the delivery person in cash.</p>
              </div>
            )}
            {err && <p className="mt-4 text-sm font-medium text-red-600">{err}</p>}
          </div>
          </div>
          <div className="h-fit rounded-btn bg-white p-5 shadow-sm border lg:sticky lg:top-6">
            <h2 className="mb-4 text-lg font-bold">Summary</h2>
            <div className="space-y-2 text-sm"><div className="flex justify-between"><span>Subtotal</span><span className="font-semibold">₹{bill.subtotal}</span></div><div className="flex justify-between border-t pt-3 text-lg font-bold">Total<span>₹{bill.total}</span></div></div>
            <button type="submit" disabled={loading || !payOn || (method === 'qr' && !upiAvailable) || (shopLoaded && shop !== null && !orderable)} className="mt-5 w-full rounded-btn bg-primary px-5 py-3 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-40">{loading ? 'Placing order...' : method === 'cod' ? `Place Order · Pay ₹${bill.total} on Delivery` : `Place Order · Scan QR & Pay ₹${bill.total}`}</button>
          </div>
        </form>
      )}
    </div>
  )
}

/* Order Result */
function OrderResultPage() {
  const { orderId } = useParams()
  const [order, setOrder] = useState<Order | null>(null); const [shop, setShop] = useState<Shop | null>(null); const [ps, setPs] = useState<PaymentSettings | null>(null)
  const [cancelling, setCancelling] = useState(false); const [cancelErr, setCancelErr] = useState('')
  const [screenshot, setScreenshot] = useState<File | null>(null); const [uploading, setUploading] = useState(false); const [uploadMsg, setUploadMsg] = useState(''); const [uploadErr, setUploadErr] = useState(''); const [screenshotUrl, setScreenshotUrl] = useState('')
  const [utr, setUtr] = useState(''); const [utrSaving, setUtrSaving] = useState(false); const [utrMsg, setUtrMsg] = useState(''); const [utrErr, setUtrErr] = useState('')
  const saveUtr = async () => {
    if (!orderId || !utr.trim()) return
    setUtrSaving(true); setUtrMsg(''); setUtrErr('')
    try {
      const res = await api.post('/local/payments/utr', { order_id: orderId, utr_number: utr.trim().toUpperCase() })
      setUtrMsg(res.data?.message || 'UTR saved — your order will auto-confirm once the bank SMS matches it.')
      if (res.data?.order?.status === 'Confirmed') {
        const s = await api.get<Order>(`/local/orders/${orderId}`).catch(() => null); if (s?.data) setOrder(s.data)
      }
    } catch (err: any) { setUtrErr(err?.response?.data?.detail || 'Could not save the UTR — please try again') }
    finally { setUtrSaving(false) }
  }
  const uploadScreenshot = async () => {
    if (!screenshot || !orderId) return
    setUploading(true); setUploadMsg(''); setUploadErr('')
    try {
      const fd = new FormData(); fd.append('file', screenshot); fd.append('order_id', orderId)
      if (utr.trim()) fd.append('utr_number', utr.trim().toUpperCase())
      const res = await api.post('/local/payments/upload', fd)
      setUploadMsg(res.data?.message || 'Screenshot uploaded — the shop will verify your payment.')
      setScreenshotUrl(res.data?.screenshot_url || '')
      setScreenshot(null)
      if (res.data?.matched) setUtrMsg('UTR matched the bank SMS — your order is confirmed!')
      const s = await api.get<Order>(`/local/orders/${orderId}`).catch(() => null); if (s?.data) setOrder(s.data)
    } catch (err: any) { setUploadErr(err?.response?.data?.detail || 'Upload failed — please try again') }
    finally { setUploading(false) }
  }
  /* Cancellation follows the delivery window: orders placed inside a window
     (morning → 12:30 PM, afternoon → 6:00 PM) are auto-accepted, and the
     student can cancel until that window closes. */
  const cancellable = canCancelOrder(order)
  const cancelOrder = async () => {
    if (!order || !window.confirm('Cancel this order? You can cancel until its delivery window closes.')) return
    setCancelling(true); setCancelErr('')
    try {
      const res = await api.post(`/local/orders/${order.id}/cancel`)
      setOrder(res.data?.order || order)
      invalidateOrdersCache()
    } catch (err: any) { setCancelErr(err?.response?.data?.detail || 'Could not cancel the order') }
    finally { setCancelling(false) }
  }
  useEffect(() => {
    if (!orderId) return
    // Poll only while the tab is visible — the order page doesn't need live
    // updates from a backgrounded tab.
    const load = () => { if (document.visibilityState === 'visible') api.get<Order>(`/local/orders/${orderId}`).then(async r => { setOrder(r.data); const s = await api.get<Shop>(`/local/shops/${r.data.shop_id}`).catch(() => null); setShop(s?.data || null) }).catch(() => {}) }
    load(); const t = setInterval(load, 5000); return () => clearInterval(t)
  }, [orderId])
  useEffect(() => { api.get<PaymentSettings>('/local/payment-settings').then(r => setPs(r.data)).catch(() => {}) }, [])
  if (!order) return <div className="flex items-center justify-center py-20 text-gray-400">Loading...</div>
  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <div className="rounded-btn bg-white p-6 shadow-lg border text-center">
        <p className="text-xs font-bold uppercase tracking-wider text-gray-500">Order Result</p>
        <h1 className="mt-3 text-4xl font-black text-primary-dark">Order Placed</h1>
        <p className="mt-2 text-lg font-semibold text-gray-600">{order.shop_name}</p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <span className="inline-flex rounded-btn px-4 py-2 text-sm font-bold bg-primary-light/30 text-primary border border-primary-light/50">{order.status}</span>
          <span className={`inline-flex rounded-btn px-3 py-2 text-xs font-bold border ${order.payment_method === 'COD' ? 'bg-amber-50 text-gold-dark border-gold-light/60' : 'bg-blue-50 text-blue-700 border-blue-200'}`}>
            {order.payment_method === 'COD' ? 'Cash on Delivery' : 'UPI Payment'}
          </span>
        </div>
        <p className="mt-3 text-xs text-gray-400">Order #{order.token} · Placed {formatPlacedAt(order.created_at)}</p>
        {cancellable && (
          <div className="mt-4">
            <button onClick={() => void cancelOrder()} disabled={cancelling}
              className="rounded-btn border border-red-200 px-5 py-2.5 text-sm font-bold text-red-600 transition-colors hover:bg-red-50 disabled:opacity-40">
              {cancelling ? 'Cancelling…' : 'Cancel Order'}
            </button>
            <p className="mt-1.5 text-xs text-gray-400">Orders are accepted automatically inside delivery windows — you can cancel until the window closes (morning by 12:30 PM, afternoon by 6:00 PM).</p>
            {cancelErr && <p className="mt-1.5 text-xs font-semibold text-red-600">{cancelErr}</p>}
          </div>
        )}
        <div className="mt-6 rounded-btn bg-gray-50 p-5 text-left text-sm">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-gray-500">Your items</p>
          <ul className="space-y-1.5">
            {order.items.split(', ').filter(Boolean).map((it, i) => (
              <li key={i} className="flex items-center gap-2 text-gray-700"><span className="inline-block h-1.5 w-1.5 rounded-pill bg-primary" />{it}</li>
            ))}
          </ul>
          <p className="mt-3 flex items-center gap-1.5 text-gray-500">{IconH.mapPin({ className: 'h-4 w-4' })}{order.delivery_location} · {order.delivery_slot}</p>
          <p className="mt-2 font-bold text-primary">Total ₹{order.total}</p>
          {shop && <div className="mt-3 rounded-sm bg-white border p-3"><p className="font-semibold text-primary">Shop: {shop.shopkeeper_name}</p><p className="mt-0.5 flex items-center gap-1.5 text-gray-500">{IconH.phone({ className: 'h-3.5 w-3.5' })}{shop.phone}</p></div>}
        </div>
        {order.payment_method === 'COD' && (
          <div className="mt-6 flex items-start gap-2 rounded-btn border-2 border-gold-light/60 bg-amber-50 p-4 text-left text-sm text-gold-dark">
            {IconH.cash({ className: 'h-4 w-4 mt-0.5 shrink-0' })}<span><b>Cash on Delivery.</b> Keep <b>₹{order.total}</b> ready — you pay the shop when your order is delivered.</span>
          </div>
        )}
        {(order.status === 'Pending Payment' || order.status === 'Pending Verification') && order.payment_method !== 'COD' && (() => {
          const oUpi = (shop?.upi_id || ps?.upi_id || '').trim()
          const oUrl = oUpi ? buildUpiUri(oUpi, shop?.name || 'DETOMSITE', order.total, 'DETOMSITE Order', order.id) : ''
          return (
            <div className="mt-6 rounded-btn border-2 border-gold-light/60 bg-amber-50 p-4 text-left text-sm text-gold-dark">
              <div className="flex items-start gap-2">
                {IconH.card({ className: 'h-4 w-4 mt-0.5 shrink-0' })}<span><b>Payment pending.</b> Scan the QR below with your UPI app to pay <b>{oUpi || `${shop?.shopkeeper_name || 'the shop'}'s UPI ID`}</b> — the shop confirms your order once your payment arrives. <b>Pay once</b>, never twice.</span>
              </div>
              {oUpi && (
                <div className="mt-4 flex w-full flex-col items-center gap-3">
                  <div className="flex w-full justify-center rounded-card border-2 border-dashed border-gold/40 bg-white p-3 sm:p-4">
                    <QRCodeSVG value={oUrl} size={170} level="M" bgColor="#ffffff" fgColor="#92400E" className="h-auto w-full max-w-[180px]" />
                  </div>
                  <p className="flex items-center gap-1.5 text-center text-xs font-bold text-gold-dark">{IconH.phone({ className: 'h-3.5 w-3.5 shrink-0' })}Scan with your UPI app — amount ₹{order.total} pre-filled</p>
                  <p className="max-w-xs text-center text-[11px] leading-relaxed text-gold-dark">If the UPI app shows <b>"exceeded bank limit"</b>, that's <b>your bank</b> refusing — no money is debited. It means your UPI daily limit is used up or the account was newly linked. Try again later or use Cash on Delivery.</p>
                </div>
              )}
              <div className="mt-4 rounded-card border-2 border-dashed border-gold/40 bg-white p-4">
                <p className="text-sm font-bold text-gold-dark">Confirm your payment (UTR)</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-gold-dark">After paying via UPI, you'll see a <b>UTR number</b> in your payment success screen — paste it here. When the shop's bank sends the credit SMS with the <b>same UTR</b>, the two match and your order is <b>auto-confirmed</b>.</p>
                <input
                  value={utr} onChange={e => { setUtr(e.target.value); setUtrMsg(''); setUtrErr('') }}
                  placeholder="Enter UTR here (e.g. THQ42010724961)" autoCapitalize="characters"
                  className="mt-2 w-full rounded-btn border-2 border-gold-light px-3 py-2 text-xs font-semibold tracking-wide text-gold-dark outline-none focus:border-gold"
                />
                <button onClick={() => void saveUtr()} disabled={!utr.trim() || utrSaving}
                  className="mt-2 w-full rounded-btn bg-gold-dark px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-gold disabled:cursor-not-allowed disabled:opacity-40">
                  {utrSaving ? 'Saving…' : (utrMsg.includes('confirmed') ? 'UTR Matched ✓' : 'Submit UTR')}
                </button>
                {utrMsg && <p className="mt-1.5 text-[11px] font-semibold text-emerald-700">{utrMsg}</p>}
                {utrErr && <p className="mt-1.5 text-[11px] font-semibold text-red-600">{utrErr}</p>}
                <div className="my-3 h-px border-t border-dashed border-gold/30" />
                <p className="text-xs font-bold text-gold-dark">Or upload the payment screenshot</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-gold-dark">Attach the UPI screenshot so the shop can verify it manually.</p>
                <input
                  type="file" accept="image/*,.pdf"
                  onChange={e => { setScreenshot(e.target.files?.[0] || null); setUploadMsg(''); setUploadErr('') }}
                  className="mt-2 w-full text-xs"
                />
                {screenshot && (
                  <p className="mt-1.5 text-[11px] font-semibold text-emerald-700">Selected: {screenshot.name} ({(screenshot.size / 1024).toFixed(0)} KB)</p>
                )}
                <button onClick={() => void uploadScreenshot()} disabled={!screenshot || uploading}
                  className="mt-2 w-full rounded-btn bg-gold-dark px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-gold disabled:cursor-not-allowed disabled:opacity-40">
                  {uploading ? 'Uploading…' : (uploadMsg ? 'Screenshot uploaded ✓' : 'Upload Screenshot')}
                </button>
                {screenshotUrl && <img src={screenshotUrl} alt="Uploaded payment screenshot" className="mt-2 max-h-40 w-full rounded-card object-contain" />}
                {uploadMsg && <p className="mt-1.5 text-[11px] font-semibold text-emerald-700">{uploadMsg}</p>}
                {uploadErr && <p className="mt-1.5 text-[11px] font-semibold text-red-600">{uploadErr}</p>}
              </div>
            </div>
          )
        })()}
        {/* Collect-your-order QR — the shopkeeper's scanner reads this to find
            the order instantly (no typing, no misreads). */}
        {order.status !== 'Cancelled' && order.status !== 'Failed' && (
          <div className="mt-6 rounded-btn border-2 border-dashed border-emerald-300 bg-primary-light/30/60 p-4">
            <p className="text-sm font-bold text-primary">Your order QR — show this at the counter</p>
            <div className="mx-auto mt-3 w-fit rounded-card bg-white p-3 shadow-sm">
              <QRCodeSVG value={`DETOMSITE-ORDER:${order.id}`} size={168} level="M" bgColor="#ffffff" fgColor="#064E3B" className="h-auto w-40 max-w-[180px] sm:w-44" />
            </div>
            <p className="mx-auto mt-3 max-w-xs text-center text-xs leading-relaxed text-primary">The shop scans this QR to fetch your order. Also handy: your token number is <b>#{order.token}</b> — tell it to the counter if you prefer.</p>
          </div>
        )}
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link to="/orders" className="rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white hover:bg-primary-dark">Track Orders →</Link>
          <Link to="/shops" className="rounded-btn border px-5 py-2.5 text-sm font-bold text-gray-600 hover:bg-gray-50">Order More</Link>
        </div>
      </div>
    </div>
  )
}

/* Reviews */
function ReviewsPage() {
  const [reviews, setReviews] = useState<any[]>([]); const [loading, setLoading] = useState(true); const [f, setF] = useState({ shop_id: '', rating: 5, comment: '' }); const [msg, setMsg] = useState('')
  const [shops, setShops] = useState<Shop[]>([])
  useEffect(() => {
    Promise.all([
      api.get('/users/reviews').catch(() => ({ data: [] })),
      fetchShopsCached(),
    ]).then(([r, s]) => { setReviews(r.data || []); setShops(s) }).finally(() => setLoading(false))
  }, [])
  const submitReview = async (e: FormEvent) => {
    e.preventDefault(); setMsg('')
    try { await api.post('/users/reviews', f); setMsg('Review submitted!'); setF({ shop_id: '', rating: 5, comment: '' }) }
    catch (err: any) { setMsg(err?.response?.data?.detail || 'Failed') }
  }
  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-bold text-primary-dark">My Reviews</h1>
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div>
          <h2 className="mb-3 text-lg font-bold text-primary">Your Reviews</h2>
          {loading ? <p className="text-gray-400">Loading...</p> : reviews.length > 0 ? (
            <div className="space-y-3">
              {reviews.map((r: any, i: number) => (
                <div key={i} className="rounded-btn border bg-white p-4">
                  <div className="flex items-center justify-between">
                    <p className="font-bold text-gold-dark">{'★'.repeat(r.rating || 5)}</p>
                    {r.shop_name && <span className="text-xs font-semibold text-primary bg-primary-light/30 rounded-sm px-2 py-0.5">{r.shop_name}</span>}
                  </div>
                  <p className="text-sm text-gray-600 mt-1">{r.comment || 'No comment'}</p>
                  {r.created_at && <p className="text-xs text-gray-400 mt-1">{r.created_at}</p>}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-btn bg-white p-8 text-center border"><p className="text-gray-500">No reviews yet. Submit your first review!</p></div>
          )}
        </div>
        <div className="rounded-btn bg-white p-5 shadow-sm border h-fit">
          <h2 className="mb-3 text-lg font-bold text-primary">Write a Review</h2>
          {msg && <div className="mb-3 rounded-sm bg-primary-light/30 border px-3 py-2 text-sm text-primary">{msg}</div>}
          <form onSubmit={submitReview} className="space-y-3">
            <select value={f.shop_id} onChange={e => setF({...f, shop_id: e.target.value})} className="w-full rounded-btn border-2 px-4 py-2.5 text-sm outline-none" required>
              <option value="">Select Shop</option>
              {shops.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <select value={f.rating} onChange={e => setF({...f, rating: parseInt(e.target.value)})} className="w-full rounded-btn border-2 px-4 py-2.5 text-sm outline-none">
              {[5,4,3,2,1].map(r => <option key={r} value={r}>{'★'.repeat(r)}</option>)}
            </select>
            <textarea value={f.comment} onChange={e => setF({...f, comment: e.target.value})} className="w-full rounded-btn border-2 px-4 py-2.5 text-sm outline-none" placeholder="Your review..." rows={2} />
            <button type="submit" className="w-full rounded-btn bg-primary px-4 py-2.5 text-sm font-bold text-white hover:bg-primary-dark">Submit Review</button>
          </form>
        </div>
      </div>
    </div>
  )
}

/* Account */
function AccountPage() {
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  const [orders, setOrders] = useState<Order[]>([])
  useEffect(() => { fetchOrdersCached().then(list => setOrders(list.filter(o => o.student_name.toLowerCase() === (user.name || '').toLowerCase()))).catch(() => {}) }, [user.name])
  const totalSpent = orders.reduce((s, o) => s + o.total, 0)
  const active = orders.filter(o => o.status !== 'Completed' && o.status !== 'Cancelled').length

  const detail = [
    { l: 'Username', v: user.username || '—' },
    { l: 'Name', v: user.name || '—' },
    { l: 'Email', v: user.email || '—' },
    { l: 'Phone', v: user.phone || '—' },
    { l: 'Role', v: 'Student' },
    { l: 'Orders Placed', v: String(orders.length) },
    { l: 'Active Orders', v: String(active) },
    { l: 'Total Spent', v: `₹${totalSpent}` },
  ]

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-bold text-primary-dark">My Account</h1>
      <div className="mb-6 rounded-card bg-gradient-to-br from-emerald-800 to-emerald-700 p-6 text-white">
        <div className="flex items-center gap-4">
          <span className="flex h-16 w-16 items-center justify-center rounded-card bg-white/15 text-2xl font-black">{(user.name || 'U').charAt(0).toUpperCase()}</span>
          <div>
            <h2 className="text-2xl font-black">{user.name || 'Student'}</h2>
            <p className="text-primary/50">@{user.username || 'student'}</p>
          </div>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {detail.map(d => (
          <div key={d.l} className="rounded-btn border bg-white p-4">
            <p className="text-xs font-semibold text-gray-500">{d.l}</p>
            <p className="mt-1 font-bold text-primary-dark">{d.v}</p>
          </div>
        ))}
      </div>
      <p className="mt-6 rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3 text-sm text-primary">
        💡 Your account is private to you — orders are linked to your name and only you can see them here.
      </p>
    </div>
  )
}

/* Support */
const HELP_DESK_PHONE = '+916382603607'
function SupportPage() {
  const [f, setF] = useState({ category: 'Order Issue', title: '', description: '' }); const [msg, setMsg] = useState(''); const [err, setErr] = useState('')
  const user = JSON.parse(localStorage.getItem('user_data') || '{}')
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setMsg('')
    try { await api.post('/local/tickets', { ...f, name: user.name || 'Student', email: user.email || '', phone_number: user.phone || '' }); setMsg('Ticket submitted!'); setF({ category: 'Order Issue', title: '', description: '' }) }
    catch (err: any) { setErr(err?.response?.data?.detail || 'Failed') }
  }
  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-bold text-primary-dark">Support</h1>

      {/* Help Desk — direct call button */}
      <div className="mb-6 rounded-btn bg-primary-light/30 border border-primary-light/50 p-5">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-pill bg-primary text-white">
            <svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>
          </div>
          <div className="flex-1">
            <p className="text-sm font-bold text-primary-dark">Help Desk</p>
            <p className="text-xs text-primary">Need urgent help? Call us directly — we're available to assist you.</p>
            <a href={`tel:${HELP_DESK_PHONE}`} className="mt-2 inline-flex items-center gap-2 rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-primary active:scale-[0.98]">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>
              Call +91 63826 03607
            </a>
          </div>
        </div>
      </div>

      <div className="rounded-btn bg-white p-6 shadow-sm border">
        {msg && <div className="mb-4 rounded-btn bg-primary-light/30 border px-4 py-3 text-sm text-primary">{msg}</div>}
        {err && <div className="mb-4 rounded-btn bg-red-50 border px-4 py-3 text-sm text-red-600">{err}</div>}
        <form onSubmit={submit} className="space-y-4">
          <select value={f.category} onChange={e => setF({...f, category: e.target.value})} className="w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-primary-light/200">
            {['Order Issue', 'Payment Issue', 'Technical Issue', 'Other'].map(c => <option key={c}>{c}</option>)}
          </select>
          <input value={f.title} onChange={e => setF({...f, title: e.target.value})} className="w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-primary-light/200" placeholder="Title" required />
          <textarea value={f.description} onChange={e => setF({...f, description: e.target.value})} className="w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-primary-light/200" placeholder="Describe your issue..." rows={3} required />
          <button type="submit" className="rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white hover:bg-primary-dark">Submit Ticket →</button>
        </form>
      </div>
    </div>
  )
}

/* ─── App ─── */
export default function App() {
  return (
    <Router>
      <Routes>
        {/* Public pages — no login needed */}
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />

        {/* Everything else requires a valid login */}
        <Route path="/*" element={
          <RequireAuth>
            <Layout>
              <Routes>
                <Route path="/" element={<ShopsPage />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/shops" element={<ShopsPage />} />
                <Route path="/shop/:shopId" element={<ShopDetailPage />} />
                <Route path="/cart" element={<CartPage />} />
                <Route path="/orders" element={<OrdersPage />} />
                <Route path="/payment" element={<PaymentPage />} />
                <Route path="/order/:orderId" element={<OrderResultPage />} />
                <Route path="/reviews" element={<ReviewsPage />} />
                <Route path="/account" element={<AccountPage />} />
                <Route path="/support" element={<SupportPage />} />
                <Route path="*" element={<NavigateToLogin />} />
              </Routes>
            </Layout>
          </RequireAuth>
        } />
      </Routes>
    </Router>
  )
}

function NavigateToLogin() {
  const navigate = useNavigate(); const user = localStorage.getItem('access_token')
  useEffect(() => { navigate(user ? '/shops' : '/login') }, [])
  return null
}
