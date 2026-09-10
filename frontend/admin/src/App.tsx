import { useState, useEffect, FormEvent, useRef } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, useNavigate, useLocation } from 'react-router-dom'
import api from './services/api'

/* ─── Dark / light mode ───
   The admin portal is dark by default; a `light` class on <html> flips the
   palette (the stylesheet overrides the dark utilities). Module-level singleton
   so the toggle in the nav and every page stay in sync. */
const THEME_KEY = 'detomsite-admin-theme'
let currentLight = false
const themeListeners: Array<(d: boolean) => void> = []
function applyTheme(light: boolean) {
  currentLight = light
  document.documentElement.classList.toggle('light', light)
  document.documentElement.classList.toggle('dark', !light)
  try { localStorage.setItem(THEME_KEY, light ? 'light' : 'dark') } catch { /* ignore */ }
  themeListeners.forEach(fn => fn(light))
}
try {
  currentLight = localStorage.getItem(THEME_KEY) === 'light'
  document.documentElement.classList.toggle('light', currentLight)
  document.documentElement.classList.toggle('dark', !currentLight)
} catch { /* storage unavailable — stay dark */ }
function useTheme() {
  const [light, setLight] = useState(currentLight)
  useEffect(() => {
    const fn = (d: boolean) => setLight(d)
    themeListeners.push(fn)
    return () => { const i = themeListeners.indexOf(fn); if (i >= 0) themeListeners.splice(i, 1) }
  }, [])
  return { light, toggle: () => applyTheme(!currentLight) }
}
function ThemeButton({ className = '' }: { className?: string }) {
  const { light, toggle } = useTheme()
  return (
    <button type="button" onClick={toggle} aria-label="Toggle light mode" title="Toggle light/dark mode"
      className={`rounded-pill p-2 text-gray-400 transition-all hover:bg-gray-800 hover:text-white ${className}`}>
      {light
        ? <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>
        : <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>}
    </button>
  )
}

/* Password input with a show/hide toggle — respects light/dark theme. */
function PasswordField({ value, onChange, placeholder = '••••••', autoComplete, required = true, className = '' }: { value: string; onChange: (v: string) => void; placeholder?: string; autoComplete?: string; required?: boolean; className?: string }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} autoComplete={autoComplete} required={required}
        className={`w-full rounded-btn border border-gray-800 light:border-gray-200 bg-gray-900 light:bg-white px-4 py-3 pr-11 text-sm text-white light:text-gray-900 placeholder-gray-500 light:placeholder-gray-400 outline-none transition-all focus:border-amber-500 ${className}`} />
      <button type="button" onClick={() => setShow(!show)} tabIndex={-1} aria-label={show ? 'Hide password' : 'Show password'}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-sm p-1.5 text-gray-500 transition-colors hover:bg-gray-800 light:hover:bg-gray-100 hover:text-gold">
        {show
          ? <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><path d="m1 1 22 22" /></svg>
          : <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>}
      </button>
    </div>
  )
}

/* Display a stored timestamp (SQLite IST wall-clock or Supabase UTC ISO) as
   "11 Aug, 9:05 PM" in Asia/Kolkata. */
function fmtTime(createdAt?: string): string {
  const raw = String(createdAt || '').trim()
  if (!raw) return ''
  let iso = raw
  if (!/T/.test(raw) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(raw)) iso = raw.replace(' ', 'T') + '+05:30'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return raw.slice(0, 16)
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(d)
}

/* Order items cell — shows the FULL order (e.g. "2x Noodles, 4x Rice"). When
   the row is too narrow to fit it all, the text truncates and hovering the
   cell reveals the complete order in a tooltip. */
function OrderItemsCell({ items }: { items?: string }) {
  const text = String(items || '').trim() || '—'
  const lines = text.split(',').map(s => s.trim()).filter(Boolean)
  return (
    <div className="group relative max-w-[280px]">
      <p className="truncate text-gray-500" title={text}>{text}</p>
      {/* Full order on hover — appears whenever the cell text is clipped */}
      <div className="pointer-events-none absolute left-0 top-full z-30 mt-1 hidden w-max max-w-xs rounded-btn border border-gray-700 bg-gray-900 px-3 py-2 shadow-2xl group-hover:block">
        {lines.length > 1 ? (
          <ul className="space-y-1">
            {lines.map((l, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs font-medium text-gray-200">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-pill bg-gold" />{l}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs font-medium text-gray-200">{text}</p>
        )}
      </div>
    </div>
  )
}

/* ─── Types ─── */

/* ─── Layout ─── */
function Layout({ children }: { children: React.ReactNode }) {
  const [menu, setMenu] = useState(false)
  const [notifs, setNotifs] = useState<any[]>([])
  const [notifOpen, setNotifOpen] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)
  const admin = JSON.parse(localStorage.getItem('admin_user') || '{}')
  const path = useLocation().pathname
  const logout = () => { localStorage.removeItem('admin_token'); localStorage.removeItem('admin_user'); window.location.href = '/login' }

  /* Close the notification dropdown when clicking outside it */
  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

  useEffect(() => {
    // Admin bell — vendor product changes & new registrations land here.
    // Only polls while the tab is actually visible, so a backgrounded admin
    // tab stops hammering the backend.
    const load = () => { if (document.visibilityState === 'visible') api.get('/admin/notifications').then(r => setNotifs(r.data || [])).catch(() => {}) }
    load(); const t = setInterval(load, 30000); return () => clearInterval(t)
  }, [])
  const nav = [
    { p: '/dashboard', l: 'Dashboard' },
    { p: '/users', l: 'Users' },
    { p: '/vendors', l: 'Vendors' },
    { p: '/orders', l: 'Orders' },
    { p: '/payments', l: 'Payments' },
    { p: '/sms', l: 'SMS' },
    { p: '/revenue', l: 'Revenue' },
    { p: '/feedback', l: 'Feedback' },
    { p: '/reviews', l: 'Reviews' },
    { p: '/settings', l: 'Settings' },
  ]
  return (
    <div className="min-h-screen bg-gray-950">
      <nav className="sticky top-0 z-50 border-b border-gray-800 bg-gray-950/90 backdrop-blur-lg">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link to="/dashboard" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-btn bg-gold text-sm font-black text-white">D</span>
            <span className="text-lg font-black text-white max-sm:hidden">Admin Portal</span>
          </Link>
          <div className="hidden items-center gap-1 md:flex">
            {nav.map(item => (
              <Link key={item.p} to={item.p} className={`rounded-pill px-3 py-2 text-sm font-semibold transition-all ${path === item.p ? 'bg-gold text-black' : 'text-gray-400 hover:bg-gray-800 hover:text-white'}`}>{item.l}</Link>
            ))}
            <ThemeButton />
            <div ref={notifRef} className="relative">
              <button onClick={() => setNotifOpen(!notifOpen)} className="rounded-pill px-2 py-2 text-sm text-gray-400 transition-all hover:bg-gray-800 hover:text-white">
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" /><path d="M10 20a2.2 2.2 0 0 0 4 0" /></svg>
                {notifs.length > 0 && <span className="ml-1 text-xs font-bold text-gold">{notifs.length}</span>}
              </button>
              {notifOpen && (
                <div className="absolute right-0 top-12 z-50 w-80 rounded-card border border-gray-800 bg-gray-900 p-3 shadow-2xl">
                  <h3 className="mb-2 px-1 text-sm font-bold text-gold">Notifications</h3>
                  <div className="max-h-72 space-y-1 overflow-y-auto">
                    {notifs.map(n => (
                      <div key={n.id} className="rounded-btn bg-gray-800/60 px-3 py-2.5 text-sm">
                        <p className="font-semibold text-white">{n.title}</p>
                        <p className="text-xs text-gray-400">{n.message}</p>
                      </div>
                    ))}
                    {notifs.length === 0 && <p className="px-3 py-2 text-sm text-gray-500">No notifications</p>}
                  </div>
                </div>
              )}
            </div>
            <span className="ml-2 text-sm text-gray-500">{admin.name || 'Admin'}</span>
            <button onClick={logout} className="ml-2 rounded-pill bg-red-900/30 px-3 py-2 text-sm font-semibold text-red-400 hover:bg-red-900/50">Logout</button>
          </div>
          <button className="rounded-pill p-2 text-gray-400 md:hidden" onClick={() => setMenu(!menu)}>{menu ? '✕' : '☰'}</button>
        </div>
        {menu && (
          <div className="border-t border-gray-800 px-4 py-3 md:hidden">
            {nav.map(item => (<Link key={item.p} to={item.p} onClick={() => setMenu(false)} className={`block rounded-btn px-4 py-2.5 text-sm font-semibold ${path === item.p ? 'bg-gold text-black' : 'text-gray-400'}`}>{item.l}</Link>))}
            <ThemeButton />
            <button onClick={logout} className="block w-full rounded-btn px-4 py-2.5 text-left text-sm font-semibold text-red-400">Logout</button>
          </div>
        )}
      </nav>
      <main className="text-gray-200">{children}</main>
    </div>
  )
}

/* ─── Pages ─── */

/* Login */
function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [err, setErr] = useState(''); const [loading, setLoading] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setLoading(true)
    try {
      const res = await api.post('/admin/login', { username, password })
      localStorage.setItem('admin_token', res.data.access_token)
      localStorage.setItem('admin_user', JSON.stringify(res.data.user))
      navigate('/dashboard')
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Invalid credentials') }
    finally { setLoading(false) }
  }
  return (
    <div className="relative min-h-screen lg:grid lg:grid-cols-2 bg-gray-950">
      <div className="absolute right-4 top-4 z-20"><ThemeButton /></div>
      {/* Mobile background — faded food photo (visible below lg only) */}
      <div className="absolute inset-0 overflow-hidden lg:hidden">
        <img
          src="https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1000&q=80"
          alt=""
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="h-full w-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-gray-950/85 via-gray-950/65 to-gray-950/85" />
      </div>
      {/* Left — brand panel with food photo (desktop only) */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden bg-gradient-to-br from-gray-950 via-gray-900 to-amber-950 p-12 text-white">
        <img
          src="https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1000&q=80"
          alt="A spread of fresh dishes"
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="absolute inset-0 h-full w-full object-cover opacity-35"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-gray-950/95 via-gray-950/60 to-gray-950/20" />
        <div className="relative">
          <span className="inline-flex items-center gap-2 rounded-pill border border-amber-400/25 bg-gold/10 px-4 py-1.5 text-xs font-bold uppercase tracking-widest text-gold backdrop-blur-sm"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17.5v.5" /></svg> DETOMSITE</span>
          <h2 className="mt-8 max-w-md text-4xl font-black leading-tight">Your campus commerce,<br />under control.</h2>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-gray-300">Approve shops, watch revenue grow, and track your monthly 5% share — all from one dashboard.</p>
          <ul className="mt-8 space-y-4 text-sm text-gray-100">
            {[
              ['Approve & manage shops', 'One click to approve, suspend or remove'],
              ['Live revenue & monthly share', 'Track what is expected, done and pending'],
              ['Everything at a glance', 'Orders, payments, feedback and more'],
            ].map(([t, s]) => (
              <li key={t} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-gold/15 text-gold"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg></span>
                <span><b>{t}</b><span className="block text-xs font-normal text-gray-400">{s}</span></span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-gray-500">© {new Date().getFullYear()} DETOMSITE · Admin Portal</p>
      </div>
      {/* Right — login form (sits above the faded mobile photo) */}
      <div className="relative flex min-h-screen items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 text-center">
            <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-card bg-gold/15 text-gold">
              <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17.5v.5" /></svg>
            </span>
            <h1 className="mt-4 text-3xl font-black text-white">Admin Portal</h1>
            <p className="mt-1 text-sm text-gray-400">Secure administration login</p>
          </div>
          <div className="rounded-card border border-gray-800 bg-gray-900/50 p-8 backdrop-blur-sm">
            {err && <div className="mb-4 rounded-btn bg-red-900/30 border border-red-900/50 px-4 py-3 text-sm font-medium text-red-400">{err}</div>}
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-400"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" /></svg>Username</label>
                <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full rounded-btn border border-gray-800 bg-gray-900 px-4 py-3 text-sm text-white placeholder-gray-500 outline-none transition-all focus:border-amber-500" placeholder="Admin username" required />
              </div>
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-400"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>Password</label>
                <PasswordField value={password} onChange={setPassword} placeholder="Your password" autoComplete="current-password" />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-gold px-4 py-3.5 text-sm font-bold text-black hover:bg-gold active:scale-[0.99] disabled:opacity-40">{loading ? 'Authenticating...' : 'Login'}</button>
              <div className="text-center">
                <Link to="/forgot-password" className="text-xs font-bold text-gold hover:text-gold">Forgot password?</Link>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}

/* Forgot Password — a single 6-digit code is emailed to the registered
   address (never shown in the UI). The backend verifies the code and updates
   the password in the DB. */
function ForgotPassword() {
  const [step, setStep] = useState<'request' | 'otp'>('request')
  const [identifier, setIdentifier] = useState('')
  const [otp, setOtp] = useState('')
  const [pw, setPw] = useState(''); const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState(''); const [info, setInfo] = useState(''); const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  const requestOtp = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setInfo(''); setLoading(true)
    try {
      const res = await api.post('/users/forgot-password', { identifier })
      setInfo(res.data?.message || 'A 6-digit code was sent to your registered email.')
      setStep('otp')
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Request failed') }
    finally { setLoading(false) }
  }
  const resetPw = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setInfo('')
    if (pw !== confirm) { setErr('Passwords do not match'); return }
    if (pw.length < 4) { setErr('Password must be at least 4 characters'); return }
    setLoading(true)
    try { await api.post('/users/reset-password', { identifier, otp, new_password: pw }); setDone(true) }
    catch (err: any) { setErr(err?.response?.data?.detail || 'Reset failed') }
    finally { setLoading(false) }
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
        <div className="absolute right-4 top-4"><ThemeButton /></div>
        <div className="w-full max-w-sm rounded-card border border-gray-800 bg-gray-900/50 p-8 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-pill bg-primary-dark/40 text-primary">✓</span>
          <h1 className="mt-4 text-2xl font-bold text-white">Password Updated!</h1>
          <p className="mt-2 text-sm text-gray-400">Sign in with your new password.</p>
          <Link to="/login" className="mt-6 block w-full rounded-btn bg-gold px-6 py-3 text-sm font-bold text-black hover:bg-gold">Go to Login</Link>
        </div>
      </div>
    )
  }

  const inputCls = "w-full rounded-btn border border-gray-800 bg-gray-900 px-4 py-3 text-sm text-white placeholder-gray-500 outline-none transition-all focus:border-amber-500"
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4 py-12">
      <div className="absolute right-4 top-4"><ThemeButton /></div>
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-white">Forgot Password</h1>
          <p className="mt-1 text-xs text-gray-500">Step {step === 'request' ? 1 : 2} of 2 · {step === 'request' ? 'Reset your password' : 'Enter the code & set a new password'}</p>
        </div>
        <div className="rounded-card border border-gray-800 bg-gray-900/50 p-8">
          {err && <div className="mb-4 rounded-btn bg-red-900/30 border border-red-900/50 px-4 py-3 text-sm text-red-400">{err}</div>}
          {info && <div className="mb-4 rounded-btn bg-primary-dark/30 border border-primary/20 px-4 py-3 text-sm text-primary">{info}</div>}
          {step === 'request' && (
            <form onSubmit={requestOtp} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-400">Username or Email</label>
                <input type="text" value={identifier} onChange={e => setIdentifier(e.target.value)} className={inputCls} placeholder="Your username or registered email" required />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-gold px-4 py-3.5 text-sm font-bold text-black hover:bg-gold disabled:opacity-40">{loading ? 'Sending...' : 'Send Code'}</button>
            </form>
          )}
          {step === 'otp' && (
            <form onSubmit={resetPw} className="space-y-4">
              <p className="text-xs leading-relaxed text-gray-400">A <b>6-digit code</b> was emailed to the address on your account. Enter it with your new password below — the code expires in 15 minutes.</p>
              <input type="text" inputMode="numeric" value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} className={`${inputCls} text-center text-2xl font-black tracking-[0.4em]`} placeholder="••••••" required />
              <PasswordField value={pw} onChange={setPw} placeholder="New password (min 4 chars)" autoComplete="new-password" />
              <PasswordField value={confirm} onChange={setConfirm} placeholder="Confirm new password" autoComplete="new-password" />
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-gold px-4 py-3.5 text-sm font-bold text-black hover:bg-gold disabled:opacity-40">{loading ? 'Saving...' : 'Verify Code & Update Password'}</button>
            </form>
          )}
          {step !== 'request' && (
            <p className="mt-5 text-center"><button type="button" onClick={() => { setStep('request'); setErr(''); setInfo('') }} className="text-xs font-bold text-gold">← Start over</button></p>
          )}
          <p className="mt-5 text-center text-sm text-gray-500">Remembered it? <Link to="/login" className="font-bold text-gold">Sign In</Link></p>
        </div>
      </div>
    </div>
  )
}

/* Dashboard — serves the last snapshot instantly, then refreshes in the
   background, so the page opens immediately on every visit. */
const ADMIN_DASH_CACHE_KEY = 'detomsite-admin-dash-cache'
function Dashboard() {
  const [stats, setStats] = useState<any>({}); const [orders, setOrders] = useState<any[]>([]); const [loading, setLoading] = useState(true)
  useEffect(() => {
    try {
      const cached = JSON.parse(localStorage.getItem(ADMIN_DASH_CACHE_KEY) || 'null')
      if (cached && Date.now() - cached.t < 30000) {
        setStats(cached.stats || {}); setOrders(cached.orders || []); setLoading(false)
      }
    } catch { /* ignore — fall through to a fresh fetch */ }
    Promise.all([
      api.get('/admin/dashboard').catch(() => ({ data: { stats: {} } })),
      api.get('/admin/orders').catch(() => ({ data: [] })),
    ]).then(([s, o]) => {
      setStats(s.data?.stats || {}); setOrders(o.data || [])
      try { localStorage.setItem(ADMIN_DASH_CACHE_KEY, JSON.stringify({ t: Date.now(), stats: s.data?.stats || {}, orders: o.data || [] })) } catch { /* ignore */ }
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex items-center justify-center py-20 text-gray-500">Loading...</div>

  const cards = [
    { l: 'Total Shops', v: stats.total_shops || 0 },
    { l: 'Approved', v: stats.approved_shops || 0 },
    { l: 'Pending Approval', v: stats.pending_approvals || 0 },
    { l: 'Total Orders', v: stats.total_orders || 0 },
    { l: "Today's Orders", v: stats.today_orders || 0 },
    { l: 'Revenue', v: `₹${(stats.total_revenue || 0).toLocaleString('en-IN')}` },
    { l: "Admin's 5% Share", v: `₹${(stats.total_service_fee || 0).toLocaleString('en-IN')}` },
    { l: 'Pending Payments', v: stats.pending_payments || 0 },
  ]

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6"><h1 className="text-2xl font-bold text-white">Dashboard</h1><p className="text-sm text-gray-400">Platform overview</p></div>
      <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(c => (
          <div key={c.l} className="rounded-btn border border-gray-800 bg-gray-900/50 p-4">
            <p className="text-xs font-semibold text-gray-400">{c.l}</p>
            <p className="mt-1 text-2xl font-bold text-white">{c.v}</p>
          </div>
        ))}
      </div>
      <div className="rounded-btn border border-gray-800 bg-gray-900/50 p-5">
        <h2 className="mb-3 text-lg font-bold text-white">Recent Orders</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Token', 'Shop', 'Student', 'Phone', 'Items', 'Amount', 'Status', 'Placed'].map(h => <th key={h} className="px-4 py-3 font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {orders.map((o: any) => (
                <tr key={o.id} className="border-b border-gray-800/50 text-gray-300">
                  <td className="px-4 py-3 font-bold">{o.token}</td>
                  <td className="px-4 py-3">{o.shop_name}</td>
                  <td className="px-4 py-3">{o.student_name}</td>
                  <td className="px-4 py-3 text-gray-500">{o.student_phone || '—'}</td>
                  <td className="px-4 py-3"><OrderItemsCell items={o.items} /></td>
                  <td className="px-4 py-3">₹{o.total}</td>
                  <td className="px-4 py-3"><span className="rounded-sm bg-gray-800 px-2 py-0.5 text-xs text-gray-300">{o.status}</span></td>
                  <td className="px-4 py-3 text-gray-500">{fmtTime(o.created_at) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {orders.length === 0 && <p className="py-4 text-center text-gray-500">No orders</p>}
        </div>
      </div>
    </div>
  )
}

/* Users */
function UsersPage() {
  const [users, setUsers] = useState<any[]>([]); const [tab, setTab] = useState<'all' | 'students' | 'shopkeepers'>('all'); const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [msg, setMsg] = useState(''); const [err, setErr] = useState('')
  useEffect(() => {
    setLoading(true)
    const endpoint = tab === 'all' ? '/admin/users' : tab === 'students' ? '/admin/users/students' : '/admin/users/shopkeepers'
    api.get(endpoint).then(r => setUsers(r.data || [])).finally(() => setLoading(false))
  }, [tab])
  const filtered = users.filter((u: any) => !search || `${u.username} ${u.name} ${u.email || ''} ${u.phone || ''}`.toLowerCase().includes(search.toLowerCase()))

  /* Permanently delete a user (with their sessions/feedback/etc.) so their
     username/email become re-registrable — fixes "email already taken" after
     a manual DB delete left stale data behind. */
  const deleteUser = async (u: any) => {
    if (!window.confirm(`Delete ${u.username} permanently? Their account, sessions and feedback are removed too — the username and email can be registered again.`)) return
    try {
      await api.delete(`/admin/users/${u.id}`)
      setMsg(`Deleted ${u.username} — the username and email can now be used again.`)
      setErr('')
      setUsers(users.filter((x: any) => x.id !== u.id))
    } catch (e: any) { setErr(e?.response?.data?.detail || 'Could not delete user') }
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-bold text-white">Registered Users ({filtered.length})</h1>
      {msg && <div className="mb-4 rounded-btn bg-primary-dark/30 border border-primary/20 px-4 py-3 text-sm text-primary">{msg}</div>}
      {err && <div className="mb-4 rounded-btn bg-red-900/30 border border-red-900/50 px-4 py-3 text-sm text-red-300">{err}</div>}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {(['all', 'students', 'shopkeepers'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`rounded-pill px-4 py-2 text-sm font-semibold ${tab === t ? 'bg-gold text-black' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>{t === 'all' ? 'All Users' : t.charAt(0).toUpperCase() + t.slice(1)}</button>
        ))}
        <div className="relative min-w-[200px] flex-1 max-w-xs ml-auto">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg></span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, username, email…" className="w-full rounded-btn border border-gray-800 bg-gray-900 py-2.5 pl-9 pr-3 text-sm text-white placeholder-gray-500 outline-none focus:border-amber-500" />
        </div>
      </div>
      <div className="rounded-btn border border-gray-800 bg-gray-900/50 overflow-x-auto">
        {loading ? <p className="p-8 text-center text-gray-500">Loading...</p> : (
          <table className="w-full min-w-[700px] text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['S.No.', 'Username', 'Name', 'Email', 'Phone', 'Role', 'Joined', 'Actions'].map(h => <th key={h} className="px-4 py-3 font-bold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.map((u: any, i: number) => (
                <tr key={u.id} className="border-b border-gray-800/50 text-gray-300">
                  <td className="px-4 py-3 text-gray-500">{i + 1}</td>
                  <td className="px-4 py-3 font-semibold">{u.username}</td>
                  <td className="px-4 py-3">{u.name}</td>
                  <td className="px-4 py-3 text-gray-500">{u.email || '—'}</td>
                  <td className="px-4 py-3">{u.phone || '—'}</td>
                  <td className="px-4 py-3"><span className={`rounded-sm px-2 py-0.5 text-xs ${u.role === 'admin' ? 'bg-gold-light/20 text-gold' : u.role === 'student' ? 'bg-primary-dark/30 text-primary' : 'bg-blue-900/30 text-blue-400'}`}>{u.role}</span></td>
                  <td className="px-4 py-3 text-gray-500">{u.created_at}</td>
                  <td className="px-4 py-3">
                    {u.role !== 'admin' ? (
                      <button onClick={() => deleteUser(u)} title="Delete permanently — frees the username & email for re-registration"
                        className="rounded-sm bg-red-900/40 px-2.5 py-1 text-[11px] font-bold text-red-300 transition-colors hover:bg-red-900/60">Delete</button>
                    ) : <span className="text-xs text-gray-600">—</span>}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-gray-500">No users found</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* Vendors */
function VendorsPage() {
  const [vendors, setVendors] = useState<any[]>([]); const [products, setProducts] = useState<any[]>([]); const [selectedShop, setSelectedShop] = useState(''); const [msg, setMsg] = useState(''); const [loading, setLoading] = useState(true)
  const [logs, setLogs] = useState<any>(null); const [logsShop, setLogsShop] = useState('')
  const [vendorFilter, setVendorFilter] = useState<'approved' | 'pending' | 'suspended' | 'removed'>('approved')
  const [todayOrders, setTodayOrders] = useState<any[]>([]); const [todayShop, setTodayShop] = useState(''); const [todayCount, setTodayCount] = useState(0); const [todayShopName, setTodayShopName] = useState('')
  const [settingsShop, setSettingsShop] = useState(''); const [settingsForm, setSettingsForm] = useState({ upi_id: '', upi_enabled: true, cod_enabled: true, phone: '' }); const [settingsSaving, setSettingsSaving] = useState(false)
  const [editProduct, setEditProduct] = useState<any>(null); const [productForm, setProductForm] = useState({ name: '', price: '', category: 'Food', description: '', inventory: '0', prep_time: '10', available: true }); const [productSaving, setProductSaving] = useState(false); const [productShopId, setProductShopId] = useState('')
  const load = async () => {
    setLoading(true)
    try { const r = await api.get('/admin/vendors'); setVendors(r.data || []) } catch {}
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const approve = async (id: string) => {
    try { await api.post(`/admin/vendors/${id}/approve`); setMsg('Shop approved!'); load(); setSelectedShop('') } catch {}
  }
  const reject = async (id: string) => {
    try { await api.post(`/admin/vendors/${id}/reject`, { action: 'reject' }); setMsg('Shop rejected'); load() } catch {}
  }
  const adminAction = async (id: string, action: 'suspend' | 'remove' | 'restore') => {
    try {
      await api.post(`/admin/vendors/${id}/admin-action`, { action })
      setMsg(action === 'restore' ? 'Shop restored' : action === 'remove' ? 'Shop removed' : 'Shop suspended')
      load()
    } catch {}
  }
  const viewProducts = async (shopId: string) => {
    setSelectedShop(selectedShop === shopId ? '' : shopId)
    setEditProduct(null); setProductShopId(shopId)
    try { const r = await api.get(`/admin/vendors/${shopId}/products`); setProducts(r.data || []) } catch {}
  }
  const openSettings = (v: any) => {
    setSettingsShop(settingsShop === v.id ? '' : v.id)
    setSettingsForm({ upi_id: v.upi_id || '', upi_enabled: !!v.upi_enabled, cod_enabled: !!v.cod_enabled, phone: v.phone || '' })
  }
  const saveSettings = async (shopId: string) => {
    setSettingsSaving(true)
    try {
      await api.patch(`/admin/vendors/${shopId}/settings`, settingsForm)
      setMsg('Shop settings updated!'); setSettingsShop(''); load()
    } catch { setMsg('Could not update settings') }
    finally { setSettingsSaving(false) }
  }
  const saveProduct = async (shopId: string) => {
    if (!productForm.name || !productForm.price) { setMsg('Name and price are required'); return }
    setProductSaving(true)
    try {
      const body = { ...productForm, price: parseInt(productForm.price) || 0, inventory: parseInt(productForm.inventory) || 0, prep_time: parseInt(productForm.prep_time) || 10 }
      if (editProduct) {
        await api.patch(`/admin/vendors/${shopId}/products/${editProduct.id}`, body)
        setMsg('Product updated!')
      } else {
        await api.post(`/admin/vendors/${shopId}/products`, body)
        setMsg('Product added!')
      }
      setEditProduct(null); setProductForm({ name: '', price: '', category: 'Food', description: '', inventory: '0', prep_time: '10', available: true })
      const r = await api.get(`/admin/vendors/${shopId}/products`); setProducts(r.data || [])
    } catch { setMsg('Could not save product') }
    finally { setProductSaving(false) }
  }
  const deleteProduct = async (shopId: string, productId: string) => {
    if (!window.confirm('Delete this product permanently?')) return
    try {
      await api.delete(`/admin/vendors/${shopId}/products/${productId}`)
      setMsg('Product deleted'); setProducts(products.filter((p: any) => p.id !== productId))
    } catch { setMsg('Could not delete product') }
  }
  const [logsErr, setLogsErr] = useState('')
  const viewLogs = async (shopId: string) => {
    setLogsShop(shopId); setLogs(null); setLogsErr('')
    try { const r = await api.get(`/admin/vendors/${shopId}/logs`); setLogs(r.data || null); if (!r.data) setLogsErr('No data returned for this shop') }
    catch { setLogsErr('Could not load logs — the backend may need a restart to pick up the new endpoint.') }
  }
  const toggleShop = async (shopId: string, currentPresent: boolean) => {
    try {
      const newPresent = !currentPresent
      await api.patch(`/admin/vendors/${shopId}/present`, { present: newPresent })
      setMsg(newPresent ? 'Shop opened — accepting orders' : 'Shop closed — not accepting orders')
      load()
    } catch { setMsg('Could not update shop status') }
  }
  const viewTodayOrders = async (shopId: string, shopName: string) => {
    setTodayShop(shopId); setTodayOrders([]); setTodayCount(0); setTodayShopName(shopName)
    try {
      const r = await api.get(`/admin/vendors/${shopId}/orders/today`)
      setTodayOrders(r.data?.orders || []); setTodayCount(r.data?.count || 0)
    } catch { setMsg('Could not load today orders') }
  }

  const filteredVendors = vendors.filter((v: any) =>
    vendorFilter === 'approved' ? v.approval_status === 'Approved'
      : vendorFilter === 'pending' ? v.approval_status === 'Pending Approval'
        : vendorFilter === 'suspended' ? v.approval_status === 'Suspended'
          : v.approval_status === 'Removed')
  const filterCount = (id: 'approved' | 'pending' | 'suspended' | 'removed') => vendors.filter((v: any) =>
    id === 'approved' ? v.approval_status === 'Approved'
      : id === 'pending' ? v.approval_status === 'Pending Approval'
        : id === 'suspended' ? v.approval_status === 'Suspended'
          : v.approval_status === 'Removed').length

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-bold text-white">Vendors Management</h1>
      {msg && <div className="mb-4 rounded-btn bg-primary-dark/30 border border-primary/20 px-4 py-3 text-sm text-primary">{msg}</div>}

      {/* Status filter — Approved is the default; no "All" option */}
      <div className="mb-4 flex flex-wrap gap-2">
        {([
          { id: 'approved', l: 'Approved' },
          { id: 'pending', l: 'Pending' },
          { id: 'suspended', l: 'Suspended' },
          { id: 'removed', l: 'Removed' },
        ] as const).map(f => (
          <button key={f.id} onClick={() => setVendorFilter(f.id)}
            className={`rounded-pill px-4 py-2 text-sm font-semibold transition-all ${vendorFilter === f.id ? 'bg-gold text-black' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {f.l} ({filterCount(f.id)})
          </button>
        ))}
      </div>

      <h2 className="mb-3 text-lg font-bold text-gray-400">{vendorFilter === 'approved' ? 'Approved' : vendorFilter === 'pending' ? 'Pending' : vendorFilter === 'suspended' ? 'Suspended' : 'Removed'} Vendors ({filteredVendors.length})</h2>
      {loading ? <p className="text-center text-gray-500 py-8">Loading...</p> : (
        <div className="space-y-3">
          {/* The number is computed from the row position (not the DB id), so
              it stays 1, 2, 3… even after vendors are removed — the list
              re-numbers itself automatically. */}
          {filteredVendors.map((v: any, i: number) => (
            <div key={v.id} className="rounded-btn border border-gray-800 bg-gray-900/50 p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-bold text-white"><span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-pill bg-gray-800 text-xs font-bold text-gold">{i + 1}</span>{v.name}</h3>
                  <p className="text-sm text-gray-400">{v.shopkeeper_name} · {v.category}</p>
                  {/* Contact details — the admin can reach the vendor directly */}
                  <p className="mt-1 text-xs text-gray-500"><span className="text-gray-400">📞</span> {v.phone || '—'} {v.shopkeeper_email ? <span className="text-gray-600">· {v.shopkeeper_email}</span> : null}</p>
                  <p className="text-xs text-gray-500">Orders: {v.orders_today} today · Revenue: ₹{v.revenue_today}</p>
                  {v.approval_status === 'Approved' && (
                    <p className="mt-1 flex items-center gap-1.5 text-xs">
                      <span className={`inline-block h-2 w-2 rounded-pill ${v.present ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
                      <span className={`font-bold ${v.present ? 'text-primary' : 'text-red-400'}`}>{v.present ? 'Open' : 'Closed'}</span>
                      <span className="text-gray-600">· {v.present ? 'Accepting orders' : 'Not accepting orders'}</span>
                    </p>
                  )}
                  {/* UPI status at a glance — set & enabled = green, set but off = yellow, not set = red */}
                  <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                    {v.upi_id ? (
                      <span className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 font-bold ${v.upi_enabled ? 'bg-primary-dark/30 text-primary' : 'bg-yellow-900/30 text-yellow-400'}`}>
                        <span className={`inline-block h-1.5 w-1.5 rounded-pill ${v.upi_enabled ? 'bg-emerald-400' : 'bg-yellow-400'}`} />
                        UPI {v.upi_enabled ? 'Set' : 'Off'}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-pill bg-red-900/30 px-2 py-0.5 font-bold text-red-400">
                        <span className="inline-block h-1.5 w-1.5 rounded-pill bg-red-400" />UPI Not Set
                      </span>
                    )}
                    {v.upi_id && <span className="font-mono text-gray-500">{v.upi_id}</span>}
                    <span className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 font-bold ${v.cod_enabled ? 'bg-blue-900/30 text-blue-400' : 'bg-gray-800 text-gray-500'}`}>
                      <span className={`inline-block h-1.5 w-1.5 rounded-pill ${v.cod_enabled ? 'bg-blue-400' : 'bg-gray-600'}`} />COD {v.cod_enabled ? 'On' : 'Off'}
                    </span>
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-sm px-2 py-1 text-xs font-semibold ${v.approval_status === 'Approved' ? 'bg-primary-dark/30 text-primary' : v.approval_status === 'Rejected' ? 'bg-red-900/30 text-red-400' : v.approval_status === 'Suspended' ? 'bg-yellow-900/30 text-yellow-400' : v.approval_status === 'Removed' ? 'bg-red-900/40 text-red-300' : 'bg-gold-light/20 text-gold'}`}>{v.approval_status}</span>
                  {v.approval_status === 'Pending Approval' && (
                    <>
                      <button onClick={() => approve(v.id)} className="rounded-sm bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary">Approve</button>
                      <button onClick={() => reject(v.id)} className="rounded-sm bg-red-900/50 px-3 py-1.5 text-xs font-bold text-red-400 hover:bg-red-900/70">Reject</button>
                    </>
                  )}
                  {v.approval_status !== 'Removed' ? (
                    <>
                      <button onClick={() => adminAction(v.id, 'suspend')} className="rounded-sm bg-yellow-900/30 px-3 py-1.5 text-xs font-semibold text-yellow-400 hover:bg-yellow-900/50">Suspend</button>
                      <button onClick={() => adminAction(v.id, 'remove')} className="rounded-sm bg-red-900/40 px-3 py-1.5 text-xs font-semibold text-red-300 hover:bg-red-900/60">Remove</button>
                    </>
                  ) : (
                    <button onClick={() => adminAction(v.id, 'restore')} className="rounded-sm bg-primary-dark/30 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary-dark/50">Restore</button>
                  )}
                  {v.approval_status === 'Approved' && (
                    <button onClick={() => toggleShop(v.id, !!v.present)}
                      title={v.present ? 'Close this shop — stop accepting orders' : 'Open this shop — start accepting orders'}
                      className={`rounded-sm px-3 py-1.5 text-xs font-bold transition-colors ${v.present ? 'bg-red-600 text-white hover:bg-red-500' : 'bg-primary text-white hover:bg-primary'}`}>
                      {v.present ? 'Stop' : 'Start'}
                    </button>
                  )}
                  <button onClick={() => viewProducts(v.id)} className="rounded-sm bg-gray-800 px-3 py-1.5 text-xs font-semibold text-gray-300 hover:bg-gray-700">Products</button>
                  {v.approval_status === 'Approved' && (
                    <button onClick={() => openSettings(v)} className={`rounded-sm px-3 py-1.5 text-xs font-semibold transition-colors ${settingsShop === v.id ? 'bg-gold text-black' : 'bg-purple-900/30 text-purple-400 hover:bg-purple-900/50'}`}>⚙ Settings</button>
                  )}
                  {v.approval_status === 'Approved' && (
                    <button onClick={() => viewTodayOrders(v.id, v.name)} className="rounded-sm bg-sky-900/30 px-3 py-1.5 text-xs font-semibold text-sky-400 hover:bg-sky-900/50">Today's Orders</button>
                  )}
                  <button onClick={() => viewLogs(v.id)} className="rounded-sm bg-gold-light/20 px-3 py-1.5 text-xs font-semibold text-gold hover:bg-gold-light/30">Logs</button>
                </div>
              </div>
              {todayShop === v.id && (() => {
                /* Time-slot filter: before 12:30 PM → morning orders;
                   after 12:30 PM → afternoon orders (12:30 PM–6 PM),
                   excluding morning. */
                const now = new Date()
                const istHour = parseInt(new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit', hour12: false }).format(now))
                const istMinute = parseInt(new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', minute: '2-digit', hour12: false }).format(now))
                const minsSinceMidnight = istHour * 60 + istMinute
                const isAfternoon = minsSinceMidnight >= 750 // 12:30 PM = 750 mins

                const slotFiltered = todayOrders.filter((o: any) => {
                  const raw = String(o.created_at || '').trim()
                  if (!raw) return true
                  let iso = raw
                  if (!/T/.test(raw) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(raw)) iso = raw.replace(' ', 'T') + '+05:30'
                  const d = new Date(iso)
                  if (isNaN(d.getTime())) return true
                  const h = parseInt(new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', hour12: false }).format(d))
                  const m = parseInt(new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', minute: '2-digit', hour12: false }).format(d))
                  const orderMins = h * 60 + m
                  if (isAfternoon) return orderMins >= 750 // after 12:30 PM
                  return orderMins < 750 // before 12:30 PM
                })
                const slotLabel = isAfternoon ? 'Afternoon (12:30 PM – 6:00 PM)' : 'Morning (before 12:30 PM)'
                return (
                  <div className="mt-4 border-t border-gray-800 pt-4">
                    <h4 className="mb-1 text-sm font-bold text-gray-400">Today's Orders — {todayShopName}</h4>
                    <p className="mb-2 text-xs text-gold font-semibold">📂 {slotLabel} · {slotFiltered.length} order{slotFiltered.length === 1 ? '' : 's'}</p>
                    {slotFiltered.length > 0 ? (
                      <div className="max-h-72 overflow-y-auto rounded-sm border border-gray-800">
                        <table className="w-full text-sm">
                          <thead className="sticky top-0 bg-gray-900"><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Token', 'Customer', 'Phone', 'Items', 'Amount', 'Method', 'Status', 'Placed'].map(h => <th key={h} className="px-3 py-2.5 font-bold">{h}</th>)}</tr></thead>
                          <tbody>
                            {slotFiltered.map((o: any) => (
                              <tr key={o.id} className="border-b border-gray-800/50 text-gray-300">
                                <td className="px-3 py-2.5 font-semibold">{o.token}</td>
                                <td className="px-3 py-2.5">{o.student_name}</td>
                                <td className="px-3 py-2.5 text-gray-500">{o.student_phone || '—'}</td>
                                <td className="px-3 py-2.5"><OrderItemsCell items={o.items} /></td>
                                <td className="px-3 py-2.5 font-bold">₹{o.total}</td>
                                <td className="px-3 py-2.5"><span className={`rounded px-2 py-0.5 text-xs ${o.payment_method === 'COD' ? 'bg-gold-light/20 text-gold' : 'bg-blue-900/30 text-blue-400'}`}>{o.payment_method || 'UPI'}</span></td>
                                <td className="px-3 py-2.5"><span className={`rounded-sm px-2 py-0.5 text-xs ${o.status === 'Completed' ? 'bg-primary-dark/30 text-primary' : o.status === 'Cancelled' ? 'bg-red-900/30 text-red-400' : 'bg-gold-light/20 text-gold'}`}>{o.status}</span></td>
                                <td className="px-3 py-2.5 text-gray-500">{fmtTime(o.created_at) || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-sm text-gray-500">No {isAfternoon ? 'afternoon' : 'morning'} orders today for this shop</p>
                    )}
                  </div>
                )
              })()}
              {settingsShop === v.id && (
                <div className="mt-4 border-t border-gray-800 pt-4">
                  <h4 className="mb-3 text-sm font-bold text-gray-400">Shop Settings — {v.name}</h4>
                  <div className="rounded-sm border border-gray-700 bg-gray-800/50 p-4 space-y-3">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <label className="mb-1 block text-xs font-bold text-gray-400">Phone Number</label>
                        <input value={settingsForm.phone} onChange={e => setSettingsForm({ ...settingsForm, phone: e.target.value })} placeholder="9876543210" className="w-full rounded-sm border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-500" />
                      </div>
                      <div>
                        <label className="mb-1 block text-xs font-bold text-gray-400">UPI ID</label>
                        <input value={settingsForm.upi_id} onChange={e => setSettingsForm({ ...settingsForm, upi_id: e.target.value })} placeholder="vendor@upi" className="w-full rounded-sm border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-500" />
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-4">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={settingsForm.upi_enabled} onChange={e => setSettingsForm({ ...settingsForm, upi_enabled: e.target.checked })} className="h-4 w-4 rounded accent-amber-500" />
                        <span className="text-sm font-semibold text-white">UPI Enabled</span>
                      </label>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={settingsForm.cod_enabled} onChange={e => setSettingsForm({ ...settingsForm, cod_enabled: e.target.checked })} className="h-4 w-4 rounded accent-amber-500" />
                        <span className="text-sm font-semibold text-white">COD Enabled</span>
                      </label>
                    </div>
                    <button onClick={() => saveSettings(v.id)} disabled={settingsSaving} className="rounded-sm bg-gold px-4 py-2 text-xs font-bold text-black hover:bg-gold disabled:opacity-40">
                      {settingsSaving ? 'Saving...' : 'Save Settings'}
                    </button>
                  </div>
                </div>
              )}
              {selectedShop === v.id && (
                <div className="mt-4 border-t border-gray-800 pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-bold text-gray-400">Products ({products.length})</h4>
                    {!editProduct && (
                      <button onClick={() => { setEditProduct(null); setProductForm({ name: '', price: '', category: 'Food', description: '', inventory: '0', prep_time: '10', available: true }); setProductShopId(v.id) }} className="rounded-sm bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary">+ Add Product</button>
                    )}
                  </div>
                  {(productShopId === v.id && (editProduct || productForm.name !== '' || !editProduct)) && selectedShop === v.id && (
                    <div className="mb-3 rounded-sm border border-amber-900/40 bg-amber-900/10 p-4 space-y-2">
                      <p className="text-xs font-bold text-gold">{editProduct ? 'Edit Product' : 'Add New Product'}</p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <input value={productForm.name} onChange={e => setProductForm({ ...productForm, name: e.target.value })} placeholder="Product name" className="rounded-sm border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-500" />
                        <input type="number" value={productForm.price} onChange={e => setProductForm({ ...productForm, price: e.target.value })} placeholder="Price (₹)" className="rounded-sm border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-500" />
                        <input value={productForm.description} onChange={e => setProductForm({ ...productForm, description: e.target.value })} placeholder="Description" className="rounded-sm border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-500" />
                        <select value={productForm.category} onChange={e => setProductForm({ ...productForm, category: e.target.value })} className="rounded-sm border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-500">
                          {['Food', 'Drinks', 'Snacks', 'Dessert', 'Other'].map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                      <div className="flex items-center gap-3">
                        <button onClick={() => saveProduct(v.id)} disabled={productSaving} className="rounded-sm bg-gold px-4 py-1.5 text-xs font-bold text-black hover:bg-gold disabled:opacity-40">{productSaving ? 'Saving...' : editProduct ? 'Update' : 'Add'}</button>
                        <button onClick={() => { setEditProduct(null); setProductForm({ name: '', price: '', category: 'Food', description: '', inventory: '0', prep_time: '10', available: true }) }} className="rounded-sm bg-gray-800 px-4 py-1.5 text-xs font-semibold text-gray-300 hover:bg-gray-700">Cancel</button>
                      </div>
                    </div>
                  )}
                  {products.length > 0 ? (
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {products.map((p: any) => (
                        <div key={p.id} className="rounded-sm bg-gray-800/50 p-3">
                          <div className="flex items-start justify-between">
                            <div>
                              <p className="font-semibold text-white">{p.name}</p>
                              <p className="text-xs text-gray-400">₹{p.price} · {p.category}</p>
                              <p className="text-xs text-gray-500"><span className={`mr-1 inline-block h-1.5 w-1.5 rounded-pill ${p.available ? 'bg-primary' : 'bg-red-500'}`} />{p.available ? 'Available' : 'Unavailable'}</p>
                            </div>
                            <div className="flex gap-1">
                              <button onClick={() => { setEditProduct(p); setProductForm({ name: p.name, price: String(p.price), category: p.category, description: p.description || '', inventory: String(p.inventory || 0), prep_time: String(p.prep_time || 10), available: !!p.available }); setProductShopId(v.id) }} className="rounded bg-gray-700 px-2 py-1 text-[10px] font-bold text-gray-300 hover:bg-gray-600">Edit</button>
                              <button onClick={() => deleteProduct(v.id, p.id)} className="rounded bg-red-900/40 px-2 py-1 text-[10px] font-bold text-red-300 hover:bg-red-900/60">Del</button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500">No products yet — click "+ Add Product" to create one.</p>
                  )}
                </div>
              )}
              {logsShop === v.id && (
                <div className="mt-4 border-t border-gray-800 pt-4">
              {logsErr && <p className="mb-3 rounded-sm border border-red-900/40 bg-red-900/20 px-4 py-3 text-sm text-red-300">{logsErr}</p>}
              {logs && (
                <>
                  <h4 className="mb-2 text-sm font-bold text-gray-400">Daily Earnings Logs</h4>
                  <div className="mb-4 grid gap-3 sm:grid-cols-3">
                    <div className="rounded-sm bg-gray-800/50 p-3"><p className="text-xs text-gray-400">Total Revenue</p><p className="text-lg font-bold text-white">₹{(logs.summary?.total_revenue || 0).toLocaleString('en-IN')}</p></div>
                    <div className="rounded-sm bg-gray-800/50 p-3"><p className="text-xs text-gray-400">Total Orders</p><p className="text-lg font-bold text-white">{logs.summary?.total_orders || 0}</p></div>
                    <div className="rounded-sm bg-amber-900/20 p-3"><p className="text-xs text-gold">Admin's 5% Share</p><p className="text-lg font-bold text-gold">₹{(logs.summary?.total_admin_fee || 0).toLocaleString('en-IN')}</p></div>
                  </div>
                  <div className="overflow-x-auto rounded-sm border border-gray-800">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Date', 'Orders', 'Earnings', "Admin's 5%", 'Vendor Keeps'].map(h => <th key={h} className="px-4 py-2.5 font-bold">{h}</th>)}</tr></thead>
                      <tbody>
                        {logs.daily?.map((d: any) => (
                          <tr key={d.created_at} className="border-b border-gray-800/50 text-gray-300">
                            <td className="px-4 py-2.5 font-semibold">{d.created_at}</td>
                            <td className="px-4 py-2.5">{d.count} orders</td>
                            <td className="px-4 py-2.5 font-bold">₹{d.revenue || 0}</td>
                            <td className="px-4 py-2.5 font-bold text-gold">₹{d.admin_fee || 0}</td>
                            <td className="px-4 py-2.5 text-primary">₹{Math.max(0, (d.revenue || 0) - (d.admin_fee || 0))}</td>
                          </tr>
                        ))}
                        {(!logs.daily || logs.daily.length === 0) && <tr><td colSpan={5} className="p-6 text-center text-gray-500">No orders yet for this shop</td></tr>}
                      </tbody>
                    </table>
                  </div>
                  <h5 className="mt-4 mb-2 text-sm font-bold text-gray-400">Orders</h5>
                  <div className="max-h-64 overflow-y-auto rounded-sm border border-gray-800">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-gray-900"><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Token', 'Customer', 'Phone', 'Items', 'Amount', 'Method', 'Status'].map(h => <th key={h} className="px-4 py-2.5 font-bold">{h}</th>)}</tr></thead>
                      <tbody>
                        {logs.orders?.map((o: any) => (
                          <tr key={o.id} className="border-b border-gray-800/50 text-gray-300">
                            <td className="px-4 py-2.5 font-semibold">{o.token}</td>
                            <td className="px-4 py-2.5">{o.student_name}</td>
                            <td className="px-4 py-2.5 text-gray-500">{o.student_phone || '—'}</td>
                            <td className="px-4 py-2.5"><OrderItemsCell items={o.items} /></td>
                            <td className="px-4 py-2.5 font-bold">₹{o.total}</td>
                            <td className="px-4 py-2.5"><span className={`rounded px-2 py-0.5 text-xs ${o.payment_method === 'COD' ? 'bg-gold-light/20 text-gold' : 'bg-blue-900/30 text-blue-400'}`}>{o.payment_method || 'UPI'}</span></td>
                            <td className="px-4 py-2.5">{o.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              </div>
              )}
            </div>
          ))}
          {filteredVendors.length === 0 && (
            <p className="py-8 text-center text-sm text-gray-500">No {vendorFilter === 'approved' ? 'approved' : vendorFilter === 'pending' ? 'pending' : 'removed'} vendors found</p>
          )}
        </div>
      )}
    </div>
  )
}

/* Orders Page — with status / method / search / date filters */
function OrdersAdminPage() {
  const [orders, setOrders] = useState<any[]>([]); const [loading, setLoading] = useState(true)
  const [fStatus, setFStatus] = useState('all')
  const [fMethod, setFMethod] = useState('all')
  const [fSearch, setFSearch] = useState('')
  const [fDate, setFDate] = useState('')
  /* Auto-refresh every 30s so new orders appear without a manual reload —
     and only while the tab is visible (a backgrounded tab shouldn't keep
     pulling the whole order list). */
  useEffect(() => {
    const load = () => { if (document.visibilityState === 'visible') api.get('/admin/orders').then(r => setOrders(r.data || [])).finally(() => setLoading(false)) }
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])
  const statuses = ['Pending Acceptance', 'Pending Payment', 'Accepted', 'Completed', 'Cancelled']
  const filtered = orders.filter((o: any) => {
    if (fStatus !== 'all' && o.status !== fStatus) return false
    if (fMethod !== 'all' && (o.payment_method || 'UPI') !== fMethod) return false
    if (fSearch && !`${o.shop_name} ${o.student_name} #${o.token}`.toLowerCase().includes(fSearch.toLowerCase())) return false
    if (fDate && !String(o.created_at || '').startsWith(fDate)) return false
    return true
  })
  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-bold text-white">All Orders ({filtered.length}{orders.length !== filtered.length && ` of ${orders.length}`})</h1>
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-btn border border-gray-800 bg-gray-900/50 p-3">
        <div className="relative min-w-[220px] flex-1">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg></span>
          <input value={fSearch} onChange={e => setFSearch(e.target.value)} placeholder="Search shop, student, token…" className="w-full rounded-btn border border-gray-800 bg-gray-900 py-2.5 pl-9 pr-3 text-sm text-white placeholder-gray-500 outline-none focus:border-amber-500" />
        </div>
        <select value={fStatus} onChange={e => setFStatus(e.target.value)} className="rounded-btn border border-gray-800 bg-gray-900 px-3 py-2.5 text-sm text-white outline-none focus:border-amber-500">
          <option value="all">All statuses</option>
          {statuses.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={fMethod} onChange={e => setFMethod(e.target.value)} className="rounded-btn border border-gray-800 bg-gray-900 px-3 py-2.5 text-sm text-white outline-none focus:border-amber-500">
          <option value="all">All payment methods</option>
          <option>UPI</option>
          <option>COD</option>
        </select>
        <input type="date" value={fDate} onChange={e => setFDate(e.target.value)} className="rounded-btn border border-gray-800 bg-gray-900 px-3 py-2.5 text-sm text-white outline-none focus:border-amber-500" />
        {(fStatus !== 'all' || fMethod !== 'all' || fSearch || fDate) && (
          <button onClick={() => { setFStatus('all'); setFMethod('all'); setFSearch(''); setFDate('') }} className="rounded-btn bg-gray-800 px-3 py-2.5 text-sm font-semibold text-gray-300 hover:bg-gray-700">Clear</button>
        )}
      </div>
      <div className="rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
        {loading ? <p className="p-8 text-center text-gray-500">Loading...</p> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Token', 'Shop', 'Student', 'Phone', 'Items', 'Amount', 'Method', 'Location', 'Slot', 'Status', 'Placed', ''].map(h => <th key={h} className="px-4 py-3 font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.map((o: any) => (
                <tr key={o.id} className="border-b border-gray-800/50 text-gray-300">
                  <td className="px-4 py-3 font-bold">{o.token}</td>
                  <td className="px-4 py-3">{o.shop_name}</td>
                  <td className="px-4 py-3">{o.student_name}</td>
                  <td className="px-4 py-3 text-gray-500">{o.student_phone || '—'}</td>
                  <td className="px-4 py-3"><OrderItemsCell items={o.items} /></td>
                  <td className="px-4 py-3 font-semibold">₹{o.total}</td>
                  <td className="px-4 py-3"><span className={`rounded px-2 py-0.5 text-xs ${o.payment_method === 'COD' ? 'bg-gold-light/20 text-gold' : 'bg-blue-900/30 text-blue-400'}`}>{o.payment_method || 'UPI'}</span></td>
                  <td className="px-4 py-3 text-gray-500">{o.delivery_location}</td>
                  <td className="px-4 py-3">{o.delivery_slot}</td>
                  <td className="px-4 py-3"><span className={`rounded-sm px-2 py-0.5 text-xs ${o.status === 'Completed' ? 'bg-primary-dark/30 text-primary' : o.status === 'Cancelled' ? 'bg-red-900/30 text-red-400' : 'bg-gold-light/20 text-gold'}`}>{o.status}</span></td>
                  <td className="px-4 py-3 text-gray-500">{fmtTime(o.created_at) || o.created_at || '—'}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={async () => {
                        try {
                          const r = await api.get(`/admin/orders/${o.id}/whatsapp-link`)
                          window.open(r.data.url, '_blank')
                        } catch (e: any) {
                          alert(e?.response?.data?.detail || 'Could not build WhatsApp link for this shop')
                        }
                      }}
                      title="Send this order to the shop's WhatsApp from your number"
                      className="rounded bg-emerald-900/40 px-2 py-1 text-xs font-semibold text-emerald-400 hover:bg-emerald-800/50"
                    >WhatsApp</button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={12} className="p-8 text-center text-gray-500">No orders match these filters</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* Payments — order payments are read-only (shops confirm UPI directly), but
   vendor→admin 5% share payments are monitored LIVE here: who paid, who
   hasn't, and a mark-received action once the money lands in the admin's UPI. */
function PaymentsPage() {
  const [payments, setPayments] = useState<any[]>([])
  const [shares, setShares] = useState<any>(null)
  const [loading, setLoading] = useState(true); const [live, setLive] = useState(false); const [msg, setMsg] = useState('')
  const [shareErr, setShareErr] = useState('')

  const loadShares = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const r = await api.get('/admin/shares')
      setShares(r.data || null)
      if (r.data) setShareErr('')
    } catch { if (!silent) setShareErr('Could not load share monitor — the backend may need a restart to pick up the new endpoint.') }
    finally { if (!silent) setLoading(false) }
  }
  const loadPayments = async () => {
    try { const r = await api.get('/admin/payments'); setPayments(r.data || []) } catch {}
  }

  useEffect(() => {
    loadShares(); loadPayments()
    // Refresh every 30s, and only while the tab is visible — the share monitor
    // doesn't need live updates from a backgrounded tab.
    const t = setInterval(() => { if (document.visibilityState === 'visible') { loadShares(true); loadPayments() } }, 30000)
    setLive(true)
    return () => clearInterval(t)
  }, [])

  const markReceived = async (id: string) => {
    try {
      await api.patch(`/admin/shares/${id}`, { status: 'Completed' })
      setMsg('Marked as received — the share is now counted as collected.')
      loadShares(true)
    } catch (err: any) { setShareErr(err?.response?.data?.detail || 'Failed to update') }
  }
  const markRejected = async (id: string) => {
    try { await api.patch(`/admin/shares/${id}`, { status: 'Rejected' }); setMsg('Share payment rejected.'); loadShares(true) } catch {}
  }

  const summary = shares?.summary || {}
  const vendorList: any[] = shares?.vendors || []
  const sharePayments: any[] = shares?.payments || []
  /* "2026-08" → "Aug 2026" — which month a share record belongs to. */
  const monthLabel = (s: any) => {
    const m = String(s || '').slice(0, 7)
    if (m.length !== 7) return '—'
    const [y, mo] = m.split('-')
    const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `${names[Number(mo) - 1] || mo} ${y}`
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6 flex items-center justify-between">
        <div><h1 className="text-2xl font-bold text-white">Payments & Vendor Shares</h1>
        <p className="text-sm text-gray-400">Order payments (read-only) + the monthly 5% share each vendor pays you — updated live every 15s</p></div>
        <span className={`flex items-center gap-2 rounded-pill px-3 py-1.5 text-xs font-bold ${live ? 'bg-primary-dark/30 text-primary' : 'bg-gray-800 text-gray-400'}`}>
          <span className={`h-2 w-2 rounded-pill ${live ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500'}`} /> LIVE
        </span>
      </div>

      {msg && <div className="mb-4 rounded-btn bg-primary-dark/30 border border-primary/20 px-4 py-3 text-sm text-primary">{msg}</div>}
      {shareErr && <div className="mb-4 rounded-btn bg-red-900/30 border border-red-900/50 px-4 py-3 text-sm text-red-300">{shareErr}</div>}

      {/* Live summary cards — this month's share cycle */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-btn border border-amber-900/30 bg-amber-900/10 p-4">
          <p className="text-xs font-semibold text-gold">Expected This Month (5% shares)</p>
          <p className="mt-1 text-2xl font-bold text-white">₹{((summary.expected_month || 0)).toLocaleString('en-IN')}</p>
          <p className="mt-1 text-xs text-gold-dark">{shares?.month_label || ''} — resets on the 1st of each month</p>
        </div>
        <div className="rounded-btn border border-primary/15 bg-primary-dark/10 p-4">
          <p className="text-xs font-semibold text-primary">Collected This Month</p>
          <p className="mt-1 text-2xl font-bold text-primary">₹{((summary.collected_month || 0)).toLocaleString('en-IN')}</p>
          <p className="mt-1 text-xs text-primary">all time: ₹{((summary.collected_total || 0)).toLocaleString('en-IN')}</p>
        </div>
        <div className="rounded-btn border border-yellow-900/30 bg-yellow-900/10 p-4">
          <p className="text-xs font-semibold text-yellow-400">Pending This Month</p>
          <p className="mt-1 text-2xl font-bold text-yellow-400">₹{((summary.pending_month || 0)).toLocaleString('en-IN')}</p>
          <p className="mt-1 text-xs text-yellow-600">{summary.pending_month_count || 0} payment{((summary.pending_month_count || 0)) === 1 ? '' : 's'} awaiting receipt</p>
        </div>
        <div className="rounded-btn border border-gray-800 bg-gray-900/50 p-4">
          <p className="text-xs font-semibold text-gray-400">Vendors Paid This Month</p>
          <p className="mt-1 text-2xl font-bold text-white">{summary.paid_month_count || 0}<span className="text-sm text-gray-500"> / {vendorList.length} vendors</span></p>
          <p className="mt-1 text-xs text-gray-500">{((summary.paid_month_count || 0) / Math.max(1, vendorList.length) * 100).toFixed(0)}% of the month settled</p>
        </div>
      </div>

      {loading ? <p className="py-8 text-center text-gray-500">Loading...</p> : (
        <>
          {/* Per-vendor live status */}
          <div className="mb-8 rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
            <h2 className="border-b border-gray-800 px-5 py-4 text-lg font-bold text-white">Vendor Share Status <span className="text-xs font-semibold text-gray-500">(5% of {shares?.month_label || 'this month'}'s earnings)</span></h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Vendor', 'Month Orders', 'Month Revenue', 'Month 5% Share', 'Status', 'Last Paid'].map(h => <th key={h} className="px-5 py-3 font-bold">{h}</th>)}</tr></thead>
                <tbody>
                  {vendorList.map((v: any) => (
                    <tr key={v.shop_id} className="border-b border-gray-800/50 text-gray-300">
                      <td className="px-5 py-3"><p className="font-semibold text-white">{v.shop_name}</p><p className="text-xs text-gray-500">{v.shopkeeper_name}</p></td>
                      <td className="px-5 py-3">{v.month_orders}</td>
                      <td className="px-5 py-3 font-bold">₹{v.month_revenue}</td>
                      <td className="px-5 py-3 font-bold text-gold">₹{v.month_fee}</td>
                      <td className="px-5 py-3">
                        {v.paid_month ? (
                          <span className="rounded-sm bg-primary-dark/30 px-2 py-0.5 text-xs font-semibold text-primary">Paid</span>
                        ) : (
                          <span className="rounded-sm bg-gold-light/20 px-2 py-0.5 text-xs font-semibold text-gold">Pending</span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-gray-500">{v.last_paid_at ? String(v.last_paid_at).slice(0, 16) : '—'}</td>
                    </tr>
                  ))}
                  {vendorList.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-gray-500">No approved vendors yet</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          {/* Share payments history — the monthly records (done / pending) */}
          <div className="mb-8 rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
            <h2 className="border-b border-gray-800 px-5 py-4 text-lg font-bold text-white">Share Payment Records <span className="text-xs font-semibold text-gray-500">(vendor → your UPI, by month)</span></h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Vendor', 'Amount', 'Month', 'Initiated', 'Status', 'Actions'].map(h => <th key={h} className="px-5 py-3 font-bold">{h}</th>)}</tr></thead>
                <tbody>
                  {sharePayments.map((p: any) => (
                    <tr key={p.id} className="border-b border-gray-800/50 text-gray-300">
                      <td className="px-5 py-3 font-semibold">{p.shop_name}</td>
                      <td className="px-5 py-3 font-bold">₹{p.amount}</td>
                      <td className="px-5 py-3"><span className="rounded-sm bg-gray-800 px-2 py-0.5 text-xs font-semibold text-gold">{monthLabel(p.created_at)}</span></td>
                      <td className="px-5 py-3 text-gray-500">{String(p.created_at || '').slice(0, 16)}</td>
                      <td className="px-5 py-3">
                        <span className={`rounded-sm px-2 py-0.5 text-xs font-semibold ${p.status === 'Completed' ? 'bg-primary-dark/30 text-primary' : p.status === 'Rejected' ? 'bg-red-900/30 text-red-400' : 'bg-gold-light/20 text-gold'}`}>
                          {p.status === 'Completed' ? 'Received' : p.status === 'Rejected' ? 'Rejected' : 'Pending'}
                        </span>
                      </td>
                      <td className="px-5 py-3">
                        {p.status === 'Pending' ? (
                          <div className="flex gap-2">
                            <button onClick={() => markReceived(p.id)} className="rounded-sm bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary">✓ Mark Received</button>
                            <button onClick={() => markRejected(p.id)} className="rounded-sm bg-red-900/40 px-3 py-1.5 text-xs font-semibold text-red-400 hover:bg-red-900/60">✗</button>
                          </div>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                  {sharePayments.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-gray-500">No share payments yet — when a vendor taps Pay, it appears here.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Order payments (read-only) */}
      <div className="rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
        <h2 className="border-b border-gray-800 px-5 py-4 text-lg font-bold text-white">Order Payments <span className="text-xs font-semibold text-gray-500">(confirmed by each shop in the vendor app)</span></h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Order', 'Amount', 'Method', 'UTR', 'Status', 'Date'].map(h => <th key={h} className="px-4 py-3 font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {payments.map((p: any) => (
                <tr key={p.id} className="border-b border-gray-800/50 text-gray-300">
                  <td className="px-4 py-3 font-semibold">{p.order_id}</td>
                  <td className="px-4 py-3 font-bold">₹{p.amount}</td>
                  <td className="px-4 py-3">{p.method}</td>
                  <td className="px-4 py-3 text-gray-500">{p.utr_number || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-sm px-2 py-0.5 text-xs ${p.status === 'Success' ? 'bg-primary-dark/30 text-primary' : p.status === 'Failed' ? 'bg-red-900/30 text-red-400' : 'bg-gold-light/20 text-gold'}`}>
                      {p.status === 'Pending' ? 'Awaiting shop confirmation' : p.status === 'Pending Verification' ? 'Awaiting shop confirmation' : p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{p.created_at}</td>
                </tr>
              ))}
              {payments.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-gray-500">No order payments yet</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* Revenue with date-filtered daily logs */
function RevenuePage() {
  const [daily, setDaily] = useState<any[]>([]); const [loading, setLoading] = useState(true); const [filter, setFilter] = useState('')
  const load = (date?: string) => {
    setLoading(true)
    const url = date ? `/admin/orders/date?date=${date}` : '/admin/orders/daily'
    api.get(url).then(r => {
      if (!date) { setDaily(r.data || []); return }
      const list: any[] = r.data || []
      const revenue = list.reduce((s, o) => s + (o.total || 0), 0)
      setDaily([{
        created_at: date,
        count: list.length,
        revenue,
        service_fee: Math.round(revenue * 0.05),
      }])
    }).catch(() => setDaily([])).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const total = daily.reduce((s: number, d: any) => s + (d.revenue || 0), 0)
  const totalFee = daily.reduce((s: number, d: any) => s + (d.service_fee || 0), 0)

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-bold text-white">Revenue & Daily Logs</h1>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-btn border border-gray-800 bg-gray-900/50 p-5">
          <p className="text-sm text-gray-400">Total Revenue (all time)</p>
          <p className="text-3xl font-bold text-white">₹{total.toLocaleString('en-IN')}</p>
        </div>
        <div className="rounded-btn border border-amber-900/30 bg-amber-900/10 p-5">
          <p className="text-sm text-gold">Admin's 5% Share</p>
          <p className="text-3xl font-bold text-gold">₹{totalFee.toLocaleString('en-IN')}</p>
          <p className="mt-1 text-xs text-gold-dark">5% platform fee collected on every order</p>
        </div>
        <div className="rounded-btn border border-primary/15 bg-primary-dark/10 p-5">
          <p className="text-sm text-primary">Vendor Share</p>
          <p className="text-3xl font-bold text-primary">₹{Math.max(0, total - totalFee).toLocaleString('en-IN')}</p>
          <p className="mt-1 text-xs text-primary">Total minus the 5% platform fee</p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input type="date" value={filter} onChange={e => { setFilter(e.target.value); load(e.target.value || undefined) }}
          className="rounded-btn border border-gray-800 bg-gray-900 px-4 py-2.5 text-sm text-white outline-none focus:border-amber-500" />
        {filter && <button onClick={() => { setFilter(''); load() }} className="rounded-btn bg-gray-800 px-4 py-2.5 text-sm font-semibold text-gray-300 hover:bg-gray-700">Clear filter</button>}
      </div>

      <div className="rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
        <h2 className="px-5 py-4 text-lg font-bold text-white border-b border-gray-800">{filter ? `Orders on ${filter}` : 'Orders by Date'}</h2>
        {loading ? <p className="p-8 text-center text-gray-500">Loading...</p> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Date', 'Orders', 'Revenue', "Admin's 5%", 'Vendor Share'].map(h => <th key={h} className="px-5 py-3 font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {daily.map((d: any) => (
                <tr key={d.created_at} className="border-b border-gray-800/50 text-gray-300">
                  <td className="px-5 py-3 font-semibold">{d.created_at}</td>
                  <td className="px-5 py-3">{d.count} orders</td>
                  <td className="px-5 py-3 font-bold">₹{d.revenue || 0}</td>
                  <td className="px-5 py-3 text-gold font-bold">₹{d.service_fee || 0}</td>
                  <td className="px-5 py-3 text-primary">₹{Math.max(0, (d.revenue || 0) - (d.service_fee || 0))}</td>
                </tr>
              ))}
              {daily.length === 0 && <tr><td colSpan={5} className="p-8 text-center text-gray-500">No data for this date</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* Settings — the admin only needs their UPI ID. Vendors' "Pay" button opens a
   UPI app directed to this account to settle their 5% monthly share. */
function SettingsPage() {
  const [upiId, setUpiId] = useState('')
  const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false)
  useEffect(() => { api.get('/local/payment-settings').then(r => { setUpiId(r.data?.upi_id || '') }).catch(() => {}).finally(() => setLoading(false)) }, [])
  const save = async (e: FormEvent) => {
    e.preventDefault(); setMsg(''); setErr('')
    const value = upiId.trim()
    if (!value) { setErr('Please enter your UPI ID'); return }
    setSaving(true)
    try {
      // Saving a UPI ID also enables UPI payments automatically
      await api.patch('/local/payment-settings', { upi_id: value, manual_enabled: true })
      setMsg('UPI ID saved & enabled — vendors will now be directed to this account when they pay their 5% share.')
    }
    catch (err: any) { setErr(err?.response?.data?.detail || 'Failed to save') }
    finally { setSaving(false) }
  }
  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-bold text-white">Settings</h1>
      <div className="rounded-btn border border-gray-800 bg-gray-900/50 p-6">
        {loading ? <p className="text-gray-500">Loading...</p> : (
          <>
          <form onSubmit={save} className="space-y-5">
            {msg && <div className="rounded-btn bg-primary-dark/30 border border-primary/20 px-4 py-3 text-sm text-primary">{msg}</div>}
            {err && <div className="rounded-btn bg-red-900/30 border border-red-900/50 px-4 py-3 text-sm text-red-400">{err}</div>}
            <div className="rounded-btn bg-amber-900/10 border border-amber-900/30 p-4">
              <p className="flex items-center gap-2 text-sm font-bold text-gold"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M2 10h20" /></svg>Your UPI ID (receive the 5% share)</p>
              <p className="mt-1 text-xs text-gold-dark">When a vendor taps <b>Pay</b> on their dashboard, they'll be directed to this UPI account to pay their 5% monthly share. Saving this also enables UPI payments for students.</p>
            </div>
            <div>
              <label className="mb-1 block text-xs font-bold text-gray-400">UPI ID (e.g. yourname@upi)</label>
              <input value={upiId} onChange={e => setUpiId(e.target.value)} placeholder="yourname@okhdfcbank" className="w-full rounded-btn border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white outline-none focus:border-amber-500" required />
            </div>
            <button type="submit" disabled={saving} className="w-full rounded-btn bg-gold px-5 py-3 text-sm font-bold text-black hover:bg-gold disabled:opacity-40">{saving ? 'Saving...' : 'Save & Enable'}</button>
          </form>
          <p className="mt-4 rounded-btn border border-gray-800 bg-gray-900/50 px-4 py-3 text-xs leading-relaxed text-gray-400">Students pay the shop by <b>scanning a UPI QR</b> (or Cash on Delivery) — the shop confirms each payment in the vendor app. Your UPI ID here is only the account vendors use to pay their <b>monthly 5% share</b>.</p>
          </>
        )}
      </div>
    </div>
  )
}

/* ─── App ─── */
/* Feedback — every student bug report / improvement contribution from the
   "Help us test DETOMSITE" page: which user gave what, and its status. */
const FEEDBACK_STATUSES = ['Open', 'In Review', 'Fixed', "Won't Fix"] as const
const FEEDBACK_CATEGORIES: Record<string, { icon: string; cls: string }> = {
  Bug: { icon: '🐞', cls: 'bg-red-900/30 text-red-400' },
  Improvement: { icon: '💡', cls: 'bg-gold-light/20 text-gold' },
  Suggestion: { icon: '✨', cls: 'bg-primary-dark/30 text-primary' },
  Other: { icon: '💬', cls: 'bg-sky-900/30 text-sky-400' },
}
function FeedbackPage() {
  const [items, setItems] = useState<any[]>([]); const [loading, setLoading] = useState(true)
  const [atsCount, setAtsCount] = useState(0)
  const [msg, setMsg] = useState(''); const [err, setErr] = useState('')
  const [search, setSearch] = useState(''); const [filter, setFilter] = useState<string>('all')

  /* ONLY real student feedback (source='User') is shown — automated test (ATS)
     data is hidden and can be purged with the "Clear test data" button. */
  const load = async () => {
    try {
      const [userRes, atsRes] = await Promise.all([
        api.get('/admin/feedback', { params: { source: 'User' } }),
        api.get('/admin/feedback', { params: { source: 'ATS' } }),
      ])
      setItems(userRes.data || [])
      setAtsCount(atsRes.data?.length || 0)
    } catch (e: any) { setErr(e?.response?.data?.detail || 'Could not load feedback — is the backend running?') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const clearAts = async () => {
    if (!window.confirm(`Delete all ${atsCount} automated test entries? Only real student feedback will remain.`)) return
    try {
      await api.delete('/admin/feedback', { params: { source: 'ATS' } })
      setMsg('Automated test data cleared — only real student feedback remains.')
      setErr('')
      setAtsCount(0)
    } catch (e: any) { setErr(e?.response?.data?.detail || 'Could not clear test data') }
  }

  const setStatus = async (id: string, status: string) => {
    try {
      await api.patch(`/admin/feedback/${id}`, { status })
      setMsg(status === 'Fixed' ? 'Marked as fixed — thanks for the report!' : `Status updated → ${status}`)
      setErr('')
      load()
    } catch (e: any) { setErr(e?.response?.data?.detail || 'Failed to update status') }
  }

  const counts = FEEDBACK_STATUSES.reduce<Record<string, number>>((acc, s) => { acc[s] = items.filter(i => i.status === s).length; return acc }, {})
  const filtered = items.filter(i => {
    if (filter !== 'all' && i.status !== filter) return false
    if (search && !`${i.name} ${i.username} ${i.email} ${i.subject} ${i.message} ${i.page}`.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Site Feedback & Bug Reports</h1>
        <p className="text-sm text-gray-400">Students test the site and contribute bugs + ideas — who sent it, what they said, and the fix status</p>
      </div>

      {msg && <div className="mb-4 rounded-btn bg-primary-dark/30 border border-primary/20 px-4 py-3 text-sm text-primary">{msg}</div>}
      {err && <div className="mb-4 rounded-btn bg-red-900/30 border border-red-900/50 px-4 py-3 text-sm text-red-300">{err}</div>}

      {/* Summary cards */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <div className="rounded-btn border border-primary/15 bg-primary-dark/10 p-4"><p className="text-xs font-semibold text-primary">👤 Real Student Reports</p><p className="mt-1 text-2xl font-bold text-primary">{items.length}</p></div>
        <div className="rounded-btn border border-violet-900/30 bg-violet-900/10 p-4">
          <p className="text-xs font-semibold text-violet-400">🤖 Test Data (hidden)</p>
          <p className="mt-1 text-2xl font-bold text-violet-400">{atsCount}</p>
          {atsCount > 0 && (
            <button onClick={clearAts} className="mt-1.5 rounded-sm bg-violet-900/40 px-2.5 py-1 text-[11px] font-bold text-violet-200 transition-colors hover:bg-violet-900/60">🧹 Clear test data</button>
          )}
        </div>
        <div className="rounded-btn border border-amber-900/30 bg-amber-900/10 p-4"><p className="text-xs font-semibold text-gold">Open</p><p className="mt-1 text-2xl font-bold text-gold">{counts['Open'] || 0}</p></div>
        <div className="rounded-btn border border-sky-900/30 bg-sky-900/10 p-4"><p className="text-xs font-semibold text-sky-400">In Review</p><p className="mt-1 text-2xl font-bold text-sky-400">{counts['In Review'] || 0}</p></div>
        <div className="rounded-btn border border-primary/15 bg-primary-dark/10 p-4"><p className="text-xs font-semibold text-primary">Fixed</p><p className="mt-1 text-2xl font-bold text-primary">{counts['Fixed'] || 0}</p></div>
        <div className="rounded-btn border border-gray-800 bg-gray-900/50 p-4"><p className="text-xs font-semibold text-gray-400">Won't Fix</p><p className="mt-1 text-2xl font-bold text-white">{counts["Won't Fix"] || 0}</p></div>
      </div>

      {atsCount > 0 && (
        <div className="mb-4 flex items-center gap-3 rounded-btn border border-violet-900/30 bg-violet-900/10 px-4 py-3 text-sm text-violet-300">
          <span>🤖 <b>{atsCount}</b> automated-test entr{atsCount === 1 ? 'y' : 'ies'} were generated by the test suite and are hidden — only <b>real student</b> feedback is shown here.</span>
          <button onClick={clearAts} className="ml-auto shrink-0 rounded-sm bg-violet-900/40 px-3 py-1.5 text-xs font-bold text-violet-100 transition-colors hover:bg-violet-900/60">Delete them</button>
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-btn border border-gray-800 bg-gray-900/50 p-3">
        <div className="relative min-w-[220px] flex-1">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg></span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search user, email, subject, message…" className="w-full rounded-btn border border-gray-800 bg-gray-900 py-2.5 pl-9 pr-3 text-sm text-white placeholder-gray-500 outline-none focus:border-amber-500" />
        </div>
        <select value={filter} onChange={e => setFilter(e.target.value)} className="rounded-btn border border-gray-800 bg-gray-900 px-3 py-2.5 text-sm text-white outline-none focus:border-amber-500">
          <option value="all">All statuses</option>
          {FEEDBACK_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        {filter !== 'all' && <button onClick={() => setFilter('all')} className="rounded-btn bg-gray-800 px-3 py-2.5 text-sm font-semibold text-gray-300 hover:bg-gray-700">Clear</button>}
      </div>

      <div className="rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
        {loading ? <p className="p-8 text-center text-gray-500">Loading...</p> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['S.No.', 'Reported By', 'Source', 'Type', 'Subject / Message', 'Page', 'Status', 'Date', 'Actions'].map(h => <th key={h} className="px-4 py-3 font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.map((f: any, i: number) => {
                const cat = FEEDBACK_CATEGORIES[f.category] || FEEDBACK_CATEGORIES.Other
                return (
                  <tr key={f.id} className="border-b border-gray-800/50 align-top text-gray-300">
                    <td className="px-4 py-3 text-gray-500">{i + 1}</td>
                    <td className="px-4 py-3">
                      <p className="font-semibold text-white">{f.name || f.username || 'Guest'}</p>
                      <p className="text-xs text-gray-500">@{f.username || '—'}</p>
                      <p className="text-xs text-gray-500">{f.email || '—'}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-[11px] font-bold ${f.source === 'ATS' ? 'bg-violet-900/30 text-violet-300' : 'bg-primary-dark/30 text-primary/80'}`}>
                        {f.source === 'ATS' ? '🤖 ATS' : '👤 User'}
                      </span>
                    </td>
                    <td className="px-4 py-3"><span className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-semibold ${cat.cls}`}>{cat.icon}{f.category}</span></td>
                    <td className="px-4 py-3 max-w-[280px]">
                      <p className="font-bold text-white">{f.subject}</p>
                      <p className="mt-1 whitespace-pre-wrap text-gray-400 line-clamp-3" title={f.message}>{f.message}</p>
                    </td>
                    <td className="px-4 py-3 text-gray-500">{f.page || '—'}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-sm px-2 py-0.5 text-xs font-semibold ${f.status === 'Fixed' ? 'bg-primary-dark/30 text-primary' : f.status === 'In Review' ? 'bg-sky-900/30 text-sky-400' : f.status === "Won't Fix" ? 'bg-gray-800 text-gray-400' : 'bg-gold-light/20 text-gold'}`}>{f.status}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">{fmtTime(f.created_at) || '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {FEEDBACK_STATUSES.filter(s => s !== f.status).map(s => (
                          <button key={s} onClick={() => setStatus(f.id, s)}
                            className={`rounded-sm px-2.5 py-1 text-[11px] font-bold transition-colors ${s === 'Fixed' ? 'bg-primary text-white hover:bg-primary' : s === 'In Review' ? 'bg-sky-900/40 text-sky-300 hover:bg-sky-900/60' : s === 'Open' ? 'bg-amber-900/40 text-gold hover:bg-amber-900/60' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>{s}</button>
                        ))}
                      </div>
                    </td>
                  </tr>
                )
              })}
              {filtered.length === 0 && <tr><td colSpan={9} className="p-10 text-center text-gray-500">{items.length === 0 ? 'No feedback yet — when a student reports a bug or idea on the “Help us test” page, it appears here.' : 'No reports match these filters'}</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* Reviews — student shop reviews visible to admin */
function ReviewsPage() {
  const [reviews, setReviews] = useState<any[]>([]); const [loading, setLoading] = useState(true); const [search, setSearch] = useState('')
  useEffect(() => {
    api.get('/admin/reviews').then(r => setReviews(r.data || [])).catch(() => {}).finally(() => setLoading(false))
  }, [])
  const filtered = reviews.filter((r: any) => !search || `${r.student_name} ${r.shop_name} ${r.comment}`.toLowerCase().includes(search.toLowerCase()))
  const avgRating = reviews.length > 0 ? (reviews.reduce((s: number, r: any) => s + (r.rating || 0), 0) / reviews.length).toFixed(1) : '0'
  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-bold text-white">Student Reviews ({filtered.length})</h1>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-btn border border-gray-800 bg-gray-900/50 p-4"><p className="text-xs font-semibold text-gray-400">Total Reviews</p><p className="mt-1 text-2xl font-bold text-white">{reviews.length}</p></div>
        <div className="rounded-btn border border-amber-900/30 bg-amber-900/10 p-4"><p className="text-xs font-semibold text-gold">Average Rating</p><p className="mt-1 text-2xl font-bold text-gold">{'★'.repeat(Math.round(Number(avgRating)))} {avgRating}</p></div>
        <div className="rounded-btn border border-primary/15 bg-primary-dark/10 p-4"><p className="text-xs font-semibold text-primary">Unique Shops Reviewed</p><p className="mt-1 text-2xl font-bold text-primary">{new Set(reviews.map((r: any) => r.shop_id)).size}</p></div>
      </div>
      <div className="mb-4 flex items-center gap-3">
        <div className="relative min-w-[220px] flex-1 max-w-xs">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg></span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search student, shop, comment…" className="w-full rounded-btn border border-gray-800 bg-gray-900 py-2.5 pl-9 pr-3 text-sm text-white placeholder-gray-500 outline-none focus:border-amber-500" />
        </div>
      </div>
      <div className="rounded-btn border border-gray-800 bg-gray-900/50 overflow-hidden">
        {loading ? <p className="p-8 text-center text-gray-500">Loading...</p> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-800 text-left text-xs text-gray-400">{['Student', 'Shop', 'Rating', 'Comment', 'Date'].map(h => <th key={h} className="px-4 py-3 font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.map((r: any) => (
                <tr key={r.id} className="border-b border-gray-800/50 text-gray-300">
                  <td className="px-4 py-3"><p className="font-semibold text-white">{r.student_name || r.username || '—'}</p></td>
                  <td className="px-4 py-3">{r.shop_name || '—'}</td>
                  <td className="px-4 py-3"><span className="text-gold">{'★'.repeat(r.rating || 0)}</span> <span className="text-gray-500">{r.rating}/5</span></td>
                  <td className="px-4 py-3 max-w-xs"><p className="truncate" title={r.comment}>{r.comment || '—'}</p></td>
                  <td className="px-4 py-3 text-gray-500">{fmtTime(r.created_at) || '—'}</td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={5} className="p-8 text-center text-gray-500">No reviews yet</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* SMS Logs — every order SMS (out) and confirm/reject reply (in) the system
   sent or received, so the admin can watch the phone-notification pipeline. */
function SmsLogsPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const load = () => { if (document.visibilityState === 'visible') api.get('/local/sms-logs').then(r => { setLogs(r.data || []); setLoading(false) }).catch(() => { setLoading(false) }) }
    load(); const t = setInterval(load, 15000); return () => clearInterval(t)
  }, [])
  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">SMS Logs</h1>
        <p className="text-sm text-gray-400">Order SMS sent to shopkeepers' phones + the YES/NO confirm replies — refreshed live</p>
      </div>
      {loading ? <p className="text-gray-500">Loading...</p> : logs.length === 0 ? (
        <div className="rounded-btn border border-gray-800 bg-gray-900 p-8 text-center text-gray-500">No SMS sent yet. Place an order to see the pipeline.</div>
      ) : (
        <div className="space-y-2">
          {logs.map((s: any) => (
            <div key={s.id} className="rounded-btn border border-gray-800 bg-gray-900 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className={`rounded-pill px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${s.direction === 'in' ? 'bg-emerald-900/40 text-emerald-300' : 'bg-primary-dark/40 text-primary'}`}>{s.direction === 'in' ? 'Received' : 'Sent'}</span>
                <span className="text-xs text-gray-500">{(s.created_at || '').replace('T', ' ').slice(0, 19)}</span>
              </div>
              <p className="mt-1.5 whitespace-pre-line font-mono text-xs leading-relaxed text-gray-300">{s.message}</p>
              {s.phone && <p className="mt-1 text-xs text-gray-500">→ {s.phone}{s.status ? ` · ${s.status}` : ''}</p>}
              {s.sub_order_id && <p className="text-[11px] text-gray-600">order {s.sub_order_id}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/*" element={
          <RequireAuth>
            <Layout>
              <Routes>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/users" element={<UsersPage />} />
                <Route path="/vendors" element={<VendorsPage />} />
                <Route path="/orders" element={<OrdersAdminPage />} />
                <Route path="/payments" element={<PaymentsPage />} />
                <Route path="/sms" element={<SmsLogsPage />} />
                <Route path="/revenue" element={<RevenuePage />} />
                <Route path="/feedback" element={<FeedbackPage />} />
                <Route path="/reviews" element={<ReviewsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<NavigateToDashboard />} />
              </Routes>
            </Layout>
          </RequireAuth>
        } />
      </Routes>
    </Router>
  )
}

/* ─── Auth guard: redirects to /login if no valid admin token ─── */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const token = localStorage.getItem('admin_token')
  useEffect(() => {
    if (!token) navigate('/login', { replace: true })
  }, [token, navigate])
  if (!token) return null
  return <>{children}</>
}

function NavigateToDashboard() {
  const navigate = useNavigate()
  useEffect(() => { navigate(localStorage.getItem('admin_token') ? '/dashboard' : '/login', { replace: true }) }, [])
  return null
}
