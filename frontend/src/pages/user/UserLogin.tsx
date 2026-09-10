import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../../services/api'
import { saveLocalSession } from '../../utils/session'
import { syncProfileToSupabase } from '../../services/supabase'
import { PasswordInput } from '../../components/PasswordInput'

export function UserLogin() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const justRegistered = searchParams.get('registered') === 'true'

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('Username and password are required')
      return
    }
    setLoading(true)
    try {
      const res = await api.post('/users/login', {
        username: username.trim(),
        password,
      })
      const { access_token, user } = res.data
      localStorage.setItem('access_token', access_token)
      saveLocalSession({
        role: 'student',
        email: user.email || `${user.username}@campus.local`,
        name: user.name,
      })

      // Sync student profile to Supabase
      try {
        await syncProfileToSupabase({
          id: String(user.id),
          email: user.email || '',
          name: user.name,
          role: 'student',
        })
      } catch {
        // Supabase sync failure is non-blocking
      }

      navigate('/customer-dashboard')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-white to-emerald-50 flex items-center justify-center px-4 py-12">
      {/* Faded food photo background */}
      <div className="absolute inset-0 overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=1000&q=80"
          alt=""
          loading="lazy"
          onError={e => { e.currentTarget.style.display = 'none' }}
          className="h-full w-full object-cover opacity-60"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-white/70 via-white/35 to-emerald-50/70" />
      </div>
      <div className="relative w-full max-w-md">
        <div className="mb-8 text-center">
          <Link to="/" className="inline-flex items-center gap-2">
            <span className="flex h-10 w-10 items-center justify-center rounded-btn bg-primary-dark text-lg font-black text-gold">D</span>
            <span className="text-2xl font-black text-primary-dark">DETOMSITE</span>
          </Link>
        </div>

        <div className="rounded-card bg-white p-8 shadow-[0_20px_60px_rgba(15,118,110,0.12)] border border-primary-light/30">
          <div className="mb-6 text-center">
            <span className="text-4xl">🎓</span>
            <h1 className="mt-2 text-2xl font-bold text-primary-dark">Student Login</h1>
            <p className="mt-1 text-sm font-medium text-gray-500">Sign in to browse and order</p>
          </div>

          {justRegistered && (
            <div className="mb-4 rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3 text-sm font-semibold text-primary">
              ✅ Account created! Please sign in.
            </div>
          )}

          {error && (
            <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600 flex items-center gap-2">
              <span>⚠️</span>{error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Username</label>
              <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm"
                placeholder="Your username" required autoFocus />
            </div>
            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Password</label>
              <PasswordInput value={password} onChange={setPassword} autoComplete="current-password" placeholder="••••••" required />
            </div>
            <button type="submit" disabled={loading}
              className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-lg shadow-emerald-900/20 transition-all hover:bg-primary-dark disabled:opacity-40">
              {loading ? 'Signing in...' : 'Sign In →'}
            </button>
          </form>

          <div className="mt-6 text-center space-y-2">
            <p className="text-sm text-gray-400">
              Don't have an account?{' '}
              <Link to="/user/register" className="font-bold text-primary hover:text-primary">Register</Link>
            </p>
            <Link to="/" className="block text-xs font-medium text-gray-400 hover:text-primary">← Back to portals</Link>
          </div>
        </div>
      </div>
    </div>
  )
}
