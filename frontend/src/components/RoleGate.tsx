import { FormEvent, ReactNode, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { getLocalSession, saveLocalSession } from '../utils/session'
import { PhoneInput, isValidMobile } from './PhoneInput'

interface RoleGateProps { children: ReactNode }

/* Students enter the student portal only — there is no role switcher here.
   Phone-first onboarding creates a real student account (via /local/auth/phone)
   and stores its JWT, so the protected order/payment APIs work exactly like a
   password-login. */

export function RoleGate({ children }: RoleGateProps) {
  const navigate = useNavigate()
  const [hasSession, setHasSession] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (getLocalSession()) setHasSession(true)
  }, [])

  const handleStart = async (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim() || !isValidMobile(phone)) return
    setError('')
    setLoading(true)
    try {
      const res = await api.post('/local/auth/phone', {
        name: name.trim(),
        phone: phone.trim(),
      })
      const { access_token, refresh_token, user } = res.data || {}
      if (access_token) localStorage.setItem('access_token', access_token)
      if (refresh_token) localStorage.setItem('refresh_token', refresh_token)
      saveLocalSession({
        role: 'student',
        email: `${user?.username || 'student'}@student.local`,
        name: (user?.name || name.trim()),
        phone: phone.trim(),
      })
      setHasSession(true)
      navigate('/shops')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not sign you in. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (hasSession) return <>{children}</>

  return (
    <main className="min-h-screen bg-gradient-to-br from-white to-emerald-50">
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-card bg-primary-dark text-3xl font-black text-gold-300 shadow-gold-lg">
            D
          </div>
          <h1 className="text-4xl font-black tracking-tight text-primary-dark">DETOMSITE</h1>
          <p className="mt-2 text-sm font-medium text-gray-500">Campus Food Ordering Platform</p>
        </div>

        <div className="rounded-card bg-white p-8 shadow-gold-lg">
          <h2 className="mb-2 text-xl font-bold text-primary">Student Portal</h2>
          <p className="mb-6 text-sm font-medium text-gray-500">Browse shops, order, and track deliveries — login with your phone number</p>

          <form onSubmit={handleStart} className="space-y-5">
            <div>
              <label className="mb-1.5 block text-sm font-semibold text-gray-700">Your Name</label>
              <input value={name} onChange={e => setName(e.target.value)}
                className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm"
                placeholder="Enter your name" required />
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-gray-700">Phone Number</label>
              <PhoneInput value={phone} onChange={setPhone} />
              <p className="mt-1 text-xs font-medium text-gray-400">Shop deliveries will use this number to reach you.</p>
            </div>

            {error && <p className="rounded-btn bg-red-50 border border-red-200 px-4 py-2.5 text-sm font-medium text-red-600">{error}</p>}

            <button type="submit" disabled={!name.trim() || !isValidMobile(phone) || loading}
              className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-gold transition-all hover:bg-primary-dark hover:shadow-gold-lg disabled:opacity-40 disabled:cursor-not-allowed">
              {loading ? 'Signing in…' : 'Continue →'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs font-medium text-gray-400">By continuing, you agree to our Terms of Service</p>
      </div>
    </main>
  )
}