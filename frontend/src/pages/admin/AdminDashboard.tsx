import { useEffect, useState, useCallback } from 'react'
import api from '../../services/api'
import {
  LocalComplaint,
  LocalMenuChangeRequest,
  LocalOrder,
  LocalPayment,
  LocalPaymentSettings,
  LocalProduct,
  LocalRefund,
  LocalSettlement,
  LocalShop,
  LocalSummary,
} from '../../types/localApi'
import { getLocalSession } from '../../utils/session'
import { usePolling } from '../../hooks/usePolling'
import { same } from '../../utils/same'

const money = (v: number) => `₹${v.toLocaleString('en-IN')}`

/* ─── Web Push helpers (mirror of the shopkeeper app) ─── */
/* Convert the base64url VAPID public key into the Uint8Array the browser's
   PushManager.subscribe() expects. */
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const output = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i)
  return output
}

function pushKeyToBase64(key: ArrayBuffer | null): string {
  if (!key) return ''
  let binary = ''
  const bytes = new Uint8Array(key)
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

type PushState = 'checking' | 'disabled' | 'unsupported' | 'denied' | 'unsubscribed' | 'subscribed' | 'error'

type Tab =
  | 'approvals'
  | 'payments'
  | 'shops'
  | 'complaints'
  | 'refunds'
  | 'settlements'
  | 'menu-changes'
  | 'settings'

export function AdminDashboard() {
  const [shops, setShops] = useState<LocalShop[]>([])
  const [products, setProducts] = useState<LocalProduct[]>([])
  const [orders, setOrders] = useState<LocalOrder[]>([])
  const [payments, setPayments] = useState<LocalPayment[]>([])
  const [summary, setSummary] = useState<LocalSummary | null>(null)
  const [paymentSettings, setPaymentSettings] = useState<LocalPaymentSettings | null>(null)
  const [complaints, setComplaints] = useState<LocalComplaint[]>([])
  const [refunds, setRefunds] = useState<LocalRefund[]>([])
  const [settlements, setSettlements] = useState<LocalSettlement[]>([])
  const [menuChanges, setMenuChanges] = useState<LocalMenuChangeRequest[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('approvals')
  const session = getLocalSession()
  const [pushState, setPushState] = useState<PushState>('checking')
  const [pushPublicKey, setPushPublicKey] = useState('')
  const [pushReason, setPushReason] = useState('')
  const [pushError, setPushError] = useState('')
  const [sendingTest, setSendingTest] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const [s, p, o, pa, su, ps, cm, re, se, mc] = await Promise.all([
        api.get<LocalShop[]>('/local/shops'),
        api.get<LocalProduct[]>('/local/products'),
        api.get<LocalOrder[]>('/local/orders'),
        api.get<LocalPayment[]>('/local/payments'),
        api.get<LocalSummary>('/local/summary'),
        api.get<LocalPaymentSettings>('/local/payment-settings'),
        api.get<LocalComplaint[]>('/local/complaints'),
        api.get<LocalRefund[]>('/local/refunds'),
        api.get<LocalSettlement[]>('/local/settlements'),
        api.get<LocalMenuChangeRequest[]>('/local/menu-change-requests'),
      ])
      setShops(cur => same(cur, s.data) ? cur : s.data)
      setProducts(cur => same(cur, p.data) ? cur : p.data)
      setOrders(cur => same(cur, o.data) ? cur : o.data)
      setPayments(cur => same(cur, pa.data) ? cur : pa.data)
      setSummary(cur => same(cur, su.data) ? cur : su.data)
      setPaymentSettings(cur => same(cur, ps.data) ? cur : ps.data)
      setComplaints(cur => same(cur, cm.data) ? cur : cm.data)
      setRefunds(cur => same(cur, re.data) ? cur : re.data)
      setSettlements(cur => same(cur, se.data) ? cur : se.data)
      setMenuChanges(cur => same(cur, mc.data) ? cur : mc.data)
    } catch {
      setError('Backend not reachable')
    }
  }, [])

  // Poll every 15s while this tab is visible; background tabs pause and refresh
  // instantly when you switch back.
  usePolling(load, 15000, [load])

  /* ─── Web push notifications (ring this phone) ─── */
  /* Start the app service worker and wait until it is really ACTIVE so
     push subscriptions never race a still-installing worker. */
  const ensureServiceWorker = async (timeoutMs = 12000): Promise<ServiceWorkerRegistration> => {
    const registration = await navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      const reg = await navigator.serviceWorker.getRegistration()
      if (reg?.active || registration.active || navigator.serviceWorker.controller) return reg || registration
      await new Promise((r) => setTimeout(r, 400))
    }
    const state = registration.active ? 'active' : registration.installing ? 'installing' : registration.waiting ? 'waiting' : 'none'
    throw new Error('service-worker-timeout:' + state)
  }

  const swStartError = (err: any) => {
    const detail = err?.message || ''
    if (detail.startsWith('service-worker-timeout')) {
      const state = detail.split(':')[1]
      if (state === 'installing' || state === 'waiting') {
        return 'The app service worker got stuck while starting. Close and reopen the app, then try again.'
      }
      return 'The app service worker did not start in this browser. You need the HTTPS site (https://...), a normal tab (not private), and service workers allowed.'
    }
    if (err?.name === 'TypeError' && /mime|script|register/i.test(detail)) {
      return 'The service worker file is not being served correctly. Open /sw.js in your browser — it should show JavaScript code, not HTML.'
    }
    return 'Could not start the app service worker: ' + (detail || 'unknown error')
  }

  const checkPushSupport = async () => {
    try {
      const res = await api.get('/admin/push/config')
      const cfg = res.data || {}
      if (!cfg.enabled || !cfg.vapid_public_key) {
        setPushReason(cfg.reason || 'Push alerts are not configured on the server yet (VAPID keys missing).')
        setPushState('disabled')
        return
      }
      setPushReason('')
      setPushPublicKey(cfg.vapid_public_key)
      if (!window.isSecureContext) {
        setPushError('Push needs a secure (HTTPS) connection. Open the deployed app URL (https://...) instead of a local or LAN address.')
        setPushState('unsupported')
        return
      }
      if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
        setPushState('unsupported')
        return
      }
      let reg
      try {
        reg = await ensureServiceWorker()
      } catch (err) {
        setPushError(swStartError(err))
        setPushState('unsupported')
        return
      }
      try {
        const sub = await reg.pushManager.getSubscription()
        if (sub) {
          // Re-register the current subscription — browsers rotate push keys
          // and endpoints over time, so this keeps the server copy fresh.
          try {
            await api.post('/admin/push/subscribe', {
              endpoint: sub.endpoint,
              keys: { p256dh: pushKeyToBase64(sub.getKey('p256dh')), auth: pushKeyToBase64(sub.getKey('auth')) },
            })
          } catch { /* best-effort — the app still treats it as subscribed */ }
          setPushState('subscribed')
        } else if (Notification.permission === 'denied') setPushState('denied')
        else setPushState('unsubscribed')
      } catch {
        setPushState('unsubscribed')
      }
    } catch {
      setPushReason('The server could not be reached to check push status.')
      setPushState('disabled')
    }
  }

  useEffect(() => {
    if (session?.role === 'admin') void checkPushSupport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const enablePush = async () => {
    setPushError('')
    try {
      if (!pushPublicKey) { setError('Notifications are not configured on the server yet.'); return }
      if (!window.isSecureContext) {
        const msg = 'Push needs a secure (HTTPS) connection — open the deployed app URL (https://...) instead of a local or LAN address, then try again.'
        setError(msg)
        setPushError(msg)
        setPushState('unsupported')
        return
      }
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) { setError("This browser doesn't support push notifications."); return }
      if (Notification.permission === 'denied') { setPushState('denied'); setError('Notifications are blocked — allow them in your browser/site settings.'); return }
      let permission: NotificationPermission = Notification.permission
      if (permission === 'default') permission = await Notification.requestPermission()
      if (permission !== 'granted') { setPushState('denied'); setError('Permission was not granted.'); return }
      let reg
      try {
        reg = await ensureServiceWorker()
      } catch (err) {
        const msg = swStartError(err)
        setError(msg)
        setPushError(msg)
        setPushState('unsupported')
        return
      }
      let sub = await reg.pushManager.getSubscription()
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(pushPublicKey),
        })
      }
      await api.post('/admin/push/subscribe', {
        endpoint: sub.endpoint,
        keys: { p256dh: pushKeyToBase64(sub.getKey('p256dh')), auth: pushKeyToBase64(sub.getKey('auth')) },
      })
      setPushState('subscribed')
      setMessage("Admin notifications enabled — you'll be alerted the moment something needs you")
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Could not enable notifications — the app service worker is not active in this browser.'
      setError(msg)
      setPushError(msg)
      setPushState('error')
    }
  }

  const sendTestPush = async () => {
    setSendingTest(true)
    setPushError('')
    try {
      const res = await api.post('/admin/push/test')
      const data = res.data || {}
      if (data.ok) setMessage(data.detail || 'Test notification sent!')
      else setPushError(data.detail || 'Test push failed')
    } catch (err: any) {
      setPushError(err?.response?.data?.detail || 'Could not send test notification')
    } finally { setSendingTest(false) }
  }

  const disablePush = async () => {
    setPushError('')
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        try { await api.delete('/admin/push/subscribe', { params: { endpoint: sub.endpoint } }) } catch { /* best-effort */ }
        await sub.unsubscribe()
      }
      setPushState('unsubscribed')
      setMessage('Admin notifications disabled')
    } catch { setError('Could not disable notifications') }
  }

  const approveShop = async (id: string, st: string) => {
    const r = await api.patch<LocalShop>(`/local/shops/${id}`, { approval_status: st })
    setShops(curr => curr.map(s => (s.id === id ? r.data : s)))
    setMessage(`Shop ${st}`)
  }
  const verifyPayment = async (id: string, st: string) => {
    const r = await api.patch<LocalPayment>(`/local/payments/${id}/status`, { status: st })
    setPayments(curr => curr.map(p => (p.id === id ? r.data : p)))
    setMessage(`Payment ${st}`)
  }

  // Complaint actions
  const updateComplaint = async (id: string, status: string, adminNotes = '') => {
    const r = await api.patch<LocalComplaint>(`/local/complaints/${id}`, { status, admin_notes: adminNotes })
    setComplaints(curr => curr.map(c => (c.id === id ? r.data : c)))
    setMessage(`Complaint ${status.toLowerCase()}`)
  }

  // Refund actions
  const updateRefund = async (id: string, status: string, refundUtr = '', adminNotes = '') => {
    const r = await api.patch<LocalRefund>(`/local/refunds/${id}`, { status, refund_utr: refundUtr, admin_notes: adminNotes })
    setRefunds(curr => curr.map(ref => (ref.id === id ? r.data : ref)))
    setMessage(`Refund ${status.toLowerCase()}`)
  }

  // Settlement actions
  const runSettlements = async () => {
    await api.post('/local/settlements/run')
    setMessage('Settlements processed')
    void load()
  }

  // Menu change actions
  const updateMenuChange = async (id: string, status: string, adminNotes = '') => {
    const r = await api.patch<LocalMenuChangeRequest>(`/local/menu-change-requests/${id}`, { status, admin_notes: adminNotes })
    setMenuChanges(curr => curr.map(m => (m.id === id ? r.data : m)))
    setMessage(`Menu change ${status.toLowerCase()}`)
  }

  const pendingShops = shops.filter(s => s.approval_status === 'Pending Approval')
  const pendingPayments = payments.filter(p => p.status === 'Pending Verification')
  const pendingPrices = products.filter(p => p.pending_price)
  const openComplaints = complaints.filter(c => c.status === 'Open' || c.status === 'Under Review')
  const pendingRefunds = refunds.filter(r => r.status === 'Pending')
  const pendingMenuChanges = menuChanges.filter(m => m.status === 'Pending')
  const totalRevenue = summary?.revenue ?? orders.reduce((s, o) => s + o.total, 0)
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'approvals', label: 'Approvals', count: pendingShops.length + pendingPrices.length },
    { id: 'payments', label: 'Payments', count: pendingPayments.length },
    { id: 'complaints', label: 'Complaints', count: openComplaints.length },
    { id: 'refunds', label: 'Refunds', count: pendingRefunds.length },
    { id: 'settlements', label: 'Settlements' },
    { id: 'menu-changes', label: 'Menu Changes', count: pendingMenuChanges.length },
    { id: 'shops', label: 'Shops' },
    { id: 'settings', label: 'Settings' },
  ]

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-primary-dark">Admin Panel</h1>
          <p className="mt-1 text-sm font-medium text-gray-500">{session?.email || 'Admin'}</p>
          {(message || error) && (
            <div
              className={`mt-3 rounded-lg px-4 py-2 text-sm font-medium ${
                error
                  ? 'border border-red-200 bg-red-50 text-red-600'
                  : 'border border-primary-light/50 bg-primary-light/30 text-primary'
              }`}
            >
              {error || message}
            </div>
          )}
        </div>

        <div className="mb-6 rounded-btn border border-primary-light/40 bg-primary-light/10 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="text-2xl">🔔</span>
              <div>
                <p className="font-bold text-primary-dark">Admin Notifications</p>
                <p className="text-xs text-gray-500">
                  Get an alert on this phone when something needs you (new vendor, payment to verify, feedback).
                </p>
                {pushState === 'subscribed' && (
                  <p className="mt-0.5 text-xs font-semibold text-emerald-600">Notifications enabled on this device</p>
                )}
                {pushState === 'denied' && (
                  <p className="mt-0.5 text-xs font-semibold text-red-600">
                    Notifications are blocked — allow them in your browser/site settings.
                  </p>
                )}
                {pushState !== 'subscribed' && pushState !== 'denied' && (pushReason || pushError) && (
                  <p className="mt-0.5 text-xs font-medium text-amber-600">{pushError || pushReason}</p>
                )}
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {pushState === 'subscribed' ? (
                <>
                  <button
                    onClick={() => void sendTestPush()}
                    disabled={sendingTest}
                    className="rounded-lg border border-primary/30 bg-white px-3 py-2 text-sm font-bold text-primary hover:bg-primary-light/20 disabled:opacity-50"
                  >
                    {sendingTest ? 'Sending...' : 'Test Alert'}
                  </button>
                  <button
                    onClick={() => void disablePush()}
                    className="rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-bold text-red-600 hover:bg-red-50"
                  >
                    Disable
                  </button>
                </>
              ) : (
                <button
                  onClick={() => void enablePush()}
                  disabled={pushState === 'checking' || pushState === 'disabled' || pushState === 'unsupported'}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-50"
                >
                  {pushState === 'checking' ? 'Checking...' : 'Enable Notifications'}
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="mb-6 grid grid-cols-3 gap-3 sm:grid-cols-6">
          {[
            ['Orders', orders.length],
            ['Revenue', money(totalRevenue)],
            ['Shops', shops.length],
            ['Pending', pendingShops.length],
            ['Payments', pendingPayments.length],
            ['Open', summary?.orderable_shops ?? 0],
          ].map(([l, v]) => (
            <div key={l} className="rounded-btn bg-white p-3 shadow-card">
              <p className="text-xs font-medium text-gray-500">{l}</p>
              <p className="mt-1 text-lg font-bold text-primary-dark">{v}</p>
            </div>
          ))}
        </div>

        <div className="mb-6 flex gap-2 overflow-x-auto border-b border-gray-100 pb-px">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`whitespace-nowrap px-4 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px ${
                tab === t.id
                  ? 'border-emerald-600 text-primary'
                  : 'border-transparent text-gray-400 hover:text-gray-600'
              }`}
            >
              {t.label}
              {t.count ? ` (${t.count})` : ''}
            </button>
          ))}
        </div>

        {tab === 'approvals' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-btn bg-white p-5 shadow-card">
              <h2 className="mb-3 text-lg font-bold text-primary">Shop Approvals</h2>
              <div className="space-y-3">
                {pendingShops.map(shop => (
                  <div key={shop.id} className="rounded-btn border border-gold-200 bg-gold-50/30 p-4">
                    <div className="mb-2 flex items-start justify-between">
                      <div>
                        <p className="font-bold text-primary-dark">{shop.name}</p>
                        <p className="text-xs text-gray-500">
                          {shop.category} · {shop.shopkeeper_name}
                        </p>
                      </div>
                      <span className="shrink-0 rounded-lg bg-gold-100 px-2 py-0.5 text-xs font-bold text-gold-700">
                        Pending
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        onClick={() => void approveShop(shop.id, 'Approved')}
                        className="rounded-lg bg-primary px-3 py-2 text-sm font-bold text-white hover:bg-primary"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => void approveShop(shop.id, 'Rejected')}
                        className="rounded-lg border border-red-200 px-3 py-2 text-sm font-bold text-red-600 hover:bg-red-50"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                ))}
                {pendingShops.length === 0 && <p className="text-sm text-gray-400">No pending approvals</p>}
              </div>
            </section>
            <section className="rounded-btn bg-white p-5 shadow-card">
              <h2 className="mb-3 text-lg font-bold text-primary">Price Requests</h2>
              <div className="space-y-3">
                {pendingPrices.map(p => (
                  <div key={p.id} className="rounded-btn border border-gold-200 bg-gold-50/30 p-4">
                    <p className="font-bold text-primary-dark">{p.name}</p>
                    <p className="text-xs text-gray-500">
                      ₹{p.price} → ₹{p.pending_price}
                    </p>
                  </div>
                ))}
                {pendingPrices.length === 0 && <p className="text-sm text-gray-400">No requests</p>}
              </div>
            </section>
          </div>
        )}

        {tab === 'payments' && (
          <section className="rounded-btn bg-white p-5 shadow-card">
            <h2 className="mb-3 text-lg font-bold text-primary">Payment Verification</h2>
            <div className="space-y-3">
              {pendingPayments.map(p => (
                <div key={p.id} className="rounded-btn border border-gold-200 bg-gold-50/30 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-bold text-primary-dark">Order {p.order_id}</p>
                      <p className="text-xs text-gray-500">
                        {money(p.amount)} · {p.method} · UTR: {p.utr_number || 'N/A'}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button
                        onClick={() => void verifyPayment(p.id, 'Success')}
                        className="rounded-lg bg-primary px-3 py-2 text-sm font-bold text-white"
                      >
                        Verify
                      </button>
                      <button
                        onClick={() => void verifyPayment(p.id, 'Failed')}
                        className="rounded-lg border border-red-200 px-3 py-2 text-sm font-bold text-red-600"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              {pendingPayments.length === 0 && <p className="text-sm text-gray-400">No pending payments</p>}
            </div>
          </section>
        )}

        {tab === 'complaints' && (
          <section className="rounded-btn bg-white p-5 shadow-card">
            <h2 className="mb-3 text-lg font-bold text-primary">Complaints ({openComplaints.length} open)</h2>
            <div className="space-y-3">
              {complaints.map(c => (
                <div
                  key={c.id}
                  className="rounded-btn border border-gray-100 bg-gray-50/50 p-4"
                >
                  <div className="mb-2 flex items-start justify-between">
                    <div>
                      <p className="font-bold text-primary-dark">{c.subject}</p>
                      <p className="text-xs text-gray-500">
                        {c.student_name} · {c.shop_name} · Order {c.parent_order_id.slice(-6)}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 rounded-lg px-2 py-0.5 text-xs font-bold ${
                        c.status === 'Open'
                          ? 'bg-red-100 text-red-600'
                          : c.status === 'Under Review'
                            ? 'bg-amber-100 text-amber-600'
                            : 'bg-emerald-100 text-emerald-600'
                      }`}
                    >
                      {c.status}
                    </span>
                  </div>
                  <p className="mb-2 text-sm text-gray-600">{c.message}</p>
                  {c.admin_notes && (
                    <p className="mb-2 rounded bg-gray-100 px-3 py-2 text-xs text-gray-500">
                      Admin: {c.admin_notes}
                    </p>
                  )}
                  <p className="mb-2 text-xs text-gray-400">Phone: {c.student_phone} · {c.created_at?.slice(0, 16)}</p>
                  {c.status !== 'Resolved' && c.status !== 'Closed' && (
                    <div className="flex gap-2">
                      <button
                        onClick={() => void updateComplaint(c.id, 'Under Review')}
                        className="rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-bold text-white"
                      >
                        Mark In Review
                      </button>
                      <button
                        onClick={() => void updateComplaint(c.id, 'Resolved', 'Resolved by admin')}
                        className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-white"
                      >
                        Resolve
                      </button>
                      <button
                        onClick={() => void updateComplaint(c.id, 'Closed', 'Dismissed')}
                        className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-bold text-gray-500"
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {complaints.length === 0 && <p className="text-sm text-gray-400">No complaints</p>}
            </div>
          </section>
        )}

        {tab === 'refunds' && (
          <section className="rounded-btn bg-white p-5 shadow-card">
            <h2 className="mb-3 text-lg font-bold text-primary">Refunds ({pendingRefunds.length} pending)</h2>
            <div className="space-y-3">
              {refunds.map(r => (
                <div key={r.id} className="rounded-btn border border-gray-100 bg-gray-50/50 p-4">
                  <div className="mb-2 flex items-start justify-between">
                    <div>
                      <p className="font-bold text-primary-dark">
                        {r.refund_type} · {money(r.refund_amount)}
                      </p>
                      <p className="text-xs text-gray-500">
                        {r.student_name} · {r.shop_name} · Original: {money(r.original_amount)}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 rounded-lg px-2 py-0.5 text-xs font-bold ${
                        r.status === 'Pending'
                          ? 'bg-amber-100 text-amber-600'
                          : r.status === 'Processed'
                            ? 'bg-blue-100 text-blue-600'
                            : 'bg-emerald-100 text-emerald-600'
                      }`}
                    >
                      {r.status}
                    </span>
                  </div>
                  {r.admin_notes && (
                    <p className="mb-2 rounded bg-gray-100 px-3 py-2 text-xs text-gray-500">
                      Admin: {r.admin_notes}
                    </p>
                  )}
                  <p className="mb-2 text-xs text-gray-400">Created: {r.created_at?.slice(0, 16)}</p>
                  {r.status === 'Pending' && (
                    <div className="flex gap-2">
                      <button
                        onClick={() => void updateRefund(r.id, 'Processed', '', 'Refund approved')}
                        className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-white"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => void updateRefund(r.id, 'Rejected', '', 'Refund denied')}
                        className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-bold text-red-600"
                      >
                        Deny
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {refunds.length === 0 && <p className="text-sm text-gray-400">No refunds</p>}
            </div>
          </section>
        )}

        {tab === 'settlements' && (
          <section className="rounded-btn bg-white p-5 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-primary">Settlements (9:00 PM daily)</h2>
              <button
                onClick={() => void runSettlements()}
                className="rounded-pill bg-primary px-4 py-2 text-sm font-bold text-white hover:bg-primary-dark"
              >
                Run Settlements Now
              </button>
            </div>
            <div className="space-y-3">
              {settlements.map(s => (
                <div key={s.id} className="rounded-btn border border-gray-100 bg-gray-50/50 p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-bold text-primary-dark">{s.shop_name} · {s.date_key}</p>
                      <p className="text-xs text-gray-500">
                        Gross: {money(s.gross_sales)} · Commission: {money(s.commission_5pct)} · Refunds: -{money(s.refunds_adjusted)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-lg font-bold text-primary">{money(s.net_payable)}</p>
                      <span
                        className={`rounded-lg px-2 py-0.5 text-xs font-bold ${
                          s.status === 'Pending'
                            ? 'bg-amber-100 text-amber-600'
                            : 'bg-emerald-100 text-emerald-600'
                        }`}
                      >
                        {s.status}
                      </span>
                    </div>
                  </div>
                  {s.settlement_utr && (
                    <p className="mt-1 text-xs text-gray-400">UTR: {s.settlement_utr}</p>
                  )}
                </div>
              ))}
              {settlements.length === 0 && <p className="text-sm text-gray-400">No settlements yet</p>}
            </div>
          </section>
        )}

        {tab === 'menu-changes' && (
          <section className="rounded-btn bg-white p-5 shadow-card">
            <h2 className="mb-3 text-lg font-bold text-primary">
              Menu Change Requests ({pendingMenuChanges.length} pending)
            </h2>
            <div className="space-y-3">
              {menuChanges.map(m => (
                <div key={m.id} className="rounded-btn border border-gray-100 bg-gray-50/50 p-4">
                  <div className="mb-2 flex items-start justify-between">
                    <div>
                      <p className="font-bold text-primary-dark">{m.change_type}: {m.field_name}</p>
                      <p className="text-xs text-gray-500">Product {m.product_id.slice(-6)} · Shop {m.shop_id.slice(-6)}</p>
                    </div>
                    <span
                      className={`shrink-0 rounded-lg px-2 py-0.5 text-xs font-bold ${
                        m.status === 'Pending'
                          ? 'bg-amber-100 text-amber-600'
                          : m.status === 'Approved'
                            ? 'bg-emerald-100 text-emerald-600'
                            : 'bg-red-100 text-red-600'
                      }`}
                    >
                      {m.status}
                    </span>
                  </div>
                  <p className="mb-1 text-sm text-gray-600">
                    Old: <span className="line-through text-gray-400">{m.old_value}</span> → New: <span className="font-semibold text-primary-dark">{m.new_value}</span>
                  </p>
                  {m.admin_notes && (
                    <p className="mb-2 rounded bg-gray-100 px-3 py-2 text-xs text-gray-500">Admin: {m.admin_notes}</p>
                  )}
                  <p className="mb-2 text-xs text-gray-400">Created: {m.created_at?.slice(0, 16)}</p>
                  {m.status === 'Pending' && (
                    <div className="flex gap-2">
                      <button
                        onClick={() => void updateMenuChange(m.id, 'Approved', 'Approved by admin')}
                        className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-white"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => void updateMenuChange(m.id, 'Rejected', 'Rejected by admin')}
                        className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-bold text-red-600"
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {menuChanges.length === 0 && <p className="text-sm text-gray-400">No menu change requests</p>}
            </div>
          </section>
        )}

        {tab === 'shops' && (
          <section className="rounded-btn bg-white shadow-card">
            <div className="border-b border-gray-100 px-5 py-3">
              <h2 className="text-lg font-bold text-primary">All Shops</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-primary-light/30/50">
                  <tr>
                    {['Shop', 'Approval', 'Status', 'Orders', 'Revenue'].map(h => (
                      <th key={h} className="px-5 py-3 text-left text-xs font-bold text-gray-500">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shops.map(shop => (
                    <tr key={shop.id} className="border-t border-gray-50">
                      <td className="px-5 py-3 font-bold text-primary-dark">{shop.name}</td>
                      <td className="px-5 py-3">
                        <span
                          className={`rounded-lg px-2 py-0.5 text-xs font-bold ${
                            shop.approval_status === 'Approved'
                              ? 'bg-primary-light/30 text-primary'
                              : shop.approval_status === 'Pending Approval'
                                ? 'bg-gold-50 text-gold-600'
                                : 'bg-red-50 text-red-600'
                          }`}
                        >
                          {shop.approval_status}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-gray-600">{shop.status}</td>
                      <td className="px-5 py-3 text-gray-600">{shop.orders_today}</td>
                      <td className="px-5 py-3 font-semibold text-primary">{money(shop.revenue_today)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === 'settings' && (
          <section className="rounded-btn bg-white p-5 shadow-card">
            <h2 className="mb-4 text-lg font-bold text-primary">Payment Settings</h2>
            {paymentSettings && (
              <form
                onSubmit={e => {
                  e.preventDefault()
                  setMessage('Saving...')
                  api
                    .patch<LocalPaymentSettings>('/local/payment-settings', paymentSettings)
                    .then(r => {
                      setPaymentSettings(r.data)
                      setMessage('Settings saved successfully')
                    })
                    .catch(() => setMessage('Failed to save settings'))
                }}
                className="max-w-md space-y-4"
              >
                <label className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-gray-700">
                  <input
                    type="checkbox"
                    checked={paymentSettings.manual_enabled}
                    onChange={e => setPaymentSettings({ ...paymentSettings, manual_enabled: e.target.checked })}
                    className="h-4 w-4 accent-emerald-600"
                  />
                  Enable manual UPI/UTR payments
                </label>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-600">Receiver Name</label>
                  <input
                    value={paymentSettings.receiver_name}
                    onChange={e => setPaymentSettings({ ...paymentSettings, receiver_name: e.target.value })}
                    className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm"
                    placeholder="Receiver name"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-600">UPI ID</label>
                  <input
                    value={paymentSettings.upi_id}
                    onChange={e => setPaymentSettings({ ...paymentSettings, upi_id: e.target.value })}
                    className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm"
                    placeholder="UPI ID"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-600">Instructions</label>
                  <textarea
                    value={paymentSettings.instructions}
                    onChange={e => setPaymentSettings({ ...paymentSettings, instructions: e.target.value })}
                    className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm"
                    placeholder="Instructions"
                    rows={3}
                  />
                </div>
                <button className="rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark">
                  Save Settings
                </button>
              </form>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
