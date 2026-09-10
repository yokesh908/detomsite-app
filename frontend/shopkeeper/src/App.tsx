import { useState, useEffect, useRef, FormEvent } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, useNavigate } from 'react-router-dom'
import api from './services/api'
import { QRCodeSVG } from 'qrcode.react'

/* UPI deep-link: encodes the shop's UPI ID so scanning the QR opens the
   student's UPI app with the amount filled in. Amount is left to the payer
   (a static shop QR) — the order flow pre-fills it client-side. */
function buildShopUpiUri(pa: string, pn: string) {
  return `upi://pay?pa=${encodeURIComponent(pa)}&pn=${encodeURIComponent(pn)}&cu=INR`
}
/* UPI amounts MUST be clean numbers with at most 2 decimal places — raw float
   totals make banks reject the payment with a confusing "exceeded bank limit"
   message. Round before putting any amount into a upi:// URI. */
function upiAmount(am: number) { const n = Number(am); return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0 }

/* ─── Web Push helpers ─── */
/* Convert the base64url VAPID public key into the Uint8Array the browser's
   PushManager.subscribe() expects. */
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const output = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i)
  return output
}

/* The subscription keys come back as ArrayBuffers — encode them as base64
   strings for storage on the server. */
function pushKeyToBase64(key: ArrayBuffer | null): string {
  if (!key) return ''
  let binary = ''
  const bytes = new Uint8Array(key)
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

/* ─── PWA Install Hook ─── */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

function usePwaInstall() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(false)

  useEffect(() => {
    const handler = (event: Event) => { event.preventDefault(); setDeferredPrompt(event as BeforeInstallPromptEvent) }
    window.addEventListener('beforeinstallprompt', handler)
    window.addEventListener('appinstalled', () => setInstalled(true))
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const install = async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const outcome = await deferredPrompt.userChoice
    if (outcome.outcome === 'accepted') setInstalled(true)
    setDeferredPrompt(null)
  }

  return { install, canInstall: !!deferredPrompt, installed }
}

/* ─── Pages ─── */

/* Portal Home - Landing page with PWA Install */
function PortalHome() {
  const navigate = useNavigate()
  const { install, canInstall, installed } = usePwaInstall()
  const [loggedIn, setLoggedIn] = useState(false)
  const vendor = JSON.parse(localStorage.getItem('vendor_user') || '{}')

  useEffect(() => {
    setLoggedIn(!!localStorage.getItem('vendor_token'))
  }, [])

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-emerald-50 via-white to-amber-50">
      {/* Faded restaurant photo background */}
      <div className="absolute inset-0 overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=1000&q=80"
          alt=""
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="h-full w-full object-cover opacity-55"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-emerald-50/70 via-white/35 to-amber-50/70" />
      </div>
      <div className="relative mx-auto max-w-4xl px-4 py-12">
        <div className="mb-10 text-center">
          <span className="mx-auto flex h-20 w-20 items-center justify-center rounded-panel bg-primary text-white shadow-lg">
            <svg className="h-10 w-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V10M3 6l1.2-3h15.6L21 6a2.4 2.4 0 0 1-4.8 0 2.4 2.4 0 0 1-4.8 0A2.4 2.4 0 0 1 6.6 6 2.4 2.4 0 0 1 3 6Z" /><path d="M9 21v-6h6v6" /></svg>
          </span>
          <h1 className="mt-4 text-4xl font-black text-primary-dark">Shopkeeper Portal</h1>
          <p className="mt-2 text-lg text-gray-500">Register your shop, manage orders, and track your business</p>
        </div>

        {!loggedIn ? (
          <div className="grid gap-4 sm:grid-cols-2 max-w-xl mx-auto">
            <button onClick={() => navigate('/register')} className="rounded-card border-2 border-gold-light/60 bg-amber-50 p-6 text-center transition-all hover:bg-gold-light hover:-translate-y-1">
              <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-card bg-gold-light/70 text-gold-dark"><svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg></span>
              <h2 className="mt-3 text-lg font-bold text-gold-dark">Register Your Shop</h2>
              <p className="mt-1 text-sm text-gold-dark">New vendor? Create your shop</p>
            </button>
            <button onClick={() => navigate('/login')} className="rounded-card border-2 border-primary-light/50 bg-primary-light/30 p-6 text-center transition-all hover:bg-primary-light hover:-translate-y-1">
              <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-card bg-emerald-200/70 text-primary"><svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg></span>
              <h2 className="mt-3 text-lg font-bold text-primary">Sign In</h2>
              <p className="mt-1 text-sm text-primary">Existing shopkeeper</p>
            </button>
          </div>
        ) : (
          <div className="max-w-xl mx-auto">
            <div className="rounded-card bg-white border-2 border-primary-light/30 p-6 mb-4">
              <div className="flex items-center gap-3 mb-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-pill bg-primary-light text-primary"><svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m4 12.5 5 5L20 6.5" /></svg></span>
                <div><h2 className="font-bold text-primary-dark">Welcome back!</h2><p className="text-sm text-gray-500">{vendor.name || vendor.username}</p></div>
              </div>
              <button onClick={() => navigate('/mobile')} className="w-full rounded-btn bg-primary px-5 py-3 text-sm font-bold text-white hover:bg-primary-dark">Open Vendor App →</button>
            </div>
          </div>
        )}

        {/* PWA Install Card */}
        {!installed && canInstall && (
          <div className="mt-8 max-w-xl mx-auto rounded-card border-2 border-primary-light/30 bg-white p-6 shadow-lg">
            <div className="flex items-start gap-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-card bg-primary-light text-primary"><svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="7" y="2" width="10" height="20" rx="2" /><path d="M11 18h2" /></svg></span>
              <div className="flex-1">
                <h3 className="text-lg font-bold text-primary-dark">Install the Mobile App</h3>
                <p className="mt-1 text-sm text-gray-500">Install the vendor app on your phone to manage orders, update products, and receive real-time notifications.</p>
                <button onClick={install} className="mt-4 rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white hover:bg-primary-dark w-full">
                  Install App
                </button>
              </div>
            </div>
          </div>
        )}

        {installed && (
          <div className="mt-8 max-w-xl mx-auto rounded-card bg-primary-light border-2 border-primary-light/50 p-6 text-center">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-pill bg-primary text-white"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m4 12.5 5 5L20 6.5" /></svg></span>
            <h3 className="mt-2 text-lg font-bold text-primary-dark">App Installed!</h3>
            <p className="text-sm text-primary">The vendor app is ready. Open it from your home screen.</p>
          </div>
        )}

        <p className="mt-10 text-center text-sm text-gray-400">Already have an account? <Link to="/mobile" className="font-semibold text-primary">Open Mobile App</Link></p>
      </div>
    </div>
  )
}  /* Indian mobile input — the user types their 10-digit number; the value is
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
        className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-amber-500" />
    )
  }
  /* Password input with a show/hide toggle — every login/signup form uses it. */
  function PasswordField({ value, onChange, placeholder = '••••••', autoComplete, required = true, className = '' }: { value: string; onChange: (v: string) => void; placeholder?: string; autoComplete?: string; required?: boolean; className?: string }) {
    const [show, setShow] = useState(false)
    return (
      <div className="relative">
        <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)}
          placeholder={placeholder} autoComplete={autoComplete} required={required}
          className={`w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 pr-11 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-amber-500 ${className}`} />
        <button type="button" onClick={() => setShow(!show)} tabIndex={-1} aria-label={show ? 'Hide password' : 'Show password'}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-sm p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gold-dark">
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{show ? <><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><path d="m1 1 22 22" /></> : <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>}</svg>
        </button>
      </div>
    )
  }

/* Register */
function Register() {
  const navigate = useNavigate()
  const [f, setF] = useState({ username: '', email: '', phone: '', password: '', confirm: '', shopName: '', shopCategory: '', shopDescription: '', upiId: '' })
  const [err, setErr] = useState(''); const [loading, setLoading] = useState(false); const [registered, setRegistered] = useState(false)
  const categories = ['Italian', 'Chinese', 'Indian', 'Fast Food', 'Cafe', 'Bakery', 'Desserts', 'Beverages', 'Japanese', 'Mexican', 'Continental']

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    if (f.password !== f.confirm) { setErr('Passwords do not match'); return }
    if (!isValidMobile(f.phone)) { setErr('Please enter a valid 10-digit mobile number'); return }
    setLoading(true)
    try {
      await api.post('/vendor/register', {
        username: f.username, email: f.email, password: f.password, name: f.username, phone: f.phone,
        shop_name: f.shopName, shop_category: f.shopCategory, shop_description: f.shopDescription, upi_id: f.upiId,
      })
      // Auto-login
      const loginRes = await api.post('/vendor/login', { username: f.username, password: f.password })
      localStorage.setItem('vendor_token', loginRes.data.access_token)
      localStorage.setItem('vendor_user', JSON.stringify(loginRes.data.user))
      setRegistered(true)
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Registration failed') }
    finally { setLoading(false) }
  }

  if (registered) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-amber-50 to-white flex items-center justify-center px-4">
        <div className="max-w-md text-center">
          <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-pill bg-gold-light text-gold-dark"><svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg></span>
          <h1 className="mt-4 text-3xl font-black text-primary-dark">Registration Submitted!</h1>
          <div className="mt-6 rounded-card border-2 border-gold-light/60 bg-amber-50 p-6">
            <p className="font-bold text-gold-dark">Pending Admin Approval</p>
            <p className="mt-2 text-sm text-gold-dark">Your shop "{f.shopName}" needs to be approved by an admin before you can start selling.</p>
            <div className="mt-4 h-2 w-full bg-gold-light rounded-pill overflow-hidden"><div className="h-full w-1/3 bg-gold rounded-pill animate-pulse" /></div>
          </div>
          <button onClick={() => navigate('/mobile')} className="mt-6 rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white hover:bg-primary-dark">Open Vendor App →</button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 to-white flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="rounded-card bg-white p-8 shadow-lg border-2 border-gold-light/40">
          <div className="mb-6 text-center">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-card bg-gold-light text-gold-dark"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V10M3 6l1.2-3h15.6L21 6a2.4 2.4 0 0 1-4.8 0 2.4 2.4 0 0 1-4.8 0A2.4 2.4 0 0 1 6.6 6 2.4 2.4 0 0 1 3 6Z" /><path d="M9 21v-6h6v6" /></svg></span>
            <h1 className="mt-3 text-2xl font-bold text-primary-dark">Shop Registration</h1>
            <p className="text-sm text-gray-500">Register your restaurant on campus</p>
          </div>
          {err && <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-600">{err}</div>}
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-500"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" /></svg>Username</label>
              <input type="text" value={f.username} onChange={e => setF({...f, username: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-amber-500" placeholder="Choose a username" required />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Email</label>
                <input type="email" value={f.email} onChange={e => setF({...f, email: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-amber-500" placeholder="you@business.com" required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Mobile</label>
                <PhoneField value={f.phone} onChange={v => setF({...f, phone: v})} />
              </div>
            </div>
            <div className="border-t pt-4">
              <p className="mb-3 flex items-center gap-1.5 text-sm font-bold text-gold-dark"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V10M3 6l1.2-3h15.6L21 6a2.4 2.4 0 0 1-4.8 0 2.4 2.4 0 0 1-4.8 0A2.4 2.4 0 0 1 6.6 6 2.4 2.4 0 0 1 3 6Z" /><path d="M9 21v-6h6v6" /></svg>Shop Details</p>
              <div className="grid grid-cols-2 gap-3">
                <input type="text" value={f.shopName} onChange={e => setF({...f, shopName: e.target.value})} className="w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-amber-500" placeholder="Shop Name" required />
                <select value={f.shopCategory} onChange={e => setF({...f, shopCategory: e.target.value})} className="w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-amber-500" required>
                  <option value="">Category</option>
                  {categories.map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
              <textarea value={f.shopDescription} onChange={e => setF({...f, shopDescription: e.target.value})} className="mt-3 w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-amber-500" placeholder="Description (optional)" rows={2} />
              <input type="text" value={f.upiId} onChange={e => setF({...f, upiId: e.target.value})} className="mt-3 w-full rounded-btn border-2 px-4 py-3 text-sm outline-none focus:border-amber-500" placeholder="UPI ID for payments (e.g. yourname@okhdfcbank) — students pay this" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500"><svg className="h-3.5 w-3.5 inline" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg> Password</label>
                <PasswordField value={f.password} onChange={v => setF({...f, password: v})} placeholder="Min 4 chars" autoComplete="new-password" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Confirm</label>
                <PasswordField value={f.confirm} onChange={v => setF({...f, confirm: v})} placeholder="Repeat" autoComplete="new-password" />
              </div>
            </div>
            <button type="submit" disabled={loading} className="w-full rounded-btn bg-amber-600 px-6 py-3.5 text-base font-bold text-white hover:bg-amber-700 active:scale-[0.99] disabled:opacity-40">{loading ? 'Registering...' : 'Register Shop'}</button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-400">Already registered? <Link to="/login" className="font-bold text-gold-dark">Sign In</Link></p>
        </div>
      </div>
    </div>
  )
}

/* Login */
function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [err, setErr] = useState(''); const [loading, setLoading] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setLoading(true)
    try {
      const res = await api.post('/vendor/login', { username, password })
      localStorage.setItem('vendor_token', res.data.access_token)
      localStorage.setItem('vendor_user', JSON.stringify(res.data.user))
      navigate('/mobile')
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Login failed') }
    finally { setLoading(false) }
  }
  return (
    <div className="relative min-h-screen lg:grid lg:grid-cols-2">
      {/* Mobile background — faded restaurant photo (visible below lg only) */}
      <div className="absolute inset-0 overflow-hidden lg:hidden">
        <img
          src="https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=1000&q=80"
          alt=""
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="h-full w-full object-cover opacity-55"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-amber-50/70 via-white/35 to-white/70" />
      </div>
      {/* Left — brand panel with restaurant photo (desktop only) */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden bg-gradient-to-br from-stone-950 via-amber-950 to-amber-900 p-12 text-white">
        <img
          src="https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=1000&q=80"
          alt="A busy restaurant kitchen"
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="absolute inset-0 h-full w-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-stone-950/95 via-amber-950/50 to-stone-950/20" />
        <div className="relative">
          <span className="inline-flex items-center gap-2 rounded-pill border border-white/15 bg-white/10 px-4 py-1.5 text-xs font-bold uppercase tracking-widest text-amber-100 backdrop-blur-sm"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg> DETOMSITE</span>
          <h2 className="mt-8 max-w-md text-4xl font-black leading-tight">Run your shop,<br />from your phone.</h2>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-amber-100/90">Bring your campus shop online in minutes — accept orders, manage your menu, and grow your business with DETOMSITE.</p>
          <ul className="mt-8 space-y-4 text-sm text-amber-50">
            {[
              ['Your shop, online in minutes', 'Start & stop accepting orders with one tap'],
              ['Never miss an order', 'Instant alerts the moment a student orders'],
              ['Simple monthly share', 'Clear your 5% dues to the admin right from your dashboard'],
            ].map(([t, s]) => (
              <li key={t} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-gold/20 text-gold"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg></span>
                <span><b>{t}</b><span className="block text-xs font-normal text-amber-100/70">{s}</span></span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-gold/60">© {new Date().getFullYear()} DETOMSITE · Shopkeeper Portal</p>
      </div>
      {/* Right — login form (sits above the faded mobile photo) */}
      <div className="relative flex min-h-screen items-center justify-center bg-gradient-to-br from-amber-50/90 to-white/95 px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="rounded-card bg-white p-8 shadow-lg border-2 border-gold-light/40">
            <div className="mb-6 text-center">
              <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-card bg-gold-light text-gold-dark"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg></span>
              <h1 className="mt-3 text-2xl font-bold text-primary-dark">Shopkeeper Login</h1>
              <p className="text-sm text-gray-500">Sign in to manage your shop</p>
            </div>
            {err && <div className="mb-4 rounded-btn bg-red-50 border px-4 py-3 text-sm text-red-600">{err}</div>}
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-500"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" /></svg>Username</label>
                <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-amber-500" placeholder="Your username" required />
              </div>
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-500"><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>Password</label>
                <PasswordField value={password} onChange={setPassword} placeholder="Your password" autoComplete="current-password" />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-amber-600 px-6 py-3.5 text-base font-bold text-white hover:bg-amber-700 active:scale-[0.99] disabled:opacity-40">{loading ? 'Signing in...' : 'Sign In'}</button>
              <div className="text-center">
                <Link to="/forgot-password" className="text-xs font-bold text-gold-dark hover:text-gold-dark">Forgot password?</Link>
              </div>
            </form>
            <p className="mt-6 text-center text-sm text-gray-400">New shopkeeper? <Link to="/register" className="font-bold text-gold-dark">Register</Link></p>
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
      <div className="min-h-screen bg-gradient-to-br from-amber-50 to-white flex items-center justify-center px-4">
        <div className="w-full max-w-sm rounded-card bg-white p-8 shadow-lg border-2 border-gold-light/40 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-pill bg-primary-light text-primary"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m4 12.5 5 5L20 6.5" /></svg></span>
          <h1 className="mt-4 text-2xl font-bold text-primary-dark">Password Updated!</h1>
          <p className="mt-2 text-sm text-gray-500">Sign in with your new password.</p>
          <Link to="/login" className="mt-6 block w-full rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white hover:bg-primary-dark">Go to Login</Link>
        </div>
      </div>
    )
  }

  const inputCls = "w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm outline-none transition-all focus:border-amber-500"
  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 to-white flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="rounded-card bg-white p-8 shadow-lg border-2 border-gold-light/40">
          <div className="mb-6 text-center">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-card bg-gold-light text-gold-dark"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg></span>
            <h1 className="mt-3 text-2xl font-bold text-primary-dark">Forgot Password</h1>
            <p className="text-xs text-gray-500">Step {step === 'request' ? 1 : 2} of 2 · {step === 'request' ? 'Reset your password' : 'Enter the code & set a new password'}</p>
          </div>
          {err && <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-600">{err}</div>}
          {info && <div className="mb-4 rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3 text-sm font-semibold text-primary">{info}</div>}
          {step === 'request' && (
            <form onSubmit={requestOtp} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">Username or Email</label>
                <input type="text" value={identifier} onChange={e => setIdentifier(e.target.value)} className={inputCls} placeholder="Your username or registered email" required />
              </div>
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-amber-600 px-6 py-3.5 text-base font-bold text-white hover:bg-amber-700 disabled:opacity-40">{loading ? 'Sending...' : 'Send Code'}</button>
            </form>
          )}
          {step === 'otp' && (
            <form onSubmit={resetPw} className="space-y-4">
              <p className="text-xs leading-relaxed text-gray-500">A <b>6-digit code</b> was emailed to the address on your account. Enter it with your new password below — the code expires in 15 minutes.</p>
              <input type="text" inputMode="numeric" value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} className={`${inputCls} text-center text-2xl font-black tracking-[0.4em]`} placeholder="••••••" required />
              <PasswordField value={pw} onChange={setPw} placeholder="New password (min 4 chars)" autoComplete="new-password" />
              <PasswordField value={confirm} onChange={setConfirm} placeholder="Confirm new password" autoComplete="new-password" />
              <button type="submit" disabled={loading} className="w-full rounded-btn bg-amber-600 px-6 py-3.5 text-base font-bold text-white hover:bg-amber-700 disabled:opacity-40">{loading ? 'Saving...' : 'Verify Code & Update Password'}</button>
            </form>
          )}
          {step !== 'request' && (
            <p className="mt-5 text-center"><button type="button" onClick={() => { setStep('request'); setErr(''); setInfo('') }} className="text-xs font-bold text-gold-dark">← Start over</button></p>
          )}
          <p className="mt-5 text-center text-sm text-gray-400">Remembered it? <Link to="/login" className="font-bold text-gold-dark">Sign In</Link></p>
        </div>
      </div>
    </div>
  )
}

/* ─── Main Entry ─── */
export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<PortalHome />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/mobile/*" element={<VendorMobileApp />} />
        <Route path="/*" element={<PortalHome />} />
      </Routes>
    </Router>
  )
}

/* ════════════════════════════════════════════════════════════════
   VENDOR MOBILE APP (PWA) - Full mobile experience for shopkeepers
   ════════════════════════════════════════════════════════════════ */

/* Types */
interface Shop { id: string; name: string; category: string; description: string; rating: number; opening_time: string; closing_time: string; present: number; status: string; approval_status: string; shopkeeper_email: string; shopkeeper_name: string; phone: string; upi_id: string; upi_enabled: number; cod_enabled: number; orders_today: number; revenue_today: number; current_token: number }
interface Product { id: string; shop_id: string; name: string; description: string; price: number; pending_price: number | null; category: string; inventory: number; prep_time: number; available: number }
interface Order { id: string; token: number; student_name: string; student_phone: string; shop_id: string; shop_name: string; items: string; total: number; delivery_location: string; delivery_slot: string; status: string; payment_method?: string; created_at: string }

/* Delivery-window filters — the day is split into TWO time slots instead of
   the old Morning/Afternoon/Evening/Night labels: orders placed before
   12:30 PM and orders placed before 6:00 PM (IST). These are the same two
   windows that drive auto-acceptance and student cancellation. */
const SLOT_FILTERS = [
  { id: 'All', l: 'All' },
  { id: 'before-1230', l: 'Before 12:30 PM' },
  { id: 'before-1830', l: 'Before 6:00 PM' },
]

/* Parse a stored timestamp into an IST clock (hours/minutes in Asia/Kolkata)
   so orders can be bucketed into the two delivery windows regardless of the
   phone's timezone. */
function istTime(createdAt?: string): { h: number; m: number } | null {
  const raw = String(createdAt || '').trim()
  if (!raw) return null
  let iso = raw
  if (!/T/.test(raw) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(raw)) iso = raw.replace(' ', 'T') + '+05:30'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null
  const s = new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  return { h: s.getHours(), m: s.getMinutes() }
}

/* Which delivery window an order belongs to, based on when it was placed:
   'before-1230' (before 12:30 PM), 'before-1830' (before 6:00 PM), or
   'after-1830' for orders placed after both windows. */
function slotBucket(createdAt?: string): string {
  const t = istTime(createdAt)
  if (!t) return 'after-1830'
  const mins = t.h * 60 + t.m
  if (mins < 12 * 60 + 30) return 'before-1230'
  if (mins < 18 * 60 + 30) return 'before-1830'
  return 'after-1830'
}
const STATUS_FILTERS = [
  { id: 'all', l: 'All statuses' },
  { id: 'pending', l: 'Pending' },
  { id: 'accepted', l: 'Accepted' },
  { id: 'completed', l: 'Completed' },
]

/* Cook summary — aggregate every order's items into a name → total-quantity
   map, so the vendor can see at a glance how much of each dish to prepare.
   Order items are stored as "2x Fried Rice, 4x Noodles"; the regex also
   tolerates "×" and items without a quantity prefix (treated as 1). */
function buildItemSummary(orders: Order[]): { name: string; qty: number }[] {
  const totals: Record<string, number> = {}
  for (const o of orders) {
    const raw = String(o.items || '')
    for (const part of raw.split(',')) {
      const item = part.trim()
      if (!item) continue
      const m = item.match(/^(\d+)\s*[xX×]\s*(.+)$/)
      if (m) {
        const name = m[2].trim()
        const qty = parseInt(m[1], 10) || 1
        totals[name] = (totals[name] || 0) + qty
      } else {
        totals[item] = (totals[item] || 0) + 1
      }
    }
  }
  return Object.entries(totals).map(([name, qty]) => ({ name, qty })).sort((a, b) => b.qty - a.qty)
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

/* One-tap call button for an order — dials the student's mobile directly. */
function CallBtn({ phone, name, compact }: { phone?: string; name?: string; compact?: boolean }) {
  if (!phone) return null
  const clean = phone.replace(/[^+\d]/g, '')
  if (compact) {
    return (
      <a href={`tel:${clean}`} title={`Call ${name || 'student'}`} aria-label={`Call ${name || 'student'}`}
        className="flex h-7 w-7 items-center justify-center rounded-pill bg-primary-light text-primary transition-colors hover:bg-primary-light/80 active:scale-90">
        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>
      </a>
    )
  }
  return (
    <a href={`tel:${clean}`}
      className="inline-flex items-center gap-1.5 rounded-sm bg-primary-light px-3 py-1.5 text-xs font-bold text-primary transition-colors hover:bg-primary-light/80 active:scale-95">
      <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>
      Call {name?.split(' ')[0] || 'student'}
    </a>
  )
}

/* ─── QR Scanner — reads the student's order QR with the phone camera ───
   Uses the native BarcodeDetector API (Chrome/Android, no library needed).
   A manual entry fallback is provided for browsers without BarcodeDetector. */
function OrderScanner({ onDone }: { onDone: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [mode, setMode] = useState<'camera' | 'manual'>('camera')
  const [scanning, setScanning] = useState(false)
  const [cameraErr, setCameraErr] = useState('')
  const [manualCode, setManualCode] = useState('')
  const [order, setOrder] = useState<Order | null>(null)
  const [lookupErr, setLookupErr] = useState('')
  const [acting, setActing] = useState(false)

  const supportsBarcode = typeof window !== 'undefined' && 'BarcodeDetector' in window

  const stopCamera = () => {
    if (videoRef.current?.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream
      stream.getTracks().forEach(t => t.stop())
      videoRef.current.srcObject = null
    }
    setScanning(false)
  }

  const lookup = async (code: string) => {
    const raw = String(code || '').trim()
    if (!raw) return
    setLookupErr(''); setOrder(null)
    try {
      const res = await api.get('/vendor/orders/lookup', { params: { code: raw } })
      setOrder(res.data || null)
      if (res.data) stopCamera()
    } catch (err: any) {
      setLookupErr(err?.response?.data?.detail || 'Could not find that order')
      // A bad/unknown code shouldn't kill the scanner — turn the camera back on.
      if (mode === 'camera') setTimeout(() => { setOrder(null); startCamera() }, 800)
    }
  }

  const startCamera = async () => {
    setCameraErr('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      if (!videoRef.current) { stream.getTracks().forEach(t => t.stop()); return }
      videoRef.current.srcObject = stream
      await videoRef.current.play()
      setScanning(true)
    } catch { setCameraErr('Could not open the camera. Use the manual entry below instead.'); setMode('manual') }
  }

  /* Detection loop — runs while the camera is live. */
  useEffect(() => {
    if (!scanning || !videoRef.current || !supportsBarcode) return
    let cancelled = false
    let timer: number | undefined
    /* BarcodeDetector is a synchronous constructor: `new BarcodeDetector(...)`.
       The old code called a non-existent static .create() method, which left
       the detector undefined and the loop never picked up any QR code. */
    let detector: any = null
    try {
      detector = new (window as any).BarcodeDetector({ formats: ['qr_code'] })
    } catch {
      detector = null
      if (!cancelled) {
        setCameraErr('QR scanning is not available in this browser — use Manual entry.')
        setScanning(false)
        setMode('manual')
      }
    }
    const tick = async () => {
      if (cancelled) return
      const video = videoRef.current
      if (detector && video && video.readyState >= 2) {
        try {
          const codes = await detector.detect(video)
          if (!cancelled && codes && codes.length > 0 && codes[0].rawValue) {
            stopCamera()
            lookup(codes[0].rawValue)
            return
          }
        } catch { /* frame skipped — keep scanning */ }
      }
      timer = window.setTimeout(tick, 250)
    }
    if (detector) timer = window.setTimeout(tick, 400)
    return () => { cancelled = true; if (timer) clearTimeout(timer); stopCamera() }
  }, [scanning, supportsBarcode])

  const setStatus = async (orderId: string, status: string) => {
    await api.patch(`/vendor/orders/${orderId}/status`, { status })
  }
  const confirmPaid = async (orderId: string) => {
    await api.post(`/vendor/orders/${orderId}/payment-received`)
  }
  const action = async (fn: () => Promise<void>) => {
    setActing(true)
    try { await fn(); onDone(); setOrder(null) }
    catch { setLookupErr('Action failed — please try again') }
    finally { setActing(false) }
  }

  const btn = "rounded-sm px-4 py-2.5 text-sm font-bold text-white transition-all active:scale-[0.98] disabled:opacity-40"

  return (
    <div>
      <h2 className="text-lg font-bold text-primary mb-1">Scan Order QR</h2>
      <p className="text-xs text-gray-500 mb-4">Point the camera at the student's order QR — or type the code/order ID manually.</p>

      {/* Mode toggle */}
      <div className="mb-4 flex rounded-btn bg-gray-100 p-1">
        <button onClick={() => { setMode('camera'); setLookupErr('') }} className={`flex-1 rounded-sm py-2 text-xs font-bold transition-all ${mode === 'camera' ? 'bg-white text-primary shadow' : 'text-gray-500'}`}>📷 Camera</button>
        <button onClick={() => { setMode('manual'); setLookupErr('') }} className={`flex-1 rounded-sm py-2 text-xs font-bold transition-all ${mode === 'manual' ? 'bg-white text-primary shadow' : 'text-gray-500'}`}>⌨️ Manual</button>
      </div>

      {mode === 'camera' && (
        <div className="rounded-btn overflow-hidden border border-gray-200 bg-black">
          <video ref={videoRef} playsInline muted className="h-64 w-full object-cover" />
          {!scanning && !order && (
            <div className="p-4 text-center">
              <button onClick={startCamera} className="rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white hover:bg-primary">Start Camera</button>
              {cameraErr && <p className="mt-2 text-xs text-gold">{cameraErr}</p>}
              {!supportsBarcode && <p className="mt-2 text-xs text-gold">This browser has no built-in QR scanner — use Manual entry.</p>}
            </div>
          )}
          {scanning && <div className="p-3 text-center text-xs font-bold text-primary/80">Scanning… point at the QR code</div>}
        </div>
      )}

      {mode === 'manual' && (
        <div className="rounded-btn border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500 mb-2">Type the code from the student's order (or the order ID).</p>
          <div className="flex gap-2">
            <input value={manualCode} onChange={e => setManualCode(e.target.value)} placeholder="DETOMSITE-ORDER:… or order ID" className="flex-1 rounded-sm border px-3 py-2.5 text-sm outline-none focus:border-primary-light/200" />
            <button onClick={() => lookup(manualCode)} className="rounded-sm bg-primary px-4 py-2.5 text-sm font-bold text-white hover:bg-primary">Find</button>
          </div>
        </div>
      )}

      {lookupErr && <div className="mt-3 rounded-sm bg-red-100 border border-red-200 px-4 py-3 text-sm font-medium text-red-600">{lookupErr}</div>}

      {/* Found order card */}
      {order && (
        <div className="mt-4 rounded-btn bg-white p-4 shadow-sm border border-primary/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xl font-black text-primary-dark">#{order.token}</span>
            <span className="rounded-pill px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-primary bg-primary-light">✓ Found</span>
          </div>
          <p className="text-sm font-semibold text-gray-700">{order.student_name} · 📞 {order.student_phone || '—'}</p>
          <p className="mt-1 text-sm text-gray-600">{order.items}</p>
          <p className="mt-1 text-xs text-gray-500">📍 {order.delivery_location} · {order.delivery_slot} · ₹{order.total} · {order.status}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(order.status === 'Pending Acceptance' || order.status === 'Pending Payment') && (
              <button disabled={acting} onClick={() => action(() => setStatus(order!.id, 'Accepted'))} className={`${btn} bg-primary hover:bg-primary`}>Accept</button>
            )}
            {order.status === 'Pending Payment' && (
              <button disabled={acting} onClick={() => action(() => confirmPaid(order!.id))} className={`${btn} bg-blue-600 hover:bg-blue-500`}>Payment Received ✓</button>
            )}
            {order.status === 'Accepted' && (
              <button disabled={acting} onClick={() => action(() => setStatus(order!.id, 'Preparing'))} className={`${btn} bg-yellow-500 hover:bg-yellow-600`}>Start Preparing</button>
            )}
            {order.status === 'Preparing' && (
              <button disabled={acting} onClick={() => action(() => setStatus(order!.id, 'Ready'))} className={`${btn} bg-primary hover:bg-primary`}>Mark Ready ✓</button>
            )}
            {order.status === 'Ready' && (
              <button disabled={acting} onClick={() => action(() => setStatus(order!.id, 'Completed'))} className={`${btn} bg-primary hover:bg-primary`}>Complete Order</button>
            )}
            <button disabled={acting} onClick={() => { setOrder(null); setLookupErr(''); if (mode === 'camera') startCamera() }} className="rounded-sm border px-4 py-2.5 text-sm font-bold text-gray-600">Scan Next</button>
          </div>
        </div>
      )}
    </div>
  )
}

function VendorMobileApp() {
  const navigate = useNavigate()
  const [page, setPage] = useState('dashboard')
  const [shop, setShop] = useState<Shop | null>(null)
  const [orders, setOrders] = useState<Order[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [stats, setStats] = useState<any>({})
  const [msg, setMsg] = useState(''); const [err, setErr] = useState('')
  const [productForm, setProductForm] = useState({ name: '', price: '', category: 'Food', description: '', inventory: '10', prep_time: '10' })
  const [upiId, setUpiId] = useState('')
  const [upiEnabled, setUpiEnabled] = useState(true)
  const [codEnabled, setCodEnabled] = useState(true)
  const [approvalStatus, setApprovalStatus] = useState<string>('loading')
  const [historyRange, setHistoryRange] = useState('today')
  const [history, setHistory] = useState<any>({ orders: [], daily: [], revenue: 0, count: 0 })
  const [slotFilter, setSlotFilter] = useState('All')
  const [statusFilter, setStatusFilter] = useState('all')  // all | pending | accepted | completed
  const [todayOnly, setTodayOnly] = useState(true)
  const [pushState, setPushState] = useState<'checking' | 'disabled' | 'unsupported' | 'denied' | 'unsubscribed' | 'subscribed' | 'error'>('checking')
  const [pushPublicKey, setPushPublicKey] = useState('')
  const [pushReason, setPushReason] = useState('')
  const [pushError, setPushError] = useState('')
  const [sendingTest, setSendingTest] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const lastRefresh = useRef(0)
  const [showDuesQr, setShowDuesQr] = useState(false)
  const [payingDues, setPayingDues] = useState(false)
  const vendor = JSON.parse(localStorage.getItem('vendor_user') || '{}')

  /* Format a date as YYYY-MM-DD in Indian time (Asia/Kolkata) — the same
     day the server uses for the dashboard's "today", so the filter and the
     dashboard can never disagree even if the phone's clock is in another
     timezone. The server also resolves named ranges itself (range= param). */
  const istDay = (d: Date) =>
    new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)

  const loadHistory = async (range: string) => {
    const today = new Date()
    let from = ''; let to = istDay(today)
    if (range === 'today') from = istDay(today)
    else if (range === 'yesterday') { const y = new Date(today); y.setDate(y.getDate() - 1); from = to = istDay(y) }
    else if (range === 'week') { const w = new Date(today); w.setDate(w.getDate() - 6); from = istDay(w) }
    try {
      const res = await api.get('/vendor/history', { params: range === 'all' ? { from, to } : { range, from, to } })
      setHistory(res.data || { orders: [], daily: [], revenue: 0, count: 0 })
      setErr('')
    } catch { setErr('Failed to load history') }
  }

  const selectHistoryRange = (range: string) => { setHistoryRange(range); loadHistory(range) }

  const isLoggedIn = !!localStorage.getItem('vendor_token')

  const loadDashboard = async (silent = false): Promise<boolean> => {
    try {
      const res = await api.get('/vendor/dashboard')
      const data = res.data
      setShop(data.shop || null)
      setUpiId(data.shop?.upi_id || '')
      /* !! handles BOTH representations the stores return: SQLite gives 0/1
         integers while Supabase (Postgres) gives real booleans. The old
         `!== 0` check broke on Supabase — `false !== 0` is `true`, so a shop
         that had just turned UPI off would flip right back to "on" after the
         refresh that follows every toggle. */
      setUpiEnabled(data.shop ? !!data.shop.upi_enabled : true)
      setCodEnabled(data.shop ? !!data.shop.cod_enabled : true)
      setOrders(data.orders || [])
      setStats(data.stats || {})
      setApprovalStatus(data.shop?.approval_status || 'not_found')
      return true
    } catch { if (!silent) setErr('Failed to load dashboard'); return false }
  }

  const loadProducts = async (silent = false) => {
    try { const res = await api.get('/vendor/products'); setProducts(res.data || []) }
    catch { if (!silent) setErr('Failed to load products') }
  }

  /* Refresh everything (dashboard + products). The header button and the
     app-regains-focus event both use this, so tapping a push notification
     opens the app with fresh orders. The timestamp guard dedupes the
     focus + visibilitychange pair that both fire when the app returns. */
  const refreshAll = async (silent = false) => {
    const now = Date.now()
    if (silent && now - lastRefresh.current < 2000) return
    lastRefresh.current = now
    if (!silent) setRefreshing(true)
    try { await Promise.all([loadDashboard(silent), loadProducts(silent)]) }
    finally { if (!silent) setTimeout(() => setRefreshing(false), 400) }
  }

  /* ─── Web push notifications ─── */
  /* Start the app service worker and wait until it is really ACTIVE.
     navigator.serviceWorker.ready can wait forever if the worker gets stuck,
     so we poll the registration state directly and always settle with an answer. */
  const ensureServiceWorker = async (timeoutMs = 12000): Promise<ServiceWorkerRegistration> => {
    const registration = await navigator.serviceWorker.register('/mobile/sw.js', { updateViaCache: 'none' })
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      const reg = await navigator.serviceWorker.getRegistration()
      if (reg?.active || registration.active || navigator.serviceWorker.controller) return reg || registration
      await new Promise((r) => setTimeout(r, 400))
    }
    const state = registration.active ? 'active' : registration.installing ? 'installing' : registration.waiting ? 'waiting' : 'none'
    throw new Error('service-worker-timeout:' + state)
  }

  /* Turn a service-worker start failure into a helpful, specific message. */
  const swStartError = (err: any) => {
    const detail = err?.message || ''
    if (detail.startsWith('service-worker-timeout')) {
      const state = detail.split(':')[1]
      if (state === 'installing' || state === 'waiting') {
        return 'The app service worker got stuck while starting. Close the app and reopen it, or re-install it from the portal home page, then try again.'
      }
      return 'The app service worker did not start in this browser. You need: the HTTPS site (https://...), a normal tab (not private), and service workers allowed. Check the browser console for the exact reason.'
    }
    if (err?.name === 'TypeError' && /mime|script|register/i.test(detail)) {
      return 'The service worker file is not being served correctly. Open /mobile/sw.js in your browser — it should show JavaScript code, not HTML.'
    }
    return 'Could not start the app service worker: ' + (detail || 'unknown error')
  }

  const checkPushSupport = async () => {
    try {
      const res = await api.get('/vendor/push/config')
      const cfg = res.data || {}
      if (!cfg.enabled || !cfg.vapid_public_key) {
        setPushReason(cfg.reason || 'Push alerts are not configured on the server yet (VAPID keys missing).')
        setPushState('disabled')
        return
      }
      setPushReason('')
      setPushPublicKey(cfg.vapid_public_key)
      if (!window.isSecureContext) {
        setPushError('Push needs a secure (HTTPS) connection. Open the deployed app URL (https://...) instead of a local or LAN address.')
        setPushState('unsupported')
        return
      }
      if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
        setPushState('unsupported')
        return
      }
      let reg
      try {
        reg = await ensureServiceWorker()
      } catch (err) {
        setPushError(swStartError(err))
        setPushState('unsupported')
        return
      }
      try {
        const sub = await reg.pushManager.getSubscription()
        if (sub) {
          // Re-register the current subscription — browsers rotate push keys and
          // endpoints over time, so this keeps the server copy fresh.
          try {
            await api.post('/vendor/push/subscribe', {
              endpoint: sub.endpoint,
              keys: { p256dh: pushKeyToBase64(sub.getKey('p256dh')), auth: pushKeyToBase64(sub.getKey('auth')) },
            })
          } catch { /* best-effort — the app still treats it as subscribed */ }
          setPushState('subscribed')
        }
        else if (Notification.permission === 'denied') setPushState('denied')
        else setPushState('unsubscribed')
      } catch {
        setPushState('unsubscribed')
      }
    } catch {
      setPushReason('The server could not be reached to check push status.')
      setPushState('disabled')
    }
  }

  const enablePush = async () => {
    setPushError('')
    try {
      if (!pushPublicKey) { setErr('Notifications are not configured on the server yet.'); return }
      if (!window.isSecureContext) {
        const msg = 'Push needs a secure (HTTPS) connection — open the deployed app URL (https://...) instead of a local or LAN address, then try again.'
        setErr(msg)
        setPushError(msg)
        setPushState('unsupported')
        return
      }
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) { setErr("This browser doesn't support push notifications."); return }
      if (Notification.permission === 'denied') { setPushState('denied'); setErr('Notifications are blocked — allow them in your browser/site settings.'); return }
      let permission: NotificationPermission = Notification.permission
      if (permission === 'default') permission = await Notification.requestPermission()
      if (permission !== 'granted') { setPushState('denied'); setErr('Permission was not granted.'); return }
      // Make sure the app's service worker is actually ACTIVE before we try to
      // subscribe — force-register it (bypasses stale cached copies) and wait.
      let reg
      try {
        reg = await ensureServiceWorker()
      } catch (err) {
        const msg = swStartError(err)
        setErr(msg)
        setPushError(msg)
        setPushState('unsupported')
        return
      }
      let sub = await reg.pushManager.getSubscription()
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(pushPublicKey),
        })
      }
      await api.post('/vendor/push/subscribe', {
        endpoint: sub.endpoint,
        keys: { p256dh: pushKeyToBase64(sub.getKey('p256dh')), auth: pushKeyToBase64(sub.getKey('auth')) },
      })
      setPushState('subscribed')
      setMsg("Order notifications enabled — you'll be alerted the moment an order arrives")
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Could not enable notifications — the app service worker is not active in this browser.'
      setErr(msg)
      setPushError(msg)
      setPushState('error')
    }
  }

  const sendTestPush = async () => {
    setSendingTest(true)
    setPushError('')
    try {
      const res = await api.post('/vendor/push/test')
      const data = res.data || {}
      if (data.ok) setMsg(data.detail || 'Test notification sent!')
      else setPushError(data.detail || 'Test push failed')
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Could not send test notification'
      setPushError(msg)
    } finally { setSendingTest(false) }
  }

  const disablePush = async () => {
    setPushError('')
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        try { await api.delete('/vendor/push/subscribe', { params: { endpoint: sub.endpoint } }) } catch { /* best-effort */ }
        await sub.unsubscribe()
      }
      setPushState('unsubscribed')
      setMsg('Order notifications disabled')
    } catch { setErr('Could not disable notifications') }
  }

  useEffect(() => {
    if (!isLoggedIn) { navigate('/login'); return }
    checkPushSupport()
    /* Boot: load the dashboard, and if that first request fails (flaky
       network right after the app opens), retry every 3s until it succeeds.
       Without this the Start/Stop toggle and the orders list could stay
       hidden for up to 30s — the length of the auto-refresh interval. */
    const boot = async () => {
      let ok = await loadDashboard(true)
      loadProducts(true)
      for (let attempt = 0; attempt < 6 && !ok; attempt++) {
        await new Promise(r => setTimeout(r, 3000))
        ok = await loadDashboard(true)
      }
    }
    void boot()
    // Refreshing on focus keeps the app current when the vendor returns to it
    // (e.g. after tapping a push notification that opens the app).
    const onVisible = () => { if (document.visibilityState === 'visible') refreshAll(true) }
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', onVisible)
    // Auto-reload orders & products every 30s so new orders appear on their
    // own — but only while the app tab is visible, so a backgrounded vendor
    // app stops pulling the dashboard every 30s.
    const auto = setInterval(() => { if (document.visibilityState === 'visible') refreshAll(true) }, 30000)
    return () => {
      window.removeEventListener('focus', onVisible)
      document.removeEventListener('visibilitychange', onVisible)
      clearInterval(auto)
    }
  }, [])

  const logout = () => { localStorage.removeItem('vendor_token'); localStorage.removeItem('vendor_user'); navigate('/') }

  const statusMsg = (s: string) => ({
    Confirmed: 'Order confirmed via SMS — preparing now',
    Accepted: 'Order accepted — preparing now',
    Preparing: 'Order is being prepared',
    Ready: 'Order ready for pickup/delivery',
    Completed: 'Order completed',
    Cancelled: 'Order rejected',
  } as Record<string, string>)[s] || `Order ${s}`

  const updateOrderStatus = async (orderId: string, status: string) => {
    try { await api.patch(`/vendor/orders/${orderId}/status`, { status }); setMsg(statusMsg(status)); loadDashboard() }
    catch { setErr('Failed to update order') }
  }

  const confirmPayment = async (orderId: string) => {
    try { await api.post(`/vendor/orders/${orderId}/payment-received`); setMsg('Payment received — order completed! 🎉'); loadDashboard() }
    catch (err: any) { setErr(err?.response?.data?.detail || 'Failed to confirm payment') }
  }

  const togglePresent = async () => {
    if (!shop || shop.approval_status !== 'Approved') { setErr('Shop not approved yet'); return }
    try { await api.patch('/vendor/shop', { present: !shop.present }); loadDashboard() }
    catch { setErr('Failed to toggle') }
  }

  /* Admin share (5% monthly fee) payment — the vendor's "Pay" tap opens a
     modal showing the ADMIN's UPI QR code so the vendor can scan it with
     their own UPI app (GPay / PhonePe / Paytm). The deep-link "Open UPI App"
     button is kept as a one-tap alternative. The share is only recorded
     (as Pending, for the admin to mark Received) once the vendor confirms. */
  const adminUpi = (stats.admin_upi_id || '').trim()
  const adminReceiver = (stats.admin_receiver_name || 'DETOMSITE Admin').trim()
  const duesAmount = stats.platform_fee_due ?? 0
  const duesQrUri = adminUpi
    ? `upi://pay?pa=${encodeURIComponent(adminUpi)}&pn=${encodeURIComponent(adminReceiver)}&am=${upiAmount(duesAmount).toFixed(2)}&cu=INR&mode=04&tn=${encodeURIComponent('DETOMSITE Admin Share')}`
    : ''
  const openDuesPay = () => {
    if (!shop) return
    if (!adminUpi) { setErr('Admin has not set their UPI ID yet — contact the admin.'); return }
    if (duesAmount <= 0) { setMsg('No dues to pay this month 🎉'); return }
    setShowDuesQr(true)
  }
  const recordDuesPaid = async () => {
    setPayingDues(true)
    try {
      await api.post('/vendor/dues/pay', { amount: duesAmount })
      setShowDuesQr(false)
      setMsg(`Share payment of ₹${duesAmount} recorded — the admin marks it received once it lands in their bank.`)
      loadDashboard()
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Could not record the payment — please try again.') }
    finally { setPayingDues(false) }
  }

  const addProduct = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/vendor/products', {
        name: productForm.name, price: parseInt(productForm.price), category: productForm.category,
        description: productForm.description, inventory: parseInt(productForm.inventory) || 10,
        prep_time: parseInt(productForm.prep_time) || 10,
      })
      setMsg('Product added!'); setProductForm({ name: '', price: '', category: 'Food', description: '', inventory: '10', prep_time: '10' })
      loadProducts()
    } catch (err: any) { setErr(err?.response?.data?.detail || 'Failed to add product') }
  }

  const updateProductAvailable = async (productId: string, available: boolean) => {
    try { await api.patch(`/vendor/products/${productId}`, { available }); setMsg(available ? 'Product enabled' : 'Product disabled'); loadProducts() }
    catch { setErr('Failed') }
  }

  const deleteProduct = async (productId: string) => {
    if (!window.confirm('Delete this product permanently?')) return
    try { await api.delete(`/vendor/products/${productId}`); setMsg('Product removed'); loadProducts() }
    catch { setErr('Failed to delete product') }
  }

  const saveUpi = () => {
    const v = upiId.trim()
    if (!v) { setErr('Enter a UPI ID first'); return }
    api.patch('/vendor/shop', { upi_id: v })
      .then(() => { setMsg('UPI ID saved! Students can pay you by scanning the QR when UPI payments are turned on.'); loadDashboard() })
      .catch(() => setErr('Failed to save UPI'))
  }

  /* Payment method toggles — the shopkeeper decides whether students can pay
     via UPI/QR, Cash on Delivery, or both. At least one must stay on so the
     shop never ends up unable to take any payment. */
  const togglePayment = async (key: 'upi_enabled' | 'cod_enabled', value: boolean) => {
    const turningOffUpi = key === 'upi_enabled' && !value
    const turningOffCod = key === 'cod_enabled' && !value
    if ((turningOffUpi && !codEnabled) || (turningOffCod && !upiEnabled)) {
      setErr('Keep at least one payment method enabled — turn the other on first.')
      return
    }
    try {
      await api.patch('/vendor/shop', { [key]: value })
      if (key === 'upi_enabled') setUpiEnabled(value)
      else setCodEnabled(value)
      setMsg(value ? 'Payment method enabled — students can now use it at checkout.' : 'Payment method turned off — students will no longer see it at checkout.')
      loadDashboard()
    } catch { setErr('Failed to update payment settings — please try again.') }
  }

  const upiQrUri = upiId.trim() ? buildShopUpiUri(upiId.trim(), shop?.name || 'DETOMSITE') : ''

  if (!isLoggedIn) return null

  /* Combined filters: delivery slot + today-only + status. Lets the vendor see
     e.g. "today's evening orders that are still pending" in one tap. */
  const todayStr = istDay(new Date())
  let slotOrders = slotFilter === 'All' ? orders : orders.filter(o => slotBucket(o.created_at) === slotFilter)
  if (todayOnly) slotOrders = slotOrders.filter(o => String(o.created_at || '').slice(0, 10) === todayStr)
  if (statusFilter === 'pending') slotOrders = slotOrders.filter(o => o.status === 'Pending Acceptance' || o.status === 'Pending Payment')
  else if (statusFilter === 'accepted') slotOrders = slotOrders.filter(o => ['Confirmed', 'Accepted', 'Preparing', 'Ready'].includes(o.status))
  else if (statusFilter === 'completed') slotOrders = slotOrders.filter(o => o.status === 'Completed' || o.status === 'Cancelled')
  const pendingOrders = slotOrders.filter(o => o.status === 'Pending Acceptance' || o.status === 'Pending Payment')
  const acceptedOrders = slotOrders.filter(o => ['Confirmed', 'Accepted', 'Preparing', 'Ready'].includes(o.status))
  /* Cook summary — totals every live (not yet completed/cancelled/failed)
     order's items so the vendor knows how much of each dish to prepare. It
     respects the today/slot/status filters above. */
  const liveOrders = slotOrders.filter(o => !['Completed', 'Cancelled', 'Failed'].includes(o.status))
  const itemSummary = buildItemSummary(liveOrders)

  /* ─── Mobile App Layout ─── */
  return (
    <div className="min-h-screen max-w-md mx-auto bg-gray-50 pb-20">
      {/* Header */}
      <div className="bg-primary text-white px-4 py-4 sticky top-0 z-10">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 font-bold text-lg">
              <svg className="h-5 w-5 text-gold" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V10M3 6l1.2-3h15.6L21 6a2.4 2.4 0 0 1-4.8 0 2.4 2.4 0 0 1-4.8 0A2.4 2.4 0 0 1 6.6 6 2.4 2.4 0 0 1 3 6Z" /><path d="M9 21v-6h6v6" /></svg>
              {shop?.name || 'Vendor App'}
            </h1>
            <p className="text-xs text-primary/60">{vendor.name}</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => refreshAll(false)} title="Refresh orders & products" className={`flex h-8 w-8 items-center justify-center rounded-pill bg-primary text-white transition-colors hover:bg-primary active:scale-95 ${refreshing ? 'animate-spin' : ''}`}>
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><polyline points="21 3 21 9 15 9" /></svg>
            </button>
            <button onClick={logout} className="text-xs text-primary/60 bg-primary px-3 py-1.5 rounded-pill">Logout</button>
          </div>
        </div>
      </div>

      {/* Approval Status */}
      {approvalStatus === 'Pending Approval' && (
        <div className="bg-gold-light border-b-2 border-gold-light/60 px-4 py-3">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-gold-dark"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>Pending Admin Approval</p>
          <p className="text-xs text-gold-dark">Your shop is under review. You'll be able to start selling once approved.</p>
        </div>
      )}
      {approvalStatus === 'Rejected' && (
        <div className="bg-red-100 border-b-2 border-red-200 px-4 py-3">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-red-800"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17.5v.5" /></svg>Shop Rejected</p>
          <p className="text-xs text-red-600">Contact admin for more information.</p>
        </div>
      )}

      {/* Status & Toggle */}
      {shop && approvalStatus === 'Approved' && (
        <div className="bg-white border-b px-4 py-3 flex items-center justify-between">
          <div>              <p className="flex items-center gap-1.5 text-sm font-semibold text-gray-700">
                <span className={`h-2 w-2 rounded-pill ${shop.present ? 'bg-primary' : 'bg-red-500'}`} />
                {shop.present ? 'Accepting Orders' : 'Not Accepting'}
              </p>
            <p className="text-xs text-gray-500">Hours {shop.opening_time} - {shop.closing_time} · <span className="font-semibold">Open until you press Stop — no auto-close</span></p>
          </div>
          <button onClick={togglePresent} className={`rounded-btn px-4 py-2 text-sm font-bold ${shop.present ? 'bg-red-500 text-white' : 'bg-primary text-white'}`}>
            {shop.present ? 'Stop' : 'Start'}
          </button>
        </div>
      )}

      {/* Order Alerts banner */}
      {(pushState === 'unsubscribed' || pushState === 'denied' || pushState === 'disabled') && (
        <div className="mx-4 mt-3 rounded-btn border border-blue-200 bg-blue-50 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="flex items-center gap-1.5 text-sm font-bold text-blue-800"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" /><path d="M10 20a2.2 2.2 0 0 0 4 0" /></svg>Order alerts are off</p>
              <p className="text-xs text-blue-600">
                {pushState === 'denied'
                  ? 'Notifications are blocked in your browser — allow them to get order alerts.'
                  : pushState === 'disabled'
                    ? 'Order alerts are not configured on the server yet.'
                    : 'Get a phone notification the moment an order comes in.'}
              </p>
            </div>
            {pushState === 'unsubscribed' && (
              <button onClick={enablePush} className="shrink-0 rounded-sm bg-blue-600 px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-blue-500">Enable</button>
            )}
          </div>
        </div>
      )}

      {/* Stats Bar */}
      {shop && (
        <div className="grid grid-cols-3 gap-2 px-4 py-3 bg-white border-b">
          <div className="text-center"><p className="text-lg font-bold text-primary">{stats.today_orders ?? shop.orders_today}</p><p className="text-xs text-gray-500">Orders Today</p></div>
          <div className="text-center"><p className="text-lg font-bold text-primary">₹{stats.today_revenue ?? shop.revenue_today}</p><p className="text-xs text-gray-500">Earned Today</p></div>
          <div className="text-center"><p className="text-lg font-bold text-primary">{shop.current_token}</p><p className="text-xs text-gray-500">Token</p></div>
        </div>
      )}

      {/* Admin Dues (5% platform fee) */}
      {shop && approvalStatus === 'Approved' && (
        <div className="mx-4 mt-3 rounded-btn border border-gold-light/60 bg-amber-50 px-4 py-3">
          <div className="flex items-center justify-between">
            <div>                  <p className="text-sm font-bold text-gold-dark">Admin Share (5% of this month's earnings)</p>
              <p className="text-xs text-gold-dark">Earned this month: ₹{stats.month_revenue ?? stats.today_revenue ?? 0} · Your share: ₹{stats.platform_fee_due ?? 0}</p>
              {stats.share_paid_month ?? stats.share_paid_today ? (
                <p className="mt-1 text-xs font-bold text-primary">Paid this month — the admin has received your share.</p>
              ) : (
                <p className="mt-1 text-xs text-gold-dark">Not paid yet — tap Pay to send this month's share to the admin's UPI.</p>
              )}
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <span className={`rounded-sm px-3 py-1 text-sm font-bold text-white ${(stats.share_paid_month ?? stats.share_paid_today) ? 'bg-primary' : 'bg-amber-600'}`}>₹{stats.platform_fee_due ?? 0}</span>
              <button onClick={openDuesPay} disabled={stats.share_paid_month ?? stats.share_paid_today} className={`rounded-sm px-3 py-1.5 text-xs font-bold text-white ${(stats.share_paid_month ?? stats.share_paid_today) ? 'bg-gray-300 text-gray-500' : 'bg-primary'}`}>{(stats.share_paid_month ?? stats.share_paid_today) ? 'Paid ✓' : 'Pay'}</button>
            </div>
          </div>
        </div>
      )}

      {/* Notifications */}
      {msg && <div className="mx-4 mt-3 rounded-btn bg-primary-light border border-primary-light/50 px-4 py-3 text-sm font-medium text-primary">{msg}</div>}
      {err && <div className="mx-4 mt-3 rounded-btn bg-red-100 border border-red-200 px-4 py-3 text-sm font-medium text-red-600">{err}</div>}

      {/* Page Content */}
      <div className="px-4 py-4">
        {!shop && approvalStatus === 'loading' ? (
          <div className="py-10 text-center">
            <p className="text-sm font-medium text-gray-400">Loading your shop…</p>
          </div>
        ) : (
          <>
        {/* Dashboard Tab */}
        {page === 'dashboard' && (
          <div>
            {/* Order filters: today + delivery slot + status */}
            <div className="mb-5 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-bold uppercase tracking-wide text-gray-500">Order filters</p>
                <button onClick={() => setTodayOnly(!todayOnly)}
                  className={`shrink-0 rounded-pill px-3.5 py-1.5 text-xs font-bold transition-all ${todayOnly ? 'bg-primary text-white shadow' : 'bg-white border border-gray-200 text-gray-600 hover:border-primary/50'}`}>
                  {todayOnly ? 'Today only ✓' : 'Show today only'}
                </button>
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {SLOT_FILTERS.map(s => (
                  <button key={s.id} onClick={() => setSlotFilter(s.id)}
                    className={`shrink-0 rounded-pill px-4 py-2 text-xs font-bold transition-all ${slotFilter === s.id ? 'bg-primary text-white shadow' : 'bg-white border border-gray-200 text-gray-600 hover:border-primary/50'}`}>
                    {s.l}{s.id !== 'All' && ` (${orders.filter(o => slotBucket(o.created_at) === s.id).length})`}
                  </button>
                ))}
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {STATUS_FILTERS.map(st => (
                  <button key={st.id} onClick={() => setStatusFilter(st.id)}
                    className={`shrink-0 rounded-pill px-4 py-2 text-xs font-bold transition-all ${statusFilter === st.id ? 'bg-gray-800 text-white shadow' : 'bg-white border border-gray-200 text-gray-600 hover:border-gray-400'}`}>
                    {st.l}
                  </button>
                ))}
              </div>
            </div>

            {/* Cook Summary — aggregated item totals for everything still to prepare */}
            {itemSummary.length > 0 && (
              <section className="mb-6">
                <div className="overflow-hidden rounded-card bg-gradient-to-br from-emerald-800 to-emerald-950 text-white shadow-lg">
                  <div className="flex items-center justify-between px-4 pb-3 pt-4">
                    <div>
                      <h2 className="flex items-center gap-1.5 text-base font-black"><svg className="h-5 w-5 text-gold" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 11h18M5 11V7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4M3 11v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6M7 15h4" /></svg>Cook Summary</h2>
                      <p className="text-[11px] text-primary/60">Everything to prepare across {liveOrders.length} live order{liveOrders.length === 1 ? '' : 's'} · {todayOnly ? 'today' : 'all-time'}</p>
                    </div>
                    <span className="rounded-pill bg-white/15 px-3 py-1 text-xs font-bold">{itemSummary.length} item{itemSummary.length === 1 ? '' : 's'}</span>
                  </div>
                  <div className="space-y-1.5 px-4 pb-4">
                    {itemSummary.map(it => (
                      <div key={it.name} className="flex items-center justify-between rounded-btn bg-white/10 px-3 py-2">
                        <span className="text-sm font-semibold">{it.name}</span>
                        <span className="rounded-sm bg-gold px-2.5 py-0.5 text-sm font-black text-emerald-950">{it.qty}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {/* Pending Orders */}
            {pendingOrders.length > 0 && (
              <section className="mb-6">
                <h2 className="text-lg font-bold text-gold-dark mb-3">Pending ({pendingOrders.length})</h2>
                <div className="space-y-3">
                  {pendingOrders.map(o => (
                    <div key={o.id} className="rounded-btn bg-white p-4 shadow-sm border border-gold-light/60">
                      <div className="flex justify-between items-start mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xl font-bold text-primary-dark">#{o.token}</span>
                          <span className={`rounded-pill px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${o.payment_method === 'COD' ? 'bg-gold-light text-gold-dark' : 'bg-blue-100 text-blue-700'}`}>
                            {o.payment_method === 'COD' ? 'Cash on Delivery' : 'UPI'}
                          </span>
                        </div>
                        <span className="text-xs bg-gold-light text-gold-dark px-2 py-0.5 rounded-pill">{o.delivery_slot}</span>
                      </div>
                      <p className="text-sm text-gray-600">{o.items}</p>
                      <p className="text-xs text-gray-400 mt-1">🕒 {fmtTime(o.created_at) || '—'} · 👤 {o.student_name} · 📞 {o.student_phone || 'no phone'} · 📍 {o.delivery_location} · ₹{o.total}</p>
                      <div className="mt-2"><CallBtn phone={o.student_phone} name={o.student_name} /></div>
                      {o.payment_method === 'COD' ? (
                        <div className="mt-3 rounded-sm border border-gold-light/60 bg-amber-50 p-3">
                          <p className="text-xs font-semibold text-gold-dark">Cash on Delivery — collect ₹{o.total} when delivering</p>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <button onClick={() => updateOrderStatus(o.id, 'Accepted')} className="rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white hover:bg-primary">Accept Order</button>
                            <button onClick={() => updateOrderStatus(o.id, 'Cancelled')} className="rounded-sm border border-red-200 px-3 py-2 text-sm font-bold text-red-600">Reject</button>
                          </div>
                          <p className="mt-2 text-[11px] text-gold-dark">After accepting, mark <b>Cash Collected ✓</b> once the student pays.</p>
                        </div>
                      ) : o.status === 'Pending Payment' ? (
                        <div className="mt-3 rounded-sm border border-blue-200 bg-blue-50 p-3">
                          <p className="text-xs font-semibold text-blue-700">Awaiting UPI payment (₹{o.total}) — confirm once it arrives in your UPI app</p>
                          {o.payment?.screenshot_name && (
                            <div className="mt-2 rounded-sm bg-white border border-blue-200 p-2">
                              <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-blue-600">Payment screenshot</p>
                              {o.payment.utr_number && <p className="text-[11px] text-gray-600">UTR: <b>{o.payment.utr_number}</b></p>}
                              <a href={`/uploads/payments/${o.payment.screenshot_name}`} target="_blank" rel="noopener noreferrer" className="mt-1 block">
                                <img src={`/uploads/payments/${o.payment.screenshot_name}`} alt="Payment screenshot" className="max-h-36 w-full rounded-sm object-contain border border-blue-100" />
                              </a>
                            </div>
                          )}
                          <button onClick={() => confirmPayment(o.id)} className="mt-2 w-full rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white hover:bg-primary">Payment Received</button>
                        </div>
                      ) : (
                        <div className="mt-3 grid grid-cols-2 gap-2">
                          <button onClick={() => updateOrderStatus(o.id, 'Accepted')} className="rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white">Accept Order</button>
                          <button onClick={() => updateOrderStatus(o.id, 'Cancelled')} className="rounded-sm border border-red-200 px-3 py-2 text-sm font-bold text-red-600">Reject</button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Active Orders — Accept → Preparing → Ready → Complete flow */}
            {acceptedOrders.length > 0 && (
              <section className="mb-6">
                <h2 className="text-lg font-bold text-primary mb-3">Active ({acceptedOrders.length})</h2>
                <div className="space-y-3">
                  {acceptedOrders.map(o => {
                    const isConfirmed = o.status === 'Confirmed'
                    const isActive = o.status === 'Accepted' || isConfirmed
                    const isPreparing = o.status === 'Preparing'
                    const isReady = o.status === 'Ready'
                    return (
                    <div key={o.id} className={`rounded-btn bg-white p-4 shadow-sm border ${isReady ? 'border-primary' : isPreparing ? 'border-yellow-300' : isConfirmed ? 'border-emerald-400' : 'border-primary-light/50'}`}>
                      <div className="flex justify-between items-start mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xl font-bold text-primary-dark">#{o.token}</span>
                          <span className={`rounded-pill px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${o.payment_method === 'COD' ? 'bg-gold-light text-gold-dark' : 'bg-blue-100 text-blue-700'}`}>
                            {o.payment_method === 'COD' ? 'Cash on Delivery' : 'UPI'}
                          </span>
                          <span className={`text-xs px-2 py-0.5 rounded-pill font-bold ${isReady ? 'bg-primary text-white' : isPreparing ? 'bg-yellow-100 text-yellow-700' : isConfirmed ? 'bg-emerald-100 text-emerald-700' : 'bg-primary-light text-primary'}`}>{o.status}</span>
                        </div>
                        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-pill">{o.delivery_slot}</span>
                      </div>
                      <p className="text-sm text-gray-600">{o.items}</p>
                      <p className="text-xs text-gray-400 mt-1">🕒 {fmtTime(o.created_at) || '—'} · 👤 {o.student_name} · 📞 {o.student_phone || 'no phone'} · 📍 {o.delivery_location}</p>
                      <div className="mt-2"><CallBtn phone={o.student_phone} name={o.student_name} /></div>
                      {/* Status flow: Accept → Preparing → Ready → Complete */}
                      <div className="mt-3 flex flex-wrap gap-2">
                        {isActive && (
                          <>
                            <button onClick={() => updateOrderStatus(o.id, 'Preparing')} className="rounded-sm bg-yellow-500 px-3 py-2 text-sm font-bold text-white hover:bg-yellow-600">Start Preparing</button>
                            <button onClick={() => updateOrderStatus(o.id, 'Cancelled')} className="rounded-sm border border-red-200 px-3 py-2 text-sm font-bold text-red-600">Reject</button>
                          </>
                        )}
                        {isPreparing && (
                          <>
                            <button onClick={() => updateOrderStatus(o.id, 'Ready')} className="rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white hover:bg-primary">Mark Ready ✓</button>
                            <button onClick={() => updateOrderStatus(o.id, 'Cancelled')} className="rounded-sm border border-red-200 px-3 py-2 text-sm font-bold text-red-600">Cancel</button>
                          </>
                        )}
                        {isReady && (
                          <>
                            {o.payment_method === 'COD' ? (
                              <button onClick={() => updateOrderStatus(o.id, 'Completed')} className="w-full rounded-sm bg-primary px-3 py-2.5 text-sm font-bold text-white hover:bg-primary transition-all active:scale-[0.98]">Cash Collected — Complete Order</button>
                            ) : (
                              <button onClick={() => updateOrderStatus(o.id, 'Completed')} className="w-full rounded-sm bg-primary px-3 py-2.5 text-sm font-bold text-white hover:bg-primary transition-all active:scale-[0.98]">Complete Order</button>
                            )}
                          </>
                        )}
                      </div>
                      {isPreparing && <p className="mt-2 text-[11px] text-yellow-600">Preparing... Mark as "Ready" once food is packed.</p>}
                      {isConfirmed && <p className="mt-2 text-[11px] text-emerald-700">Confirmed by SMS reply — start preparing this order.</p>}
                      {isReady && <p className="mt-2 text-[11px] text-primary">Ready for pickup! Mark complete once the student collects it.{o.payment_method === 'COD' ? ' Collect ₹' + o.total + ' in cash.' : ''}</p>}
                    </div>
                    )
                  })}
                </div>
              </section>
            )}

            {/* All Orders */}
            <section>
              <h2 className="text-lg font-bold text-gray-700 mb-3">All Orders ({slotOrders.length})</h2>
              <div className="space-y-2">
                {slotOrders.map(o => (
                  <div key={o.id} className="rounded-sm bg-white p-3 shadow-sm border flex items-center justify-between">
                    <div>
                      <span className="font-bold text-primary-dark">#{o.token}</span>
                      <span className="ml-2 text-xs text-gray-500">{o.student_name} · {fmtTime(o.created_at)}</span>
                      {o.delivery_slot && <span className="ml-1 text-[10px] bg-primary-light/30 text-primary px-2 py-0.5 rounded-pill">{o.delivery_slot}</span>}
                    </div>
                    <div className="flex items-center gap-1">
                      <CallBtn phone={o.student_phone} name={o.student_name} compact />
                      {o.payment_method === 'COD' && <span className="text-[10px] bg-gold-light text-gold-dark px-2 py-0.5 rounded-pill">COD</span>}
                      <span className="text-xs bg-gray-100 px-2 py-0.5 rounded-pill">{o.status}</span>
                      {o.payment_method === 'COD' && o.status === 'Accepted' && (
                        <button onClick={() => updateOrderStatus(o.id, 'Completed')} title="Cash received — mark completed" className="flex h-6 w-6 items-center justify-center rounded-pill bg-primary text-xs font-black text-white hover:bg-primary transition-all active:scale-90">✓</button>
                      )}
                    </div>
                  </div>
                ))}
                {slotOrders.length === 0 && <p className="text-sm text-gray-400 text-center">No orders yet</p>}
              </div>
            </section>
          </div>
        )}

        {/* Scan Tab */}
        {page === 'scan' && (
          <div><OrderScanner onDone={() => refreshAll(true)} /></div>
        )}

        {/* Products Tab */}
        {page === 'products' && (
          <div>                <h2 className="text-lg font-bold text-primary mb-4">Products ({products.length})</h2>

            {/* Add Product Form — only once the shop is approved */}
            {approvalStatus === 'Approved' && (
              <form onSubmit={addProduct} className="rounded-btn bg-white p-4 shadow-sm border mb-4">
                <h3 className="font-bold text-sm mb-3">Add New Product</h3>
                <div className="space-y-2">
                  <input type="text" value={productForm.name} onChange={e => setProductForm({...productForm, name: e.target.value})} className="w-full rounded-sm border px-3 py-2 text-sm outline-none" placeholder="Product name" required />
                  <div className="grid grid-cols-2 gap-2">
                    <input type="number" value={productForm.price} onChange={e => setProductForm({...productForm, price: e.target.value})} className="w-full rounded-sm border px-3 py-2 text-sm outline-none" placeholder="Price ₹" required />
                    <select value={productForm.category} onChange={e => setProductForm({...productForm, category: e.target.value})} className="w-full rounded-sm border px-3 py-2 text-sm outline-none">
                      <option value="Food">Food</option><option value="Beverages">Beverages</option><option value="Starters">Starters</option><option value="Desserts">Desserts</option>
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="mb-1 block text-xs font-bold text-gray-500">Stock (per batch)</label>
                      <input type="number" value={productForm.inventory} onChange={e => setProductForm({...productForm, inventory: e.target.value})} className="w-full rounded-sm border px-3 py-2 text-sm outline-none" placeholder="Default stock" min="0" />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-bold text-gray-500">Prep Time (min)</label>
                      <input type="number" value={productForm.prep_time} onChange={e => setProductForm({...productForm, prep_time: e.target.value})} className="w-full rounded-sm border px-3 py-2 text-sm outline-none" placeholder="Minutes" min="1" />
                    </div>
                  </div>
                  <input type="text" value={productForm.description} onChange={e => setProductForm({...productForm, description: e.target.value})} className="w-full rounded-sm border px-3 py-2 text-sm outline-none" placeholder="Description" />
                  <button type="submit" className="w-full rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white">Add Product +</button>
                </div>
              </form>
            )}
            {approvalStatus !== 'Approved' && approvalStatus !== 'loading' && (
              <div className="mb-4 rounded-btn border border-gold-light/60 bg-amber-50 px-4 py-3 text-sm text-gold-dark">
                {approvalStatus === 'Pending Approval'
                  ? <>⏳ Your shop is <b>pending admin approval</b> — you'll be able to add products once it's approved.</>
                  : approvalStatus === 'Rejected'
                    ? <>Your shop was <b>rejected</b> — contact the admin to resolve this before adding products.</>
                    : 'You can add products once your shop is approved by the admin.'}
              </div>
            )}

            {/* Product List */}
            <div className="space-y-2">
              {products.map(p => (
                <div key={p.id} className="rounded-btn bg-white p-4 shadow-sm border flex items-center justify-between">
                  <div>
                    <h3 className="font-bold text-primary-dark">{p.name}</h3>
                    <p className="text-xs text-gray-500">₹{p.price} · {p.category}{p.inventory > 0 ? ` · Stock: ${p.inventory}` : ''}</p>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => updateProductAvailable(p.id, !p.available)} className={`rounded-sm px-2 py-1 text-xs font-bold ${p.available ? 'bg-gray-100 text-gray-500' : 'bg-primary-light text-primary'}`}>{p.available ? 'Hide' : 'Show'}</button>
                    <button onClick={() => deleteProduct(p.id)} className="rounded-sm bg-red-100 px-2 py-1 text-xs font-bold text-red-600">Del</button>
                  </div>
                </div>
              ))}
              {products.length === 0 && <p className="text-sm text-gray-400 text-center">No products. Add your first product!</p>}
            </div>
          </div>
        )}

        {/* History Tab */}
        {page === 'history' && (
          <div>
            <h2 className="text-lg font-bold text-primary mb-3">Orders & Earnings</h2>
            <p className="text-xs text-gray-500 mb-4">Every day starts fresh — see what you earned on any day. Select a range below.</p>

            {/* Range filter chips */}
            <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
              {[{ id: 'today', l: 'Today' }, { id: 'yesterday', l: 'Yesterday' }, { id: 'week', l: 'Last 7 Days' }, { id: 'all', l: 'All Time' }].map(r => (
                <button key={r.id} onClick={() => selectHistoryRange(r.id)}
                  className={`shrink-0 rounded-pill px-4 py-2 text-xs font-bold transition-all ${historyRange === r.id ? 'bg-primary text-white' : 'bg-white border text-gray-600'}`}>
                  {r.l}
                </button>
              ))}
            </div>

            {/* Range summary */}
            <div className="mb-4 grid grid-cols-2 gap-2">
              <div className="rounded-btn bg-white p-3 shadow-sm border">
                <p className="text-xs text-gray-500">Orders</p>
                <p className="text-xl font-bold text-primary-dark">{history.count || 0}</p>
              </div>
              <div className="rounded-btn bg-white p-3 shadow-sm border">
                <p className="text-xs text-gray-500">Amount Received</p>
                <p className="text-xl font-bold text-primary-dark">₹{history.revenue || 0}</p>
              </div>
            </div>

            {/* Per-day breakdown */}
            {history.daily && history.daily.length > 0 && (
              <div className="mb-4 rounded-btn bg-white p-4 shadow-sm border">
                <h3 className="text-sm font-bold text-gray-700 mb-2">Day-by-day</h3>
                <div className="space-y-2">
                  {history.daily.map((d: any) => (
                    <div key={d.date} className="flex items-center justify-between rounded-sm bg-gray-50 px-3 py-2">
                      <span className="text-sm font-semibold text-gray-700">{d.date}</span>
                      <span className="text-xs text-gray-500">{d.count} orders</span>
                      <span className="text-sm font-bold text-primary">₹{d.revenue}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Orders in range */}
            <h3 className="text-sm font-bold text-gray-700 mb-2">Orders ({history.orders?.length || 0})</h3>
            <div className="space-y-2">
              {history.orders?.map((o: any) => (
                <div key={o.id} className="rounded-btn bg-white p-3 shadow-sm border">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-primary-dark">#{o.token}</span>
                    <span className="text-xs text-gray-500">{fmtTime(o.created_at) || o._day || String(o.created_at || '').slice(0, 10)}</span>
                  </div>
                  <p className="mt-1 text-sm text-gray-600">{o.items}</p>
                  <div className="mt-1 flex items-center justify-between">
                    <span className="text-xs text-gray-400">{o.student_name} · 📞 {o.student_phone || '—'}</span>
                    <span className="flex items-center gap-1.5">
                      {o.payment_method === 'COD' && <span className="text-[10px] bg-gold-light text-gold-dark px-2 py-0.5 rounded-pill">COD</span>}
                      <span className="font-bold text-primary">₹{o.total}</span>
                      <span className="text-[10px] bg-gray-100 px-2 py-0.5 rounded-pill">{o.status}</span>
                      <CallBtn phone={o.student_phone} name={o.student_name} compact />
                    </span>
                  </div>
                </div>
              ))}
              {(!history.orders || history.orders.length === 0) && <p className="py-6 text-center text-sm text-gray-400">No orders in this range</p>}
            </div>
          </div>
        )}

        {/* Settings Tab */}
        {page === 'settings' && (
          <div>
            <h2 className="text-lg font-bold text-primary mb-4">Shop Settings</h2>
            {approvalStatus === 'Approved' && (
              <div className="rounded-btn bg-amber-50 border border-gold-light/60 p-4 mb-4">
                <p className="text-sm font-bold text-gold-dark">Admin Share (5% of this month's earnings)</p>
                <p className="mt-1 text-xs text-gold-dark">The admin takes 5% of what you earn in a month through this app — it's never added to the student's bill. This month: you earned <strong>₹{stats.month_revenue ?? stats.today_revenue ?? 0}</strong>, so your share is <strong>₹{stats.platform_fee_due ?? 0}</strong>. Pay it from the dashboard card with the <b>Pay</b> button.</p>
              </div>
            )}
            {/* Payment methods — the shopkeeper controls which ways students can pay */}
            <div className="rounded-btn bg-white p-4 shadow-sm border">
              <h3 className="mb-1 flex items-center gap-1.5 text-sm font-bold text-gray-700"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M2 10h20" /></svg>Payment Methods</h3>
              <p className="mb-4 text-xs text-gray-500">Choose how students pay you. Having bank issues? Turn UPI off — only Cash on Delivery will show at checkout. Both stay on by default.</p>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3 rounded-btn border border-gray-200 bg-gray-50 p-3">
                  <div>
                    <p className="text-sm font-semibold text-gray-800">UPI / QR Payments</p>
                    <p className="text-[11px] text-gray-500">Students scan your QR with GPay / PhonePe / Paytm{upiId.trim() ? '' : ' — add your UPI ID below first'}</p>
                  </div>
                  <button onClick={() => togglePayment('upi_enabled', !upiEnabled)} role="switch" aria-checked={upiEnabled}
                    className={`relative h-7 w-12 shrink-0 rounded-pill transition-colors ${upiEnabled ? 'bg-primary' : 'bg-gray-300'}`}>
                    <span className={`absolute top-0.5 h-6 w-6 rounded-pill bg-white shadow transition-all ${upiEnabled ? 'left-[22px]' : 'left-0.5'}`} />
                  </button>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-btn border border-gray-200 bg-gray-50 p-3">
                  <div>
                    <p className="text-sm font-semibold text-gray-800">Cash on Delivery</p>
                    <p className="text-[11px] text-gray-500">Students pay in cash when the order arrives</p>
                  </div>
                  <button onClick={() => togglePayment('cod_enabled', !codEnabled)} role="switch" aria-checked={codEnabled}
                    className={`relative h-7 w-12 shrink-0 rounded-pill transition-colors ${codEnabled ? 'bg-primary' : 'bg-gray-300'}`}>
                    <span className={`absolute top-0.5 h-6 w-6 rounded-pill bg-white shadow transition-all ${codEnabled ? 'left-[22px]' : 'left-0.5'}`} />
                  </button>
                </div>
              </div>
            </div>

            <div className="rounded-btn bg-white p-4 shadow-sm border space-y-4">
              {/* Order notifications */}
              <div>
                <div className="flex items-center justify-between">
                  <p className="flex items-center gap-1.5 text-sm font-semibold text-gray-700"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" /><path d="M10 20a2.2 2.2 0 0 0 4 0" /></svg>Order Notifications</p>
                  <span className={`rounded-pill px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${pushState === 'subscribed' ? 'bg-primary-light text-primary' : 'bg-gray-100 text-gray-500'}`}>
                    {pushState === 'subscribed' ? 'On' : 'Off'}
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {pushState === 'subscribed'
                    ? "On — you'll get an alert on your phone the moment a student places an order, even when the app is closed."
                    : pushState === 'checking'
                      ? 'Checking notification status…'
                      : pushState === 'disabled'
                        ? pushReason || 'Push alerts are not configured on the server yet (VAPID keys missing).'
                        : pushState === 'unsupported'
                          ? pushError || "This browser doesn't support push notifications. Use Chrome on Android, or install the app from the portal."
                          : pushState === 'denied'
                            ? 'Notifications are blocked by your browser. Allow them in site settings, then try again.'
                            : pushState === 'error'
                              ? pushError || 'Something went wrong — tap Enable to try again.'
                              : 'Get a phone notification the moment an order comes in — even when the app is closed.'}
                </p>
                {pushError && (
                  <p className="mt-2 rounded-sm border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-600">{pushError}</p>
                )}
                {pushState === 'subscribed' ? (
                  <div className="mt-3 space-y-2">
                    <button onClick={sendTestPush} disabled={sendingTest} className="w-full rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white transition-colors hover:bg-primary disabled:opacity-50">
                      {sendingTest ? 'Sending…' : '📲 Send Test Notification'}
                    </button>
                    <button onClick={disablePush} className="w-full rounded-sm border border-red-200 px-3 py-2 text-sm font-bold text-red-600 transition-colors hover:bg-red-50">Turn Off Notifications</button>
                  </div>
                ) : pushState === 'unsubscribed' || pushState === 'error' || pushState === 'checking' ? (
                  <button onClick={enablePush} className="mt-3 w-full rounded-sm bg-primary px-3 py-2 text-sm font-bold text-white transition-colors hover:bg-primary">Enable Order Notifications</button>
                ) : null}
              </div>

              <div className="border-t pt-4"><p className="text-sm font-semibold text-gray-700">Shop Name</p><p className="text-gray-600">{shop?.name || '—'}</p></div>
              <div><p className="text-sm font-semibold text-gray-700">Category</p><p className="text-gray-600">{shop?.category || '—'}</p></div>
              <div><p className="text-sm font-semibold text-gray-700">Hours</p><p className="text-gray-600">{shop?.opening_time} - {shop?.closing_time}</p></div>
              <div><p className="text-sm font-semibold text-gray-700">Phone</p><p className="text-gray-600">{shop?.phone || '—'}</p></div>
              <div>
                <p className="text-sm font-semibold text-gray-700">UPI ID (students pay this)</p>
                <div className="mt-1 flex gap-2">
                  <input value={upiId} onChange={e => setUpiId(e.target.value)} placeholder="yourname@okhdfcbank" className="flex-1 rounded-sm border px-3 py-2 text-sm outline-none focus:border-primary-light/200" />
                  <button onClick={(e) => { e.preventDefault(); saveUpi() }} className="shrink-0 rounded-sm bg-primary px-4 py-2 text-sm font-bold text-white hover:bg-primary transition-colors">Save</button>
                </div>
                {upiEnabled && upiQrUri ? (
                  <div className="mt-3 flex w-full flex-col items-center rounded-btn border-2 border-dashed border-primary/50 bg-primary-light/30 p-4">
                    <div className="flex w-full justify-center">
                      <QRCodeSVG value={upiQrUri} size={160} level="M" bgColor="#ffffff" fgColor="#064E3B" className="h-auto w-full max-w-[180px]" />
                    </div>
                    <p className="mt-2 text-center text-xs font-bold text-primary">📱 Students scan this to pay your shop</p>
                    <p className="mt-0.5 font-mono text-xs text-gray-500">{upiId.trim()}</p>
                    <p className="mt-1 text-center text-[11px] text-gray-400">Add your shop name as the payee and share this QR on your counter.</p>
                  </div>
                ) : upiEnabled ? (
                  <p className="mt-2 text-xs text-gray-400">Add your UPI ID to let students pay you digitally — they can also scan the QR shown here. Cash on Delivery stays available either way.</p>
                ) : (
                  <p className="mt-2 text-xs font-medium text-gold-dark">UPI payments are turned off — students will only see Cash on Delivery at checkout. Turn UPI on above to show your QR again.</p>
                )}
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-700">Approval Status</p>
                <span className={`inline-block mt-1 rounded-sm px-3 py-1 text-sm font-bold ${approvalStatus === 'Approved' ? 'bg-primary-light text-primary' : approvalStatus === 'Rejected' ? 'bg-red-100 text-red-700' : 'bg-gold-light text-gold-dark'}`}>
                  {approvalStatus === 'loading' ? 'Checking...' : approvalStatus}
                </span>
              </div>
              <button onClick={() => navigate('/')} className="w-full rounded-sm bg-gray-100 px-3 py-2 text-sm font-bold text-gray-600">Back to Portal</button>
            </div>
          </div>
        )}
          </>
        )}
      </div>

      {/* Bottom Tab Bar */}
      <nav className="fixed bottom-0 left-0 right-0 max-w-md mx-auto bg-white border-t flex z-10">
        {[
          { id: 'dashboard', label: 'Orders', icon: <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg> },
          { id: 'scan', label: 'Scan', icon: <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M7 12h10" /></svg> },
          { id: 'history', label: 'History', icon: <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg> },
          { id: 'products', label: 'Products', icon: <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" /><path d="M3 8l9 5 9-5M12 13v8" /></svg> },
          { id: 'settings', label: 'Settings', icon: <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1Z" /></svg> },
        ].map(tab => (
          <button key={tab.id} onClick={() => { setPage(tab.id); setMsg(''); setErr(''); if (tab.id === 'history') loadHistory(historyRange) }}
            className={`flex-1 py-2.5 text-center text-xs font-semibold transition-all ${page === tab.id ? 'text-primary border-t-2 border-emerald-800 bg-primary-light/30' : 'text-gray-400'}`}>
            <span className="mx-auto mb-0.5 flex h-5 w-5 items-center justify-center">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Admin Share UPI QR modal — the vendor scans the admin's QR to pay
          the 5% share (or uses the one-tap UPI app button). */}
      {showDuesQr && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setShowDuesQr(false)}>
          <div className="w-full max-w-sm rounded-card bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-primary-dark">Pay Admin Share</h3>
            <p className="mt-1 text-xs text-gray-500">Scan this QR with your UPI app (GPay / PhonePe / Paytm) to pay <b>₹{duesAmount}</b> to the admin.</p>
            <div className="mt-4 flex justify-center rounded-card border-2 border-dashed border-primary/50 bg-primary-light/30 p-4">
              {duesQrUri && <QRCodeSVG value={duesQrUri} size={180} level="M" bgColor="#ffffff" fgColor="#064E3B" />}
            </div>
            <p className="mt-3 text-center font-mono text-xs text-gray-600">{adminUpi}</p>
            <p className="text-center text-xs text-gray-400">Receiver: {adminReceiver}</p>
            <div className="mt-5 grid grid-cols-2 gap-2">
              <button onClick={() => window.open(duesQrUri, '_blank')} className="rounded-btn bg-primary px-4 py-2.5 text-sm font-bold text-white transition-colors hover:bg-primary">Open UPI App</button>
              <button onClick={() => void recordDuesPaid()} disabled={payingDues} className="rounded-btn bg-amber-600 px-4 py-2.5 text-sm font-bold text-white transition-colors hover:bg-gold disabled:opacity-40">{payingDues ? 'Recording…' : "I've Paid ✓"}</button>
            </div>
            <button onClick={() => setShowDuesQr(false)} className="mt-2 w-full rounded-btn border px-4 py-2 text-sm font-bold text-gray-500 transition-colors hover:bg-gray-50">Close</button>
          </div>
        </div>
      )}
    </div>
  )
}
