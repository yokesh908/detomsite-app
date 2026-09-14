import { useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import { saveLocalSession } from '../../utils/session'
import { InstallPwaCard } from '../../components/InstallPwaCard'
import { syncProfileToSupabase } from '../../services/supabase'
import { PhoneInput, isValidMobile } from '../../components/PhoneInput'
import { PasswordInput } from '../../components/PasswordInput'

export function VendorRegister() {
  const [form, setForm] = useState({
    username: '', email: '', phone: '', password: '', confirmPassword: '',
    shopName: '', shopCategory: '', shopDescription: '',
    agreeTerms: false,
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [registered, setRegistered] = useState(false)
  const [approvalStatus, setApprovalStatus] = useState<'pending' | 'approved' | null>(null)
  const categories = ['Italian', 'Chinese', 'Indian', 'Fast Food', 'Biryani', 'Cafe', 'Bakery', 'Desserts', 'Beverages', 'Vegan', 'Japanese', 'Mexican', 'Continental']

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.username || !form.email || !form.phone || !form.password || !form.shopName || !form.shopCategory) {
      setError('All required fields must be filled')
      return
    }
    if (form.password !== form.confirmPassword) { setError('Passwords do not match'); return }
    if (form.password.length < 4) { setError('Password must be at least 4 characters'); return }
    if (!isValidMobile(form.phone)) { setError('Please enter a valid 10-digit mobile number'); return }
    if (!form.agreeTerms) { setError('You must agree to the Terms & Conditions'); return }

    setLoading(true)
    try {
      const regRes = await api.post('/vendor/register', {
        username: form.username,
        email: form.email,
        password: form.password,
        name: form.username,
        phone: form.phone,
        shop_name: form.shopName,
        shop_category: form.shopCategory,
        shop_description: form.shopDescription,
      })

      // Sync vendor profile to Supabase
      try {
        const vendorUserId = regRes.data?.user?.id || form.username
        await syncProfileToSupabase({
          id: String(vendorUserId),
          email: form.email,
          name: form.username,
          role: 'shopkeeper',
        })
      } catch {
        // Supabase sync failure is non-blocking
      }

      // Auto-login: store session
      const loginRes = await api.post('/vendor/login', {
        username: form.username,
        password: form.password,
      })
      const { access_token, user } = loginRes.data
      localStorage.setItem('access_token', access_token)
      saveLocalSession({
        role: 'shopkeeper',
        email: user.email || `${user.username}@campus.local`,
        name: user.name,
        shop_name: form.shopName,
        shop_category: form.shopCategory,
        phone: form.phone,
      })

      setRegistered(true)
      setApprovalStatus('pending')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Registration failed. Try a different username.')
    } finally {
      setLoading(false)
    }
  }

  // After registration, show the pending approval + PWA install page
  if (registered) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-white to-amber-50">
        <div className="mx-auto max-w-2xl px-4 py-12">
          <div className="mb-8 text-center">
            <span className="text-5xl">👨‍🍳</span>
            <h1 className="mt-3 text-3xl font-black text-primary-dark">Registration Submitted!</h1>
          </div>

          {approvalStatus === 'pending' && (
            <div className="rounded-card border border-gold-light/60 bg-amber-50 p-6 mb-6">
              <div className="flex items-center gap-3 mb-3">
                <span className="text-2xl">⏳</span>
                <div>
                  <h2 className="font-bold text-gold-dark">Pending Admin Approval</h2>
                  <p className="text-sm text-gold-dark">Your shop "{form.shopName}" needs to be approved by an admin before it goes live.</p>
                </div>
              </div>
              <div className="h-2 bg-gold-light rounded-pill overflow-hidden">
                <div className="h-full w-1/3 bg-gold rounded-pill animate-pulse" />
              </div>
            </div>
          )}

          {/* Install the mobile app for notifications */}
          <div className="mb-6">
            <InstallPwaCard />
          </div>

          <div className="rounded-card border border-primary-light/30 bg-white p-6 shadow-[0_14px_42px_rgba(15,118,110,0.12)]">
            <h2 className="text-lg font-bold text-primary-dark">What happens next?</h2>
            <ol className="mt-4 space-y-3 text-sm text-gray-600">
              <li className="flex items-start gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-primary-light text-xs font-bold text-primary">1</span>
                <span><strong>Admin Review</strong> — An admin will review and approve your shop request.</span>
              </li>
              <li className="flex items-start gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-primary-light text-xs font-bold text-primary">2</span>
                <span><strong>Install App</strong> — Install the app on your phone using the button above to get instant order notifications.</span>
              </li>
              <li className="flex items-start gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-pill bg-primary-light text-xs font-bold text-primary">3</span>
                <span><strong>Start Selling</strong> — Once approved, toggle "Accepting Orders" on and start receiving orders!</span>
              </li>
            </ol>
          </div>

          <div className="mt-6 text-center space-y-3">
            <Link to="/shopkeeper-dashboard"
              className="inline-flex items-center gap-2 rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white shadow-lg hover:bg-primary-dark">
              Go to Dashboard →
            </Link>
            <br />
            <Link to="/" className="text-xs font-medium text-gray-400 hover:text-primary">← Back to portals</Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-white to-amber-50 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center">
          <Link to="/" className="inline-flex items-center gap-2">
            <span className="flex h-10 w-10 items-center justify-center rounded-btn bg-primary-dark text-lg font-black text-gold">D</span>
            <span className="text-2xl font-black text-primary-dark">DETOMSITE</span>
          </Link>
        </div>

        <div className="rounded-card bg-white p-8 shadow-[0_20px_60px_rgba(15,118,110,0.12)] border border-gold-light/40">
          <div className="mb-6 text-center">
            <span className="text-4xl">👨‍🍳</span>
            <h1 className="mt-2 text-2xl font-bold text-primary-dark">Shopkeeper Registration</h1>
            <p className="mt-1 text-sm font-medium text-gray-500">Register your restaurant on campus</p>
          </div>

          {error && (
            <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600 flex items-center gap-2">
              <span>⚠️</span>{error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Personal Info */}
            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Username *</label>
              <input type="text" value={form.username} onChange={e => setForm({...form, username: e.target.value})}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 outline-none focus:border-amber-500 focus:shadow-amber-sm" placeholder="Choose username" required />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm font-semibold text-gray-700">Email *</label>
                <input type="email" value={form.email} onChange={e => setForm({...form, email: e.target.value})}
                  className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 outline-none focus:border-amber-500 focus:shadow-amber-sm" placeholder="business@shop.com" required />
              </div>
              <div>
                <label className="mb-1 block text-sm font-semibold text-gray-700">Mobile *</label>
                <PhoneInput value={form.phone} onChange={v => setForm({...form, phone: v})} placeholder="98765 43210" required />
              </div>
            </div>

            {/* Shop Info */}
            <div className="border-t border-gray-100 pt-4">
              <p className="text-sm font-bold text-gold-dark mb-3">🏪 Shop Details</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-sm font-semibold text-gray-700">Shop Name *</label>
                  <input type="text" value={form.shopName} onChange={e => setForm({...form, shopName: e.target.value})}
                    className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 outline-none focus:border-amber-500 focus:shadow-amber-sm" placeholder="Your restaurant name" required />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-semibold text-gray-700">Category *</label>
                  <select value={form.shopCategory} onChange={e => setForm({...form, shopCategory: e.target.value})}
                    className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 outline-none focus:border-amber-500 focus:shadow-amber-sm" required>
                    <option value="">Select category</option>
                    {categories.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div className="mt-3">
                <label className="mb-1 block text-sm font-semibold text-gray-700">Description</label>
                <textarea value={form.shopDescription} onChange={e => setForm({...form, shopDescription: e.target.value})}
                  className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 outline-none focus:border-amber-500 focus:shadow-amber-sm" placeholder="Tell students about your shop..." rows={2} />
              </div>
            </div>

            {/* Password */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm font-semibold text-gray-700">Password *</label>
                <PasswordInput value={form.password} onChange={v => setForm({...form, password: v})} autoComplete="new-password" required />
              </div>
              <div>
                <label className="mb-1 block text-sm font-semibold text-gray-700">Confirm *</label>
                <PasswordInput value={form.confirmPassword} onChange={v => setForm({...form, confirmPassword: v})} autoComplete="new-password" required />
              </div>
            </div>

            {/* Info notice */}
            <div className="rounded-btn bg-amber-50 border border-gold-light/60 px-4 py-3">
              <p className="text-xs font-semibold text-gold-dark">
                ⏳ After registration, your shop will be <strong>"Pending Approval"</strong>. An admin must approve it before students can see and order from it.
              </p>
            </div>

            {/* Terms */}
            <label className="flex items-start gap-3 cursor-pointer">
              <input type="checkbox" checked={form.agreeTerms} onChange={e => setForm({...form, agreeTerms: e.target.checked})}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 accent-amber-600" />
              <span className="text-xs text-gray-500">
                I agree to the <a href="#" className="font-semibold text-gold-dark">Terms & Conditions</a> and <a href="#" className="font-semibold text-gold-dark">Vendor Agreement</a>
              </span>
            </label>

            <button type="submit" disabled={loading || !form.agreeTerms}
              className="w-full rounded-btn bg-amber-600 px-6 py-3.5 text-base font-bold text-white shadow-lg shadow-amber-900/20 transition-all hover:bg-amber-700 disabled:opacity-40">
              {loading ? 'Registering...' : 'Register Shop →'}
            </button>
          </form>

          <div className="mt-6 text-center">
            <span className="text-sm text-gray-400">Already registered? </span>
            <Link to="/shopkeeper-dashboard" className="text-sm font-bold text-gold-dark hover:text-gold-dark">Go to Dashboard</Link>
          </div>
        </div>
      </div>
    </div>
  )
}
