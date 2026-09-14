import { useEffect, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../services/api'
import { LocalParentOrder } from '../types/localApi'
import { usePolling } from '../hooks/usePolling'
import { same } from '../utils/same'

const statusStyles: Record<string, { bg: string; color: string; border: string }> = {
  Completed: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
  Cancelled: { bg: '#FEF2F2', color: '#DC2626', border: '#FECACA' },
  Pending: { bg: '#FFFBEB', color: '#966A2C', border: '#FDE68A' },
  Delivered: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
}

const subOrderStyles: Record<string, { bg: string; color: string; border: string }> = {
  Completed: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
  Delivered: { bg: '#ECFDF5', color: '#065F46', border: '#A7F3D0' },
  Cancelled: { bg: '#FEF2F2', color: '#DC2626', border: '#FECACA' },
  Rejected: { bg: '#FEF2F2', color: '#DC2626', border: '#FECACA' },
  Accepted: { bg: '#EFF6FF', color: '#1D4ED8', border: '#BFDBFE' },
  Preparing: { bg: '#FFFBEB', color: '#966A2C', border: '#FDE68A' },
  Ready: { bg: '#F0FDF4', color: '#15803D', border: '#BBF7D0' },
  Pending: { bg: '#FFFBEB', color: '#966A2C', border: '#FDE68A' },
}

export function OrderResultPage() {
  const { orderId = '' } = useParams()
  const [order, setOrder] = useState<LocalParentOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [paymentPending, setPaymentPending] = useState(false)

  useEffect(() => {
    const flag = sessionStorage.getItem('payment_pending')
    if (flag) { sessionStorage.removeItem('payment_pending'); setPaymentPending(true) }
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
                <p className="font-bold">⚠️ Payment proof received but the record didn't save.</p>
                <p className="mt-1">Your order <b>was placed</b> — contact support with your token <b>#{order.token}</b> to submit your UTR and screenshot.</p>
              </div>
            )}
            <p className="text-xs font-bold uppercase tracking-wider text-gray-500">Order Result</p>
            <h1 className="mt-3 text-5xl font-black text-primary-dark">Token {order.token}</h1>
            <p className="mt-2 text-lg font-semibold text-gray-600">{order.student_name}</p>
            <div className="mt-5 inline-flex rounded-btn px-4 py-2 text-sm font-bold"
              style={parentStyle}>{order.status}</div>
            <p className="mt-2 text-sm text-gray-500">{order.sub_orders?.length || 0} shop{order.sub_orders?.length !== 1 ? 's' : ''} · one payment</p>

            <div className="mt-6 space-y-4 text-left">
              {order.sub_orders?.map(sub => {
                const st = subOrderStyles[sub.status] || subOrderStyles.Pending
                return (
                  <div key={sub.id} className="rounded-lg bg-gray-50 p-4 border border-gray-100">
                    <div className="flex items-center justify-between">
                      <h3 className="font-bold text-primary-dark">🏪 {sub.shop_name}</h3>
                      <span className="rounded-pill px-2.5 py-1 text-xs font-bold" style={st}>{sub.status}</span>
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