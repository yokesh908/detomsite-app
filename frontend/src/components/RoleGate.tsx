import { FormEvent, ReactNode, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { saveSessionToBackend } from '../services/localApi'
import { getDashboardPath, getLocalSession, saveLocalSession, UserRoleChoice } from '../utils/session'
import { PhoneInput, isValidMobile } from './PhoneInput'

interface RoleGateProps { children: ReactNode }

const ROLE_ROUTES: Record<string, UserRoleChoice> = {
  '/shops': 'student', '/shop': 'student', '/cart': 'student', '/payment': 'student',
  '/order-result': 'student', '/customer-dashboard': 'student', '/feedback': 'student',
  '/support': 'student', '/home': 'student',
  '/shopkeeper-dashboard': 'shopkeeper',
  '/admin-dashboard': 'admin',
}

const roles = [
  { id: 'student' as UserRoleChoice, label: 'Student', icon: '🎓', desc: 'Order food from campus shops — login with your phone number', color: 'from-emerald-500 to-emerald-700' },
  { id: 'shopkeeper' as UserRoleChoice, label: 'Shopkeeper', icon: '👨‍🍳', desc: 'Manage your shop and orders', color: 'from-gold-500 to-gold-700' },
  { id: 'admin' as UserRoleChoice, label: 'Admin', icon: '⚙️', desc: 'Oversee campus operations', color: 'from-emerald-600 to-emerald-900' },
]

export function RoleGate({ children }: RoleGateProps) {
  const navigate = useNavigate()
  const [hasSession, setHasSession] = useState(false)
  const [role, setRole] = useState<UserRoleChoice>('student')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [accessDenied, setAccessDenied] = useState(false)

  useEffect(() => {
    const session = getLocalSession()
    if (session) {
      // Check role-based access: if user is on a dashboard that doesn't match their role, redirect
      const path = window.location.pathname
      const requiredRole = Object.entries(ROLE_ROUTES).find(([prefix]) => path.startsWith(prefix))?.[1]
      if (requiredRole && session.role !== requiredRole) {
        setAccessDenied(true)
        return
      }
      setHasSession(true)
    }
  }, [])

  const handleStart = (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    // Students enter by phone number (OTP-ready); shopkeepers/admins use email.
    const identity = role === 'student' ? phone : email.trim()
    if (!identity) return
    const session: Parameters<typeof saveLocalSession>[0] = {
      role,
      email: role === 'student' ? phone : identity,
      name: name.trim(),
      phone: role === 'student' ? phone : undefined,
    }
    saveLocalSession(session)
    void saveSessionToBackend({ role, email: identity, name: name.trim() })
    setHasSession(true)
    navigate(getDashboardPath(role))
  }

  if (accessDenied) {
    const session = getLocalSession()
    const correctPath = session ? getDashboardPath(session.role) : '/'
    return (
      <div className="min-h-screen bg-gradient-to-br from-white to-red-50 flex items-center justify-center px-6">
        <div className="max-w-md text-center">
          <div className="text-6xl mb-4">🚫</div>
          <h1 className="text-2xl font-bold text-red-600">Access Denied</h1>
          <p className="mt-2 text-gray-500">You don't have permission to access this page as a <strong>{session?.role}</strong>.</p>
          <button onClick={() => { setAccessDenied(false); navigate(correctPath) }}
            className="mt-4 rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark">
            Go to your dashboard
          </button>
        </div>
      </div>
    )
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
          <h2 className="mb-6 text-xl font-bold text-primary">Welcome, who are you?</h2>

          <form onSubmit={handleStart} className="space-y-5">
            <div className="grid grid-cols-3 gap-3">
              {roles.map(option => (
                <button key={option.id} type="button" onClick={() => setRole(option.id)}
                  className={`group rounded-btn border-2 p-4 text-center transition-all ${
                    role === option.id ? 'border-emerald-500 bg-primary-light/30 shadow-emerald-sm' : 'border-gray-100 bg-white hover:border-primary-light/50'
                  }`}>
                  <span className="block text-2xl">{option.icon}</span>
                  <span className={`mt-1 block text-sm font-bold ${role === option.id ? 'text-primary' : 'text-gray-600'}`}>{option.label}</span>
                </button>
              ))}
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-semibold text-gray-700">Your Name</label>
              <input value={name} onChange={e => setName(e.target.value)}
                className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm"
                placeholder="Enter your name" required />
            </div>

            {role === 'student' ? (
              <div>
                <label className="mb-1.5 block text-sm font-semibold text-gray-700">Phone Number</label>
                <PhoneInput value={phone} onChange={setPhone} />
                <p className="mt-1 text-xs font-medium text-gray-400">Shop deliveries will use this number to reach you.</p>
              </div>
            ) : (
              <div>
                <label className="mb-1.5 block text-sm font-semibold text-gray-700">Email Address</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                  className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm"
                  placeholder={role === 'shopkeeper' ? 'shop@campus.com' : 'admin@campus.com'} required />
              </div>
            )}

            <div className="rounded-btn bg-primary-light/30 px-4 py-3 text-sm font-medium text-primary">
              {roles.find(r => r.id === role)?.desc}
            </div>

            <button type="submit"
              disabled={!name.trim() || (role === 'student' ? !isValidMobile(phone) : !email.trim())}
              className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-gold transition-all hover:bg-primary-dark hover:shadow-gold-lg disabled:opacity-40 disabled:cursor-not-allowed">
              Continue →
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs font-medium text-gray-400">By continuing, you agree to our Terms of Service</p>
      </div>
    </main>
  )
}
