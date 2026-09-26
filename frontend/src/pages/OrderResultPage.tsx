import { useEffect, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../services/api'
import { LocalParentOrder, LocalPaymentSettings } from '../types/localApi'
import { usePolling } from '../hooks/usePolling'
import { same } from '../utils/same'

const statusStyles: Record<string, { bg: string; color: string; border: string }> = {
  Completed: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
  Confirmed: { bg: '#F0FDF4', color: '#15803D', border: '#BBF7D0' },
  Cancelled: { bg: '#FEF2F2', color: '#DC2626', border: '#FECACA' },
  Pending: { bg: '#FFFBEB', color: '#966A2C', border: '#FDE68A' },
  Delivered: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
}

const statusLabels: Record<string, string> = {
  Pending: 'Order Pending',
  Confirmed: 'Order Confirmed',
  Accepted: 'Order Accepted',
  Preparing: 'Preparing Food',
  Ready: 'Ready for Pickup',
  Delivered: 'Delivered',
  Completed: 'Order Completed',
}

const subOrderStyles: Record<string, { bg: string; color: string; border: string }> = {
  Completed: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
  Delivered: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
  Cancelled: { bg: '#FEF2F2', color: '#DC2626', border: '#FECACA' },
  Rejected: { bg: '#FEF2F2', color: '#DC2626', border: '#FECACA' },
  Confirmed: { bg: '#F0FDF4', color: '#15803D', border: '#BBF7D0' },
  Accepted: { bg: '#EFF6FF', color: '#1D4ED8', border: '#BFDBFE' },
  Preparing: { bg: '#FFFBEB', color: '#966A2C', border: '#FDE68A' },
  Ready: { bg: '#F0FDF4', color: '#15803D', border: '#BBF7D0' },
  Pending: { bg: '#FFFBEB', color: '#966A2C', border: '#FDE68A' },
}

/* Order journey: Pending → Confirmed → Preparing → Ready → Delivered → Completed.
   Renders a 6-step gold/green progress bar so students always see where their
   order stands without hunting through status pills. */
const journeySteps = [
  { key: 'Pending', label: 'Pending' },
  { key: 'Confirmed', label: 'Confirmed' },
  { key: 'Preparing', label: 'Preparing' },
  { key: 'Ready', label: 'Ready' },
  { key: 'Delivered', label: 'Delivered' },
  { key: 'Completed', label: 'Completed' },
]
const journeyInnerRank: Record<string, number> = { Pending: 0, Accepted: 1, Confirmed: 1, Preparing: 2, Ready: 3, Delivered: 4, Completed: 5 }

function OrderJourney({ status }: { status: string }) {
  const rank = journeyInnerRank[status] ?? (status === 'Cancelled' || status === 'Rejected' ? -1 : 0)
  return (
    <div className="mt-5 rounded-btn border border-primary-light/30 bg-white p-4">
      <p className="mb-3 text-left text-xs font-black uppercase tracking-wider text-primary">Order Journey</p>
      <div className="flex items-center gap-1">
        {journeySteps.map((step, i) => {
          const done = rank >= i
          const isCancelled = rank < 0
          return (
            <div key={step.key} className="flex flex-1 flex-col items-center gap-1.5">
              <div className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-black transition-all ${
                isCancelled
                  ? 'bg-red-100 text-red-600'
                  : (done ? (step.key === 'Confirmed' ? 'bg-gold text-white shadow-gold-sm' : 'bg-primary text-white shadow-emerald-sm') : 'bg-slate-100 text-slate-400')
              }`}>
                {isCancelled ? '✕' : done ? (step.key === 'Completed' ? '✓' : (i + 1)) : ''}
              </div>
              <span className={`text-[10px] font-bold ${done ? 'text-primary' : 'text-slate-400'}`}>{step.label}</span>
            </div>
          )
        })}
      </div>
      <div className="relative mt-1 flex gap-1">
        {journeySteps.map((step, i) => (
          <div key={step.key} className={`h-1 flex-1 rounded-pill ${rank >= i ? (step.key === 'Confirmed' ? 'bg-gold' : 'bg-primary') : 'bg-slate-200'}`} />
        ))}
      </div>
    </div>
  )
}

export function OrderResultPage() {
  const { orderId = '' } = useParams()
  const [order, setOrder] = useState<LocalParentOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [paymentPending, setPaymentPending] = useState(false)
  const [pendingDetail, setPendingDetail] = useState('')

  useEffect(() => {
    const flag = sessionStorage.getItem('payment_pending')
    if (flag) { sessionStorage.removeItem('payment_pending'); setPaymentPending(true) }
    const detail = sessionStorage.getItem('payment_pending_detail')
    if (detail) { sessionStorage.removeItem('payment_pending_detail'); setPendingDetail(detail) }
  }, [])

  const load = useCallback(() => {
    api.get<LocalParentOrder>(`/local/orders/parent/${orderId}`)
      .then(r => setOrder(cur => same(cur, r.data) ? cur : r.data))
      .catch(() => setOrder(null))
      .finally(() => setLoading(false))
  }, [orderId])

  // Poll every 5s while this tab is visible so the student sees the order get
  // auto-accepted; background tabs pause and refresh instantly on switch-back.
  usePolling(load, 5000, [orderId])

  /* The UTR paste/recovery box was removed with the UTR verification method.
     The payment settings below power the "Scan for better option" pay button
     (the platform UPI used at checkout) while the payment is pending. */
  const [ps, setPs] = useState<LocalPaymentSettings | null>(null)
  useEffect(() => {
    api.get<LocalPaymentSettings>('/local/payment-settings').then(r => setPs(r.data)).catch(() => {})
  }, [])

  const awaitingPayment = order
    && String(order.payment_method || '').toUpperCase() !== 'COD'
    && String(order.payment_status || '').toUpperCase() !== 'PAID'
    && order.status !== 'Cancelled'
  const payUpi = ps?.manual_enabled ? ps.upi_id?.trim() || '' : ''
  const payUri = awaitingPayment && payUpi && order
    ? `upi://pay?pa=${encodeURIComponent(payUpi)}&pn=${encodeURIComponent((ps?.receiver_name || 'DETOMSITE').trim())}&am=${(Math.round(Number(order.total) * 100) / 100).toFixed(2)}&cu=INR&tn=${encodeURIComponent(`Detomsite ${order.total}`)}`
    : ''

  const parentStyle = order ? statusStyles[order.status] || statusStyles.Pending : statusStyles.Pending

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-3xl px-4 py-6">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-400 font-medium">Loading...</div>
        ) : order ? (
          <div className="rounded-btn bg-white p-6 shadow-gold-lg text-center">
            {paymentPending && (
              <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-left text-sm text-amber-700">
                <p className="font-bold">⚠️ Your order was placed, but the payment record didn't save.</p>
                {pendingDetail && <p className="mt-1 text-xs">{pendingDetail}</p>}
                <p className="mt-1">No problem — your order is safe. If you already paid in your UPI app, send the UTR shown there to the shop so the admin can record it; otherwise complete the payment with the button below.</p>
              </div>
            )}
            <p className="text-xs font-bold uppercase tracking-wider text-gray-500">Order Result</p>
            <h1 className="mt-3 text-5xl font-black text-primary-dark">Token {order.token}</h1>
            <p className="mt-2 text-lg font-semibold text-gray-600">{order.student_name}</p>
            <div className="mt-5 inline-flex rounded-btn px-4 py-2 text-sm font-bold"
              style={parentStyle}>{statusLabels[order.status] || order.status}</div>
            <p className="mt-2 text-sm text-gray-500">{order.sub_orders?.length || 0} shop{order.sub_orders?.length !== 1 ? 's' : ''} · one payment</p>

            <OrderJourney status={order.status} />

            <div className="mt-6 space-y-4 text-left">
              {order.sub_orders?.map(sub => {
                const st = subOrderStyles[sub.status] || subOrderStyles.Pending
                return (
                  <div key={sub.id} className="rounded-lg bg-gray-50 p-4 border border-gray-100">
                    <div className="flex items-center justify-between">
                      <h3 className="font-bold text-primary-dark">🏪 {sub.shop_name}</h3>
                      <span className="rounded-pill px-2.5 py-1 text-xs font-bold" style={st}>{statusLabels[sub.status] || sub.status}</span>
                    </div>
                    <p className="mt-1 text-sm text-gray-600">{sub.items_summary}</p>
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                      <span className="font-semibold text-primary">₹{sub.subtotal}</span>
                      {sub.shop_phone && (
                        <a href={`tel:${sub.shop_phone}`} className="inline-flex items-center gap-1.5 rounded-pill bg-white border border-gray-200 px-3 py-1 text-xs font-bold text-gray-700 hover:border-primary">📞 Call {sub.shop_name}</a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="mt-6 rounded-btn bg-gray-50 p-5 text-left space-y-2 text-sm">
              <p className="text-gray-500">{order.delivery_location}</p>
              <p className="font-semibold text-primary">₹{order.total}</p>
              <p className="text-gray-500">Payment: {order.payment_method} · {order.payment_status}</p>
            </div>

            {awaitingPayment && (
              <div className="mt-4 rounded-card border border-emerald-200 bg-emerald-50/60 p-4 text-left">
                <p className="text-sm font-bold text-primary">Payment pending — complete it in your UPI app.</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-primary">Pay ₹{order.total} once — the admin verifies the payment and confirms your order. Do NOT scan any other QR.</p>
                {payUri ? (
                  <a href={payUri}
                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-btn bg-primary px-4 py-2.5 text-sm font-bold text-white transition-all hover:bg-primary-dark">
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M7 12h10" /></svg>
                    Scan for better option · Pay ₹{order.total}
                  </a>
                ) : null}
              </div>
            )}

            <div className="mt-6 flex justify-center gap-3">
              <Link to="/customer-dashboard" className="rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark">Track Orders →</Link>
              <Link to="/shops" className="rounded-btn border border-gray-200 bg-white px-5 py-2.5 text-sm font-bold text-gray-600 hover:bg-gray-50">Order More</Link>
            </div>
          </div>
        ) : (
          <div className="rounded-btn bg-white p-6 text-center shadow-card">
            <h2 className="text-xl font-bold text-gray-600">Order not found</h2>
            <Link to="/shops" className="mt-4 inline-flex rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm">Browse shops →</Link>
          </div>
        )}
      </div>
    </div>
  )
}