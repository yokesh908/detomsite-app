import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { LocalPaymentSettings, LocalParentOrder } from '../types/localApi'
import { clearCart, getCartByShop, toPaymentGroup } from '../utils/cart'
import { getLocalSession } from '../utils/session'
import { PhoneInput, isValidMobile } from '../components/PhoneInput'

const UPI_LIMIT = 100000

function upiAmount(am: number) { const n = Number(am); return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0 }

export function PaymentPage() {
  const navigate = useNavigate()
  const session = getLocalSession()
  const [ps, setPs] = useState<LocalPaymentSettings | null>(null)
  const [method, setMethod] = useState<'manual' | 'cod'>('manual')
  const [utr, setUtr] = useState('')
  const [ssFile, setSsFile] = useState<File | null>(null)
  const [loc, setLoc] = useState(session?.default_delivery_location || 'Hostel A Block 201')
  const [phone, setPhone] = useState(session?.phone || '')
  const [locating, setLocating] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const groups = getCartByShop()
  const total = groups.reduce((sum, g) => sum + g.subtotal, 0)
  const manualReady = Boolean(ps?.manual_enabled && ps.upi_id)

  useEffect(() => {
    api.get<LocalPaymentSettings>('/local/payment-settings')
      .then(r => setPs(r.data)).catch(() => setError('Cannot load payment settings'))
  }, [])

  /* Payment settings load async — if UPI isn't configured on the server the
     "UPI (UTR)" tab disappears, so stop the form from silently keeping a
     'manual' selection the shop can't accept. */
  useEffect(() => {
    if (ps && !manualReady && method === 'manual') setMethod('cod')
  }, [ps, manualReady, method])

  const reverseGeocode = async (lat: number, lon: number): Promise<string> => {
    try {
      const r = await fetch(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=en`)
      if (r.ok) {
        const d = await r.json()
        const parts = [d.locality, d.city, d.principalSubdivision, d.countryName].filter((x: any) => x && String(x).trim())
        if (parts.length) return parts.join(', ')
      }
    } catch { /* try the fallback below */ }
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}&zoom=18&addressdetails=1`)
      if (r.ok) {
        const d = await r.json()
        if (d?.display_name) return String(d.display_name)
      }
    } catch { /* give up */ }
    return ''
  }

  const useMyLocation = () => {
    if (!navigator.geolocation) { setError('Location is not supported in this browser — please type it manually.'); return }
    setLocating(true)
    setError('')
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude, lon = pos.coords.longitude
        setLoc(`${lat.toFixed(4)}, ${lon.toFixed(4)}`)
        const address = await reverseGeocode(lat, lon)
        setLoc(address || `${lat.toFixed(4)}, ${lon.toFixed(4)}`)
        setLocating(false)
      },
      () => { setLocating(false); setError('Could not get your location — please type it manually.') },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!groups.length) { setError('Cart empty'); return }
    if (!isValidMobile(phone)) { setError('Please enter a valid 10-digit mobile number'); return }

    if (method === 'manual') {
      if (!manualReady) { setError('Manual payment not configured'); return }
      if (!utr.trim() || !ssFile) { setError('Enter UTR and attach screenshot'); return }
    }

    setLoading(true)
    try {
      // Step 1: Create the multi-shop parent order (ONE token for all shops).
      const order = await api.post<LocalParentOrder>('/local/orders/multi', {
        shops: groups.map(g => toPaymentGroup(g)),
        student_name: session?.name || 'Student',
        student_phone: phone,
        student_email: session?.email || '',
        delivery_location: loc,
        delivery_slot: method === 'cod' ? 'COD' : 'UTR',
        payment_method: method === 'cod' ? 'COD' : 'UTR',
      })

      // Step 2: If UPI/UTR, submit the payment record and upload the real
      // screenshot file. Verification is done by the admin/backend (frontend
      // never decides payment success). If payment delivery fails the ORDER
      // already exists — never re-submit it (that created duplicate orders),
      // just flag the payment as pending and let the student retry later.
      let paymentPending = false
      if (method === 'manual') {
        try {
          await api.post('/local/payments', {
            order_id: order.data.id,
            amount: total,
            method: 'Manual UTR',
            utr_number: utr,
            screenshot_name: ssFile?.name,
          })
          if (ssFile) {
            const fd = new FormData()
            fd.append('file', ssFile)
            fd.append('order_id', order.data.id)
            fd.append('utr_number', utr)
            await api.post('/local/payments/upload', fd)
          }
        } catch {
          paymentPending = true
        }
      }

      clearCart()
      if (paymentPending) sessionStorage.setItem('payment_pending', '1')
      navigate(`/order-result/${order.data.id}`)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Order could not be placed')
    } finally {
      setLoading(false)
    }
  }

  const canPay = method === 'cod'
    ? true
    : manualReady && Boolean(utr.trim()) && Boolean(ssFile)

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-primary-dark">Checkout</h1>
          <p className="mt-1 text-sm font-medium text-gray-500">
            {groups.length === 0 ? 'Review your order' : `${groups.length} shop${groups.length > 1 ? 's' : ''} · one payment`}
          </p>
        </div>
        {groups.length === 0 ? (
          <div className="rounded-btn bg-white p-8 text-center shadow-card">
            <p className="mb-4 text-lg font-semibold text-gray-600">Cart is empty</p>
            <Link to="/shops" className="inline-flex rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm">Browse →</Link>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_340px]">
            <div className="rounded-btn bg-white p-5 shadow-card">
              <h2 className="mb-4 text-lg font-bold text-primary-dark">Delivery Details</h2>
              <div className="space-y-4 mb-6">
                <div className="flex gap-2">
                  <input value={loc} onChange={e => setLoc(e.target.value)}
                    className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Delivery location" required />
                  <button type="button" onClick={useMyLocation} disabled={locating}
                    className="shrink-0 rounded-btn border-2 border-primary-light/50 bg-primary-light/30 px-3 py-2 text-xs font-bold text-primary transition-all hover:bg-primary-light disabled:opacity-50">
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" /></svg>
                    {locating ? 'Locating...' : 'Use my location'}
                  </button>
                </div>
                <PhoneInput value={phone} onChange={setPhone} placeholder="98765 43210" required />
              </div>

              <h2 className="mb-4 text-lg font-bold text-primary-dark">Payment Method</h2>

              <div className="mb-4 flex gap-3">
                {manualReady && (
                  <button type="button" onClick={() => setMethod('manual')}
                    className={`flex-1 rounded-btn border-2 p-4 text-center transition-all ${
                      method === 'manual' ? 'border-emerald-500 bg-primary-light/30 shadow-emerald-sm' : 'border-gray-200 hover:border-emerald-300'
                    }`}>
                    <span className="mx-auto mb-1 flex h-8 w-8 items-center justify-center rounded-pill bg-primary-light text-primary"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M2 10h20" /></svg></span>
                    <span className={`text-xs font-bold ${method === 'manual' ? 'text-primary' : 'text-gray-500'}`}>UPI (UTR)</span>
                  </button>
                )}
                <button type="button" onClick={() => setMethod('cod')}
                  className={`flex-1 rounded-btn border-2 p-4 text-center transition-all ${
                    method === 'cod' ? 'border-emerald-500 bg-primary-light/30 shadow-emerald-sm' : 'border-gray-200 hover:border-emerald-300'
                  }`}>
                  <span className="mx-auto mb-1 flex h-8 w-8 items-center justify-center rounded-pill bg-primary-light text-primary">💵</span>
                  <span className={`text-xs font-bold ${method === 'cod' ? 'text-primary' : 'text-gray-500'}`}>Cash on Delivery</span>
                </button>
              </div>

              {method === 'manual' && (
                <div className="space-y-4">
                  {total > UPI_LIMIT && (
                    <div className="flex items-start gap-2.5 rounded-btn border-2 border-amber-300 bg-amber-50 p-4">
                      <svg className="h-5 w-5 shrink-0 text-gold-dark" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17.5v.5" /></svg>
                      <div className="text-xs leading-relaxed text-gold-dark">
                        <p className="font-bold">₹{total.toLocaleString('en-IN')} is above the UPI transaction limit (₹{UPI_LIMIT.toLocaleString('en-IN')}).</p>
                        <p className="mt-1">Banks cap UPI per payment — above the limit the bank rejects the transaction with “exceeded the bank limit … retry with a smaller amount”, and <b>no money is debited</b>. Please choose a smaller order, or split it into two payments.</p>
                      </div>
                    </div>
                  )}
                  <div className="rounded-btn bg-primary-light/30 border border-primary-light/50 p-4">
                    <p className="text-sm font-semibold text-primary">UPI Payment — Pay ₹{total} (one bill for {groups.length} shop{groups.length > 1 ? 's' : ''})</p>
                    {manualReady ? (
                      <div className="mt-2 text-sm text-gray-600">
                        <p>Pay to: {ps?.receiver_name || 'Merchant'}</p>
                        <p className="font-mono font-bold text-primary">{ps?.upi_id}</p>
                        {ps?.instructions && <p className="mt-1 text-gray-500">{ps.instructions}</p>}
                        <a
                          href={`upi://pay?pa=${encodeURIComponent((ps?.upi_id || '').trim())}&pn=${encodeURIComponent((ps?.receiver_name || 'DETOMSITE').trim())}&am=${upiAmount(total).toFixed(2)}&cu=INR&mode=04&tn=${encodeURIComponent('DETOMSITE Multi-Shop Order')}`}
                          className="mt-3 flex w-full items-center justify-center gap-2 rounded-btn bg-primary px-4 py-3 text-sm font-bold text-white transition-all hover:bg-primary">
                          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>
                          Pay via UPI App (GPay / PhonePe / Paytm)
                        </a>
                        <p className="mt-2 text-xs text-primary">Opens your UPI app — pay now, then enter the UTR and upload the screenshot below.</p>
                      </div>
                    ) : <p className="mt-2 text-sm text-gray-400">Admin hasn't configured payment yet</p>}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <input value={utr} onChange={e => setUtr(e.target.value)}
                      className="rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="UTR / Transaction ID" required={method === 'manual'} />
                    <input onChange={e => setSsFile(e.target.files?.[0] || null)}
                      className="rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm" type="file" accept="image/*,.pdf" required={method === 'manual'} />
                  </div>
                </div>
              )}

              {method === 'cod' && (
                <div className="rounded-btn bg-amber-50/70 border border-amber-200 p-4 text-sm text-amber-700">
                  💵 You'll pay cash to each shop when they deliver. No COD fee.
                  <p className="mt-1 text-xs text-amber-600/80">For a multi-shop order each shop collects its own share on delivery. Cash on Delivery orders can't be edited or cancelled after a shop accepts them.</p>
                </div>
              )}

              {error && <p className="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-2 text-sm font-medium text-red-600">{error}</p>}
            </div>

            <div className="h-fit rounded-btn bg-white p-5 shadow-gold">
              <h2 className="mb-4 text-lg font-bold text-primary-dark">Summary</h2>
              <div className="space-y-2 text-sm">
                {groups.map(g => (
                  <div key={g.shop_id} className="flex justify-between">
                    <span className="text-gray-500">{g.shop_name}</span>
                    <span className="font-semibold text-primary">₹{g.subtotal}</span>
                  </div>
                ))}
                <div className="flex justify-between border-t border-gray-100 pt-3 text-lg font-bold text-primary-dark">
                  <span>Total</span><span>₹{total}</span>
                </div>
                <p className="pt-1 text-xs text-gray-400">No delivery fee, no taxes, no COD fee. Each shop's flat ₹10 per order is on them, never you.</p>
              </div>
              <button type="submit" disabled={loading || !canPay}
                className="mt-5 w-full rounded-btn bg-primary px-5 py-3 text-sm font-bold text-white shadow-gold transition-all hover:bg-primary-dark disabled:opacity-40">
                {loading ? 'Placing order...' : method === 'cod' ? `Place COD Order · ₹${total}` : `Pay ₹${total} via UPI`}
              </button>
              {!manualReady && method === 'manual' && (
                <p className="mt-3 text-center text-xs font-medium text-gray-400">UPI not configured — use COD instead.</p>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}