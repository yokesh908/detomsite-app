import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../../services/api'
import { syncProfileToSupabase } from '../../services/supabase'
import { PhoneInput, isValidMobile } from '../../components/PhoneInput'
import { PasswordInput } from '../../components/PasswordInput'

export function UserRegister() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    username: '', email: '', phone: '', password: '', confirmPassword: '',
    agreeTerms: false,
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.username || !form.email || !form.phone || !form.password) {
      setError('All required fields must be filled')
      return
    }
    if (form.password !== form.confirmPassword) {
      setError('Passwords do not match')
      return
    }
    if (form.password.length < 4) {
      setError('Password must be at least 4 characters')
      return
    }
    if (!isValidMobile(form.phone)) {
      setError('Please enter a valid 10-digit mobile number')
      return
    }
    if (!form.agreeTerms) {
      setError('You must agree to the Terms & Conditions')
      return
    }

    setLoading(true)
    try {
      const regRes = await api.post('/users/register', {
        username: form.username,
        email: form.email,
        password: form.password,
        name: form.username,
        phone: form.phone,
      })

      // Sync user profile to Supabase
      if (regRes.data?.user?.id) {
        try {
          await syncProfileToSupabase({
            id: String(regRes.data.user.id),
            email: form.email,
            name: form.username,
            role: 'student',
          })
        } catch {
          // Supabase sync failure is non-blocking
        }
      }

      // Redirect to user login page on success
      navigate('/user/login?registered=true')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Registration failed. Try a different username.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-white to-emerald-50 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center">
          <Link to="/" className="inline-flex items-center gap-2">
            <span className="flex h-10 w-10 items-center justify-center rounded-btn bg-primary-dark text-lg font-black text-gold">D</span>
            <span className="text-2xl font-black text-primary-dark">DETOMSITE</span>
          </Link>
        </div>

        <div className="rounded-card bg-white p-8 shadow-[0_20px_60px_rgba(15,118,110,0.12)] border border-primary-light/30">
          <div className="mb-6 text-center">
            <span className="text-4xl">🎓</span>
            <h1 className="mt-2 text-2xl font-bold text-primary-dark">Student Registration</h1>
            <p className="mt-1 text-sm font-medium text-gray-500">Create your campus food account</p>
          </div>

          {error && (
            <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600 flex items-center gap-2">
              <span>⚠️</span>{error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Username *</label>
              <input type="text" value={form.username} onChange={e => setForm({...form, username: e.target.value})}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Choose a username" required />
            </div>

            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Email *</label>
              <input type="email" value={form.email} onChange={e => setForm({...form, email: e.target.value})}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="you@campus.com" required />
            </div>

            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Mobile Number *</label>
              <PhoneInput value={form.phone} onChange={v => setForm({...form, phone: v})} placeholder="98765 43210" required />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm font-semibold text-gray-700">Password *</label>
                <PasswordInput value={form.password} onChange={v => setForm({...form, password: v})} autoComplete="new-password" required />
              </div>
              <div>
                <label className="mb-1 block text-sm font-semibold text-gray-700">Confirm Password *</label>
                <PasswordInput value={form.confirmPassword} onChange={v => setForm({...form, confirmPassword: v})} autoComplete="new-password" required />
              </div>
            </div>

            {/* Terms & Conditions */}
            <label className="flex items-start gap-3 cursor-pointer">
              <input type="checkbox" checked={form.agreeTerms} onChange={e => setForm({...form, agreeTerms: e.target.checked})}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 accent-emerald-600" />
              <span className="text-xs text-gray-500">
                I agree to the{' '}
                <a href="#" className="font-semibold text-primary hover:text-primary">Terms & Conditions</a>
                {' '}and{' '}
                <a href="#" className="font-semibold text-primary hover:text-primary">Privacy Policy</a>
              </span>
            </label>

            <button type="submit" disabled={loading || !form.agreeTerms}
              className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-lg shadow-emerald-900/20 transition-all hover:bg-primary-dark disabled:opacity-40">
              {loading ? 'Creating Account...' : 'Create Account →'}
            </button>
          </form>

          <div className="mt-6 text-center">
            <span className="text-sm text-gray-400">Already have an account? </span>
            <Link to="/user/login" className="text-sm font-bold text-primary hover:text-primary">Sign In</Link>
          </div>
        </div>
      </div>
    </div>
  )
}
