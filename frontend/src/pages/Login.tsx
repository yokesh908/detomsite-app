import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { saveSessionToBackend } from '../services/localApi'
import { getLocalSession, saveLocalSession, getDashboardPath, UserRoleChoice } from '../utils/session'

const roles: { id: UserRoleChoice; label: string; icon: string }[] = [
  { id: 'student', label: 'Student', icon: '🎓' },
  { id: 'shopkeeper', label: 'Shopkeeper', icon: '👨‍🍳' },
  { id: 'admin', label: 'Admin', icon: '⚙️' },
]

export function Login() {
  const saved = getLocalSession()
  const navigate = useNavigate()
  const [email, setEmail] = useState(saved?.email || '')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRoleChoice>(saved?.role || 'student')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!email.trim()) { setError('Please enter your email'); return }
    if (!password.trim()) { setError('Please enter your password'); return }
    setLoading(true)
    try {
      const endpoint = role === 'admin' ? '/admin/login'
        : role === 'shopkeeper' ? '/vendor/login'
        : '/users/login'
      const body = role === 'admin'
        ? { username: email.trim(), password }
        : role === 'shopkeeper' ? { username: email.trim(), password }
        : { email: email.trim(), password }
      const response = await api.post(endpoint, body)
      const data = response.data
      const session = {
        role,
        email: email.trim(),
        name: data.name || data.user?.name || email.split('@')[0],
      }
      saveLocalSession(session)
      if (data.access_token) localStorage.setItem('access_token', data.access_token)
      void saveSessionToBackend(session)
      navigate(getDashboardPath(role))
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.response?.data?.message || 'Login failed. Please check your credentials.'
      setError(typeof msg === 'string' ? msg : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left Side - Illustration / Branding */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-emerald-900 via-emerald-800 to-emerald-950">
        {/* Decorative elements */}
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-20 left-10 text-8xl">🍕</div>
          <div className="absolute top-40 right-20 text-6xl">🍔</div>
          <div className="absolute bottom-32 left-24 text-7xl">🥤</div>
          <div className="absolute bottom-48 right-16 text-5xl">🍛</div>
          <div className="absolute top-1/3 left-1/3 text-4xl">🥗</div>
          <div className="absolute top-2/3 right-1/4 text-4xl">☕</div>
          <div className="absolute top-1/4 right-1/3 text-3xl">🧁</div>
          <div className="absolute bottom-1/4 left-1/2 text-3xl">🌮</div>
        </div>
        
        {/* Gradient orbs */}
        <div className="absolute -top-32 -right-32 w-96 h-96 rounded-pill bg-primary/30 blur-3xl" />
        <div className="absolute -bottom-32 -left-32 w-80 h-80 rounded-pill bg-gold-500/10 blur-3xl" />
        
        {/* Content */}
        <div className="relative z-10 flex flex-col justify-center px-16 py-20">
          <div className="mb-8">
            <span className="flex h-14 w-14 items-center justify-center rounded-card bg-gold-400/20 backdrop-blur-sm text-2xl font-black text-gold-300 shadow-lg mb-6">
              D
            </span>
            <h1 className="text-5xl font-black text-white leading-tight">
              Campus Food<br />
              <span className="text-gold-300">Ordering</span>
            </h1>
            <p className="mt-4 text-lg text-primary/50/80 leading-relaxed max-w-md">
              Order from your favorite campus restaurants. Track in real-time. Enjoy the convenience.
            </p>
          </div>

          {/* Feature list */}
          <div className="space-y-4">
            {[
              { icon: '🛵', text: 'Fast delivery to your campus location' },
              { icon: '🔔', text: 'Real-time order tracking & notifications' },
              { icon: '💳', text: 'Secure UPI payments with verification' },
            ].map((item, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="text-xl">{item.icon}</span>
                <span className="text-primary/50/80 font-medium">{item.text}</span>
              </div>
            ))}
          </div>

          {/* Floating card preview */}
          <div className="mt-12 rounded-btn bg-white/10 backdrop-blur-sm border border-white/10 p-5 max-w-sm">
            <div className="flex items-center gap-3">
              <div className="h-12 w-12 rounded-lg bg-gradient-to-br from-gold-400 to-gold-600 flex items-center justify-center text-xl">🍕</div>
              <div className="flex-1">
                <div className="h-3 w-32 rounded-pill bg-white/20" />
                <div className="mt-2 h-2 w-24 rounded-pill bg-white/10" />
              </div>
              <div className="h-8 w-16 rounded-lg bg-gold-500/30 text-center text-xs font-bold text-gold-300 flex items-center justify-center">4.5 ⭐</div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Side - Login Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center px-6 py-12 bg-white">
        <div className="w-full max-w-md">
          {/* Mobile Logo */}
          <div className="mb-8 text-center lg:hidden">
            <Link to="/" className="inline-flex items-center gap-2">
              <span className="flex h-10 w-10 items-center justify-center rounded-btn bg-primary-dark text-lg font-black text-gold-300 shadow-gold-sm">D</span>
              <span className="text-2xl font-black text-primary-dark">DETOMSITE</span>
            </Link>
          </div>

          {/* Form card */}
          <div className="lg:px-4">
            <div className="mb-8">
              <h1 className="text-3xl font-bold text-primary-dark">Welcome back</h1>
              <p className="mt-2 text-gray-500">Sign in to continue ordering</p>
            </div>

            {error && (
              <div className="mb-5 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600 flex items-center gap-2">
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleLogin} className="space-y-5">
              {/* Role selector - compact */}
              <div>
                <label className="mb-2 block text-sm font-semibold text-gray-700">I am a</label>
                <div className="flex gap-2">
                  {roles.map(option => (
                    <button key={option.id} type="button" onClick={() => setRole(option.id)}
                      className={`flex-1 rounded-btn border-2 py-3 text-center transition-all ${
                        role === option.id
                          ? 'border-emerald-500 bg-primary-light/30 shadow-emerald-sm'
                          : 'border-gray-200 bg-white hover:border-emerald-300'
                      }`}>
                      <span className="block text-lg">{option.icon}</span>
                      <span className={`text-xs font-bold mt-0.5 block ${role === option.id ? 'text-primary' : 'text-gray-500'}`}>
                        {option.label}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Email */}
              <div>
                <label className="mb-1.5 block text-sm font-semibold text-gray-700">Email</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 text-lg">📧</span>
                  <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                    className="w-full rounded-btn border-2 border-gray-200 bg-white pl-11 pr-4 py-3 text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm"
                    placeholder="you@campus.com" required />
                </div>
              </div>

              {/* Password */}
              <div>
                <label className="mb-1.5 block text-sm font-semibold text-gray-700">Password</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 text-lg">🔒</span>
                  <input type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)}
                    className="w-full rounded-btn border-2 border-gray-200 bg-white pl-11 pr-11 py-3 text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm"
                    placeholder="Enter your password" required />
                  <button type="button" onClick={() => setShowPassword(s => !s)} tabIndex={-1} aria-label={showPassword ? 'Hide password' : 'Show password'}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-primary">
                    {showPassword ? (
                      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><path d="m1 1 22 22" /></svg>
                    ) : (
                      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>
                    )}
                  </button>
                </div>
              </div>

              {/* Submit */}
              <button type="submit" disabled={loading}
                className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-lg shadow-emerald-900/20 transition-all hover:bg-primary-dark hover:shadow-xl hover:shadow-emerald-900/30 disabled:opacity-40 disabled:cursor-not-allowed">
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-pill animate-spin" />
                    Signing in...
                  </span>
                ) : 'Sign In'}
              </button>
            </form>

            {/* Divider */}
            <div className="my-7 flex items-center gap-3">
              <div className="flex-1 border-t border-gray-100" />
              <span className="text-sm text-gray-400 font-medium">or</span>
              <div className="flex-1 border-t border-gray-100" />
            </div>

            {/* Sign Up options */}
            <div className="space-y-3">
              <p className="text-center text-sm text-gray-500 font-medium">Don't have an account?</p>
              <div className="grid grid-cols-2 gap-3">
                <Link to="/register/student"
                  className="flex items-center justify-center gap-2 rounded-btn border-2 border-primary-light/50 bg-primary-light/30/50 px-4 py-3 text-sm font-bold text-primary transition-all hover:bg-primary-light/30 hover:border-emerald-300 hover:shadow-emerald-sm">
                  🎓 Student Sign Up
                </Link>
                <Link to="/register/shopkeeper"
                  className="flex items-center justify-center gap-2 rounded-btn border-2 border-gold-200 bg-gold-50/50 px-4 py-3 text-sm font-bold text-gold-700 transition-all hover:bg-gold-50 hover:border-gold-300 hover:shadow-gold-sm">
                  👨‍🍳 Shop Sign Up
                </Link>
              </div>
            </div>

            {/* Back to home */}
            <div className="mt-6 text-center">
              <Link to="/" className="text-sm font-medium text-gray-400 hover:text-primary transition-colors">
                ← Back to home
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
