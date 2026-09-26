import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import QRCode from 'qrcode'
import api from '../services/api'
import { LocalPaymentSettings, LocalParentOrder } from '../types/localApi'
import { clearCart, getCartByShop, toPaymentGroup } from '../utils/cart'
import { getCheckoutProfile, getLocalSession, rememberCheckout } from '../utils/session'
import { PhoneInput, isValidMobile } from '../components/PhoneInput'

const UPI_LIMIT = 100000

function upiAmount(am: number) { const n = Number(am); return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0 }

/* Delivery is a single fixed drop point: the VIT-AP main gate (enforced
   server-side too), so the checkout shows it as a read-only field. */
const DEFAULT_LOC = 'VIT-AP Main Gate'
function isVitAp(v: string) { return /vit[\s-]*ap/i.test(v || '') && /main[\s-]*gate/i.test(v || '') }

export function PaymentPage() {
  const navigate = useNavigate()
  const session = getLocalSession()
  const [ps, setPs] = useState<LocalPaymentSettings | null>(null)
  const [method, setMethod] = useState<'manual' | 'cod'>('manual')
  const [slot, setSlot] = useState<'Afternoon' | 'Night'>('Afternoon')
  /* Phone + location are restored from the remembered checkout profile so a
     returning student does not retype their number after logging out and back
     in — the "we get out and come back" case. The session wins when it has a
     value, and the profile fills the gap. */
  const [remembered] = useState(() => getCheckoutProfile())
  // One fixed drop point, so the location is constant rather than user-editable.
  const loc = DEFAULT_LOC
  const [phone, setPhone] = useState(() => session?.phone || remembered.phone || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const groups = getCartByShop()
  const total = groups.reduce((sum, g) => sum + g.subtotal, 0)
  const manualReady = Boolean(ps?.manual_enabled && ps.upi_id)
  const upiUrl = manualReady
    ? `upi://pay?pa=${encodeURIComponent((ps?.upi_id || '').trim())}&pn=${encodeURIComponent((ps?.receiver_name || 'DETOMSITE').trim())}&am=${upiAmount(total).toFixed(2)}&cu=INR&tn=${encodeURIComponent(`Detomsite ${total}`)}`
    : ''
  const [upiQrCode, setUpiQrCode] = useState('')

  useEffect(() => {
    api.get<LocalPaymentSettings>('/local/payment-settings')
      .then(r => setPs(r.data)).catch(() => setError('Cannot load payment settings'))
  }, [])

  /* Payment settings load async — if UPI isn't configured on the server the
     "UPI" tab disappears, so stop the form from silently keeping a
     'manual' selection the shop can't accept. */
  useEffect(() => {
    if (ps && !manualReady && method === 'manual') setMethod('cod')
  }, [ps, manualReady, method])

  useEffect(() => {
    let active = true
    if (!upiUrl) {
      setUpiQrCode('')
      return () => { active = false }
    }
    QRCode.toDataURL(upiUrl, { width: 220, margin: 2, errorCorrectionLevel: 'M' })
      .then(url => { if (active) setUpiQrCode(url) })
      .catch(() => { if (active) setUpiQrCode('') })
    return () => { active = false }
  }, [upiUrl])

  /* GPS "use my location" removed: delivery is VIT-AP campus only, and a GPS
     reverse-geocode (city/state/country) would push off-campus text into the
     order. The VIT-AP select below is the only delivery input. */

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!groups.length) { setError('Cart empty'); return }
    if (!isValidMobile(phone)) { setError('Please enter a valid 10-digit mobile number'); return }
    if (!isVitAp(loc)) { setError('Delivery is VIT-AP main gate only.'); return }

    /* Remember the number + gate BEFORE the network calls: if the order or the
       payment POST fails, the student still must not have to retype their
       number on the retry (this was the "get out and come back" complaint). */
    rememberCheckout({ phone: phone.replace(/\s/g, ''), location: loc })

    if (method === 'manual') {
      if (!manualReady) { setError('Manual payment not configured'); return }
      /* No UTR paste anymore: the student pays from the QR / "Scan for
         better option" button and the admin verifies the payment. */
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
        delivery_slot: slot,
        payment_method: method === 'cod' ? 'COD' : 'UTR',
      })

      // Step 2: record the payment (no UTR anymore — the row carries the
      // server-priced amount and the ADMIN verifies it; the frontend never
      // decides payment success). If the save fails the ORDER already exists
      // — never re-submit it (that created duplicate orders); flag it so the
      // result page can tell the student.
      let paymentPending = false
      if (method === 'manual') {
        try {
          await api.post('/local/payments', {
            order_id: order.data.id,
            amount: total,
            method: 'Manual UTR',
            utr_number: '',
          })
        } catch (err: any) {
          paymentPending = true
          const detail = err?.response?.data?.detail || ''
          if (detail) sessionStorage.setItem('payment_pending_detail', String(detail))
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
    : manualReady

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
              <h2 className="mb-4 text-lg font-bold text-primary-dark">Delivery Details · VIT-AP only</h2>
              <div className="space-y-4 mb-6">
                <div>
                  <label className="mb-1 block text-sm font-bold text-gray-500">Delivery location (VIT-AP main gate)</label>
                  {/* One fixed drop point: a read-only field, not a picker. A
                      free-text "room / block" box here could only produce a
                      value the server now rejects, so it is gone. */}
                  <div className="flex w-full items-center justify-between rounded-btn border-2 border-gray-200 bg-gray-50 px-4 py-2.5 text-sm text-gray-900">
                    <span className="font-semibold">{DEFAULT_LOC}</span>
                    <span className="text-[11px] font-bold text-gray-500">Collect at the gate</span>
                  </div>
                  <p className="mt-1.5 text-[11px] font-semibold text-primary">📍 Every order is collected at the VIT-AP main gate.</p>
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
                    <p className="text-sm font-semibold text-primary">UPI Payment — Pay ₹{total} ONCE (one bill for {groups.length} shop{groups.length > 1 ? 's' : ''})</p>
                    {manualReady ? (
                      <div className="mt-2 text-sm text-gray-600">
                        <p>Pay to: {ps?.receiver_name || 'Merchant'} — if your UPI app shows a DIFFERENT name, STOP and pay via mobile number instead</p>
                        <p className="font-mono font-bold text-primary">{ps?.upi_id}</p>
                        {ps?.instructions && <p className="mt-1 text-gray-500">{ps.instructions}</p>}
                        {upiQrCode && (
                          <div className="mt-4 flex flex-col items-center rounded-btn border border-primary-light/60 bg-white p-4 text-center">
                            <img src={upiQrCode} alt={`Scan ONCE to pay ₹${total}`} className="h-52 w-52" />
                            <p className="mt-2 text-sm font-bold text-primary-dark">Scan ONCE to pay ₹{total} (no second scan)</p>
                            <p className="mt-1 text-xs text-gray-500">This is the ONLY QR — the order-result page shows no second QR. Pay once.</p>
                          </div>
                        )}
                        <a
                          href={upiUrl}
                          className="mt-3 flex w-full items-center justify-center gap-2 rounded-btn bg-primary px-4 py-3 text-sm font-bold text-white transition-all hover:bg-primary">
                          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.4 2.1L8.1 10a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.6 2Z" /></svg>
                          Pay via UPI App (GPay / PhonePe / Paytm)
                        </a>
                        <p className="mt-2 text-xs text-primary">Pay FIRST in your UPI app (QR above or the "Scan for better option" button) — then tap "Place Order". The admin verifies the payment; nothing to paste.</p>
                        <p className="mt-1 text-[11px] text-amber-700">If the app warns "THIS PAYMENT MAY FAIL AS PER UPI RISK POLICY": STOP — the VPA name check failed. Pay the same VPA via mobile number instead, or verify receiver name. Do NOT retry blindly.</p>
                      </div>
                    ) : <p className="mt-2 text-sm text-gray-400">Admin hasn't configured payment yet</p>}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {upiUrl ? (
                      <a href={upiUrl}
                        className="flex items-center justify-center gap-2 rounded-btn bg-primary px-4 py-2.5 text-sm font-bold text-white shadow-gold transition-all hover:bg-primary-dark">
                        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M7 12h10" /></svg>
                        Scan for better option
                      </a>
                    ) : null}
                    <select value={slot} onChange={e => setSlot(e.target.value as 'Afternoon' | 'Night')}
                      className="rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-primary">
                      <option value="Afternoon">Afternoon slot · deliver 1:00 – 1:30 PM</option>
                      <option value="Night">Night slot · deliver 7:30 – 8:00 PM</option>
                    </select>
                  </div>
                  <p className="text-xs text-gray-500">Pay in your UPI app first (scan the QR, or use <b>Scan for better option</b> to open the app directly), then tap <b>Place Order</b>. Nothing to paste — the admin verifies the payment. No screenshot upload. No second QR after.</p>
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
                {loading ? 'Placing order...' : method === 'cod' ? `Place COD Order · ₹${total}` : `Place Order · ₹${total}`}
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