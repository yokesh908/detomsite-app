import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { saveLocalSession } from '../../utils/session'
import api from '../../services/api'
import { PhoneInput, isValidMobile } from '../../components/PhoneInput'
import { PasswordInput } from '../../components/PasswordInput'

export function ShopkeeperRegister() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ fullName: '', email: '', phone: '', password: '', confirmPassword: '', shopName: '', shopCategory: '', campus: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const categories = ['Italian', 'Chinese', 'Indian', 'Fast Food', 'Biryani', 'Cafe', 'Bakery', 'Desserts', 'Beverages', 'Vegan', 'Japanese', 'Mexican', 'Continental']

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.fullName || !form.email || !form.phone || !form.password || !form.shopName || !form.shopCategory || !form.campus) { setError('All fields are required'); return }
    if (form.password !== form.confirmPassword) { setError('Passwords do not match'); return }
    if (!isValidMobile(form.phone)) { setError('Please enter a valid 10-digit mobile number'); return }
    setLoading(true)
    try {
      await api.post('/local/shops', { name: form.shopName, category: form.shopCategory, description: `${form.shopName} at ${form.campus}`, shopkeeper_email: form.email, shopkeeper_name: form.fullName, phone: form.phone })
      saveLocalSession({ role: 'shopkeeper', email: form.email, name: form.fullName, phone: form.phone, shop_name: form.shopName, shop_category: form.shopCategory })
      navigate('/shopkeeper-dashboard')
    } catch { setError('Unable to submit registration. Is the backend running?') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-white to-emerald-50 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <Link to="/" className="inline-flex items-center gap-2">
            <span className="flex h-10 w-10 items-center justify-center rounded-btn bg-primary-dark text-lg font-black text-gold-300 shadow-gold-sm">D</span>
            <span className="text-2xl font-black text-primary-dark">DETOMSITE</span>
          </Link>
        </div>
        <div className="rounded-card bg-white p-8 shadow-gold-lg">
          <div className="mb-6 text-center">
            <span className="text-4xl">👨‍🍳</span>
            <h1 className="mt-2 text-2xl font-bold text-primary-dark">Shopkeeper Registration</h1>
            <p className="mt-1 text-sm font-medium text-gray-500">Register your restaurant on campus</p>
          </div>
          {error && <div className="mb-4 rounded-btn bg-red-50 border border-red-200 px-4 py-3 text-sm font-medium text-red-600">{error}</div>}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div><label className="mb-1 block text-sm font-semibold text-gray-700">Full Name *</label>
                <input value={form.fullName} onChange={e => setForm({...form, fullName: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Your name" /></div>
              <div><label className="mb-1 block text-sm font-semibold text-gray-700">Phone *</label>
                <PhoneInput value={form.phone} onChange={v => setForm({...form, phone: v})} /></div>
            </div>
            <div><label className="mb-1 block text-sm font-semibold text-gray-700">Email *</label>
              <input type="email" value={form.email} onChange={e => setForm({...form, email: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="business@restaurant.com" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="mb-1 block text-sm font-semibold text-gray-700">Shop Name *</label>
                <input value={form.shopName} onChange={e => setForm({...form, shopName: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Your restaurant" /></div>
              <div><label className="mb-1 block text-sm font-semibold text-gray-700">Category *</label>
                <select value={form.shopCategory} onChange={e => setForm({...form, shopCategory: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm">
                  <option value="">Select</option>
                  {categories.map(c => <option key={c} value={c}>{c}</option>)}
                </select></div>
            </div>
            <div><label className="mb-1 block text-sm font-semibold text-gray-700">Campus *</label>
              <input value={form.campus} onChange={e => setForm({...form, campus: e.target.value})} className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Main Campus" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="mb-1 block text-sm font-semibold text-gray-700">Password *</label>
                <PasswordInput value={form.password} onChange={v => setForm({...form, password: v})} autoComplete="new-password" /></div>
              <div><label className="mb-1 block text-sm font-semibold text-gray-700">Confirm *</label>
                <PasswordInput value={form.confirmPassword} onChange={v => setForm({...form, confirmPassword: v})} autoComplete="new-password" /></div>
            </div>
            <div className="rounded-btn bg-primary-light/30 border border-primary-light/50 px-4 py-3">
              <p className="text-xs font-semibold text-primary">⏳ After registration, your shop will be <strong>"Pending Approval"</strong>. An admin must approve it before students can see and order from it.</p>
            </div>
            <button type="submit" disabled={loading} className="w-full rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-gold transition-all hover:bg-primary-dark hover:shadow-gold-lg disabled:opacity-40">
              {loading ? 'Registering...' : 'Register Shop →'}
            </button>
          </form>
          <div className="mt-6 text-center">
            <span className="text-sm text-gray-400">Already registered? </span>
            <Link to="/login" className="text-sm font-bold text-primary hover:text-primary">Sign In</Link>
          </div>
        </div>
      </div>
    </div>
  )
}
