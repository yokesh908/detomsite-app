import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../../services/api'
import { saveLocalSession } from '../../utils/session'
import { syncProfileToSupabase } from '../../services/supabase'

/* Password field with a show/hide toggle, styled for the dark glassy card. */
function PasswordInputGlass({ value, onChange, placeholder = '••••••' }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)}
        className="w-full rounded-btn border border-white/10 bg-white/10 px-4 py-3 pr-11 text-sm text-white placeholder-emerald-100/40 outline-none transition-all focus:border-amber-300/50 focus:bg-white/15"
        placeholder={placeholder} autoComplete="current-password" required />
      <button type="button" onClick={() => setShow(s => !s)} tabIndex={-1} aria-label={show ? 'Hide password' : 'Show password'}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-primary/50/50 transition-colors hover:bg-white/10 hover:text-gold">
        {show ? (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><path d="m1 1 22 22" /></svg>
        ) : (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>
        )}
      </button>
    </div>
  )
}

export function AdminLogin() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('Username and password are required')
      return
    }
    setLoading(true)
    try {
      const res = await api.post('/admin/login', {
        username: username.trim(),
        password,
      })
      const { access_token, user } = res.data
      localStorage.setItem('access_token', access_token)
      saveLocalSession({
        role: 'admin',
        email: `${user.username}@admin.detomsite`,
        name: user.name || 'Administrator',
      })

      // Sync admin profile to Supabase
      try {
        await syncProfileToSupabase({
          id: 'admin-0',
          email: `${user.username}@admin.detomsite`,
          name: user.name || 'Administrator',
          role: 'admin',
        })
      } catch {
        // Supabase sync failure is non-blocking
      }

      navigate('/admin-dashboard')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Invalid admin credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="inline-flex h-16 w-16 items-center justify-center rounded-card bg-gold-light/15 text-3xl font-black text-gold shadow-lg backdrop-blur-sm">D</span>
          <h1 className="mt-4 text-3xl font-black text-white">Admin Portal</h1>
          <p className="mt-1 text-sm text-primary/50/60">Secure administration login</p>
        </div>

        <div className="rounded-card border border-white/10 bg-white/5 p-8 backdrop-blur-sm">
          {error && (
            <div className="mb-4 rounded-btn bg-red-500/20 border border-red-500/30 px-4 py-3 text-sm font-medium text-red-300 flex items-center gap-2">
              <span>⚠️</span>{error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm font-semibold text-primary/50/80">Admin Username</label>
              <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                className="w-full rounded-btn border border-white/10 bg-white/10 px-4 py-3 text-sm text-white placeholder-emerald-100/40 outline-none transition-all focus:border-amber-300/50 focus:bg-white/15"
                placeholder="Enter admin username" required autoFocus />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-semibold text-primary/50/80">Password</label>
              <PasswordInputGlass value={password} onChange={setPassword} placeholder="••••••" />
            </div>
            <button type="submit" disabled={loading}
              className="w-full rounded-btn bg-gold px-4 py-3.5 text-sm font-bold text-white shadow-lg shadow-amber-900/30 transition-all hover:bg-gold disabled:opacity-40">
              {loading ? 'Authenticating...' : 'Login to Admin Panel →'}
            </button>
          </form>

          <div className="mt-6 text-center space-y-2">
            <p className="text-xs text-primary/50/40">Use your backend .env admin credentials</p>
            <Link to="/" className="block text-xs font-medium text-primary/50/40 hover:text-gold transition-colors">
              ← Back to portals
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
