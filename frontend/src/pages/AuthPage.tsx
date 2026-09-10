import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { saveSessionToBackend } from '../services/localApi'
import { saveLocalSession, UserRoleChoice, getDashboardPath } from '../utils/session'
import { syncProfileToSupabase, isSupabaseConfigured } from '../services/supabase'

/* ─── Admin credentials (hardcoded for now, change in production) ─── */
const ADMIN_USERNAME = import.meta.env.VITE_ADMIN_USERNAME || 'admin'
const ADMIN_PASSWORD = import.meta.env.VITE_ADMIN_PASSWORD || 'admin123'

/* ─── Role definitions ─── */
const roles: { id: UserRoleChoice; label: string; icon: string; color: string }[] = [
  { id: 'student', label: 'Student', icon: '🎓', color: 'emerald' },
  { id: 'shopkeeper', label: 'Shopkeeper', icon: '👨‍🍳', color: 'gold' },
  { id: 'admin', label: 'Admin', icon: '⚙️', color: 'emerald' },
]

type AuthMode = 'login' | 'signup'

/* Password field with a show/hide toggle, styled to match the portal switcher. */
function AuthPasswordField({ value, onChange, placeholder, autoComplete, required = true }: { value: string; onChange: (v: string) => void; placeholder?: string; autoComplete?: string; required?: boolean }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">🔒</span>
      <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)}
        className="w-full rounded-card border border-slate-200 bg-white pl-11 pr-11 py-3 text-slate-700 placeholder-slate-400 outline-none transition-all focus:border-primary focus:shadow-[0_0_0_3px_rgba(15,118,110,0.12)]"
        placeholder={placeholder} autoComplete={autoComplete} required={required} />
      <button type="button" onClick={() => setShow(s => !s)} tabIndex={-1} aria-label={show ? 'Hide password' : 'Show password'}
        className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-primary">
        {show ? (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><path d="m1 1 22 22" /></svg>
        ) : (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>
        )}
      </button>
    </div>
  )
}

export function AuthPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<AuthMode>('login')
  const [role, setRole] = useState<UserRoleChoice>('student')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (!username.trim() || !password.trim()) {
      setError('Username and password are required')
      return
    }

    if (mode === 'signup' && !fullName.trim()) {
      setError('Full name is required')
      return
    }

    if (mode === 'signup' && password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    if (mode === 'signup' && password.length < 4) {
      setError('Password must be at least 4 characters')
      return
    }

    // ─── Helper to complete auth after login/register ───
    const finishAuth = (user: { username: string; name: string; role: string }, accessToken: string | null) => {
      if (accessToken) {
        localStorage.setItem('access_token', accessToken)
      }
      const session = {
        role: user.role as UserRoleChoice,
        email: `${user.username}@campus.local`,
        name: user.name,
      }
      saveLocalSession(session)
      // Fire-and-forget for backend session + supabase sync
      saveSessionToBackend(session)
      if (isSupabaseConfigured()) {
        syncProfileToSupabase({
          id: `${user.role}-${user.username}`,
          email: session.email,
          name: session.name,
          role: user.role,
        })
      }
      navigate(getDashboardPath(user.role as UserRoleChoice))
    }

    setLoading(true)

    try {
      // ─── Admin: use hardcoded credentials (no registration) ───
      if (role === 'admin') {
        if (mode === 'signup') {
          setError('Admin accounts cannot be created here. Contact system administrator.')
          setLoading(false)
          return
        }
        if (username.trim() !== ADMIN_USERNAME || password !== ADMIN_PASSWORD) {
          setError('Invalid admin credentials')
          setLoading(false)
          return
        }
        finishAuth({ username: ADMIN_USERNAME, name: 'Administrator', role: 'admin' }, null)
        return
      }

      // ─── Student / Shopkeeper: use backend API ───
      const cleanUsername = username.trim()
      const profileName = fullName.trim() || cleanUsername

      if (mode === 'login') {
        const response = await api.post('/local/auth/login', {
          username: cleanUsername,
          password,
        })
        const { access_token, user } = response.data
        finishAuth(user, access_token)
      } else {
        // ─── Signup: register then construct session from response ───
        const response = await api.post('/local/auth/register', {
          username: cleanUsername,
          password,
          name: profileName,
          role,
        })
        const { user } = response.data

        // Try auto-login to get a JWT token; if it fails, continue without token
        let accessToken: string | null = null
        try {
          const loginRes = await api.post('/local/auth/login', {
            username: cleanUsername,
            password,
          })
          accessToken = loginRes.data.access_token
        } catch {
          // Auto-login failed — user is registered but we proceed without JWT
        }

        finishAuth(user, accessToken)
      }
    } catch (error: any) {
      const msg =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        'An unexpected error occurred. Please try again.'
      setError(typeof msg === 'string' ? msg : 'Operation failed')
    } finally {
      setLoading(false)
    }
  }

  const switchMode = (m: AuthMode) => {
    setMode(m)
    setError('')
  }

  return (
    <div className="relative min-h-screen flex bg-[radial-gradient(circle_at_top_left,_rgba(212,160,85,0.16),_transparent_30%),linear-gradient(135deg,_#fdf8ef_0%,_#f5efe4_100%)]">
      {/* Mobile background — faded food photo (visible below lg only) */}
      <div className="absolute inset-0 overflow-hidden lg:hidden">
        <img
          src="https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1000&q=80"
          alt=""
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="h-full w-full object-cover opacity-75"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-amber-50/60 via-transparent to-amber-50/60" />
      </div>
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-700">
        <div className="absolute inset-0 opacity-[0.08]">
          {['🍕', '🍔', '🥤', '🍛', '🥗', '☕', '🧁', '🌮'].map((emoji, i) => (
            <span key={i} className="absolute text-6xl md:text-7xl lg:text-8xl"
              style={{
                top: `${10 + (i * 12) % 80}%`,
                left: `${10 + (i * 15) % 75}%`,
                transform: `rotate(${i * 25}deg)`,
              }}>{emoji}</span>
          ))}
        </div>
        <div className="absolute -top-32 -right-32 h-96 w-96 rounded-pill bg-primary/20 blur-3xl" />
        <div className="absolute -bottom-32 -left-32 h-80 w-80 rounded-pill bg-gold/10 blur-3xl" />

        <div className="relative z-10 flex flex-col justify-center px-12 xl:px-16 py-20">
          <div className="mb-8">
            <span className="mb-6 flex h-14 w-14 items-center justify-center rounded-card bg-gold-light/15 text-2xl font-black text-gold shadow-lg backdrop-blur-sm">
              D
            </span>
            <h1 className="text-4xl font-black leading-tight text-white xl:text-5xl">
              Campus Food<br />
              <span className="text-gold">Ordering</span>
            </h1>
            <p className="mt-4 max-w-md text-base leading-relaxed text-primary/50/80 xl:text-lg">
              {mode === 'login'
                ? 'Welcome back! Sign in to order from your favorite campus restaurants.'
                : 'Join the campus food community! Create your account to start ordering.'}
            </p>
          </div>

          <div className="space-y-4">
            {[
              { icon: '🛵', text: 'Fast delivery to your campus location' },
              { icon: '🔔', text: 'Real-time order tracking & notifications' },
              { icon: '💳', text: 'Secure UPI payments with verification' },
            ].map((item) => (
              <div key={item.text} className="flex items-center gap-3">
                <span className="text-xl">{item.icon}</span>
                <span className="font-medium text-primary/50/70">{item.text}</span>
              </div>
            ))}
          </div>

          <div className="mt-10 max-w-sm rounded-card border border-white/10 bg-white/10 p-5 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-btn bg-gradient-to-br from-amber-300 to-amber-500 text-xl">🍕</div>
              <div>
                <div className="text-sm font-semibold text-white/90">Pizza Palace</div>
                <div className="text-xs text-primary/50/60">Italian · ⭐ 4.5</div>
              </div>
              <div className="ml-auto rounded-pill bg-gold-light/20 px-2.5 py-1 text-xs font-bold text-gold">Open</div>
            </div>
          </div>
        </div>
      </div>

      <div className="relative flex w-full items-center justify-center bg-white/15 px-6 py-8 backdrop-blur-[2px] lg:w-1/2 lg:bg-white/60">
        <div className="w-full max-w-md rounded-[28px] border border-primary-light/30 bg-white/90 p-6 shadow-[0_20px_60px_rgba(15,118,110,0.12)]">
          <div className="mb-6 text-center lg:hidden">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-btn bg-gradient-to-br from-emerald-800 to-emerald-600 text-lg font-black text-gold shadow-lg">D</span>
            <h1 className="mt-2 text-2xl font-black text-primary-dark">DETOMSITE</h1>
          </div>

          <div className="mb-8 flex rounded-card bg-primary-light/30 p-1">
            <button onClick={() => switchMode('login')}
              className={`flex-1 rounded-btn py-2.5 text-sm font-bold transition-all ${mode === 'login' ? 'bg-white text-primary shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
              Sign In
            </button>
            <button onClick={() => switchMode('signup')}
              className={`flex-1 rounded-btn py-2.5 text-sm font-bold transition-all ${mode === 'signup' ? 'bg-white text-primary shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
              Sign Up
            </button>
          </div>

          <div className="mb-6">
            <label className="mb-2 block text-sm font-semibold text-slate-700">I want to join as</label>
            <div className="flex gap-2">
              {roles.map(opt => (
                <button key={opt.id} type="button" onClick={() => { setRole(opt.id); setError('') }}
                  className={`flex-1 rounded-card border py-3 text-center transition-all ${
                    role === opt.id
                      ? 'border-emerald-500 bg-primary-light/30 shadow-[0_8px_20px_rgba(15,118,110,0.1)]'
                      : 'border-slate-200 bg-white hover:border-emerald-300'
                  }`}>
                  <span className="block text-lg">{opt.icon}</span>
                  <span className={`mt-0.5 block text-xs font-bold ${role === opt.id ? 'text-primary' : 'text-slate-500'}`}>
                    {opt.label}
                  </span>
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {role === 'student' && 'Students access the website and can browse shops and place orders.'}
              {role === 'shopkeeper' && 'Shopkeepers can use the mobile app experience and wait for admin approval.'}
              {role === 'admin' && 'Admins use the secure admin portal with dedicated credentials.'}
            </p>
          </div>

          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-600">
              <span>⚠️</span>
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === 'signup' && role !== 'admin' && (
              <div>
                <label className="mb-1.5 block text-sm font-semibold text-slate-700">Full Name</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">👤</span>
                  <input type="text" value={fullName} onChange={e => setFullName(e.target.value)}
                    className="w-full rounded-card border border-slate-200 bg-white pl-11 pr-4 py-3 text-slate-700 placeholder-slate-400 outline-none transition-all focus:border-primary focus:shadow-[0_0_0_3px_rgba(15,118,110,0.12)]"
                    placeholder="Your full name" />
                </div>
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-slate-700">
                {role === 'admin' ? 'Admin Username' : 'Username'}
              </label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">
                  {role === 'admin' ? '🔑' : role === 'student' ? '🎓' : '👨‍🍳'}
                </span>
                <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                  className="w-full rounded-card border border-slate-200 bg-white pl-11 pr-4 py-3 text-slate-700 placeholder-slate-400 outline-none transition-all focus:border-primary focus:shadow-[0_0_0_3px_rgba(15,118,110,0.12)]"
                  placeholder={role === 'admin' ? 'Enter admin username' : 'Choose a username'}
                  autoComplete="username" required />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-slate-700">Password</label>
              <AuthPasswordField value={password} onChange={setPassword}
                placeholder={mode === 'signup' ? 'Create a password' : 'Enter your password'}
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />
            </div>

            {mode === 'signup' && (
              <div>
                <label className="mb-1.5 block text-sm font-semibold text-slate-700">Confirm Password</label>
                <AuthPasswordField value={confirmPassword} onChange={setConfirmPassword}
                  placeholder="Confirm your password" autoComplete="new-password" />
              </div>
            )}

            {role === 'admin' && mode === 'login' && (
              <div className="rounded-card border border-primary-light/50 bg-primary-light/30 px-4 py-2.5">
                <p className="text-xs font-medium text-primary">
                  🔑 Default admin: <strong>{ADMIN_USERNAME}</strong> / <strong>{ADMIN_PASSWORD}</strong>
                </p>
              </div>
            )}
            {role === 'shopkeeper' && mode === 'signup' && (
              <div className="rounded-card border border-gold-light/60 bg-amber-50 px-4 py-2.5">
                <p className="text-xs font-medium text-gold-dark">
                  ⏳ After signup, your shop will be <strong>Pending Approval</strong>. An admin must approve it before students can order.
                </p>
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full rounded-card bg-gradient-to-r from-emerald-800 to-emerald-700 px-6 py-3.5 text-base font-bold text-white shadow-lg shadow-emerald-900/20 transition-all hover:from-emerald-900 hover:to-emerald-800 disabled:opacity-40 disabled:cursor-not-allowed">
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-pill border-2 border-white/30 border-t-white" />
                  {mode === 'login' ? 'Signing in...' : 'Creating account...'}
                </span>
              ) : mode === 'login' ? 'Sign In' : 'Create Account'}
            </button>
          </form>

          <div className="mt-6 text-center">
            {mode === 'login' ? (
              <p className="text-sm text-slate-500">
                Don't have an account?{' '}
                <button type="button" onClick={() => switchMode('signup')} className="font-bold text-primary hover:text-primary">
                  Sign Up
                </button>
              </p>
            ) : (
              <p className="text-sm text-slate-500">
                Already have an account?{' '}
                <button type="button" onClick={() => switchMode('login')} className="font-bold text-primary hover:text-primary">
                  Sign In
                </button>
              </p>
            )}
            <Link to="/" className="mt-3 inline-block text-sm font-medium text-slate-400 transition-colors hover:text-primary">
              ← Back to home
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
