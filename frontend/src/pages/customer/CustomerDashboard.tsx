import { useEffect, useState, useCallback } from 'react'
import { orderGroup } from '../../utils/operations'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import { LocalNotification, LocalParentOrder, LocalTicket } from '../../types/localApi'
import { getLocalSession, saveLocalSession } from '../../utils/session'
import { subscribeNotifications } from '../../services/notifStore'
import { usePolling } from '../../hooks/usePolling'
import { same } from '../../utils/same'

type Notice = { kind: 'ok' | 'error'; text: string } | null

const statusLabels: Record<string, string> = {
  Pending: 'Pending',
  Confirmed: 'Confirmed',
  Accepted: 'Accepted',
  Preparing: 'Preparing',
  Ready: 'Ready',
  Delivered: 'Delivered',
  Completed: 'Completed',
}
const subStatusLabels: Record<string, string> = {
  Confirmed: 'Confirmed',
  Accepted: 'Accepted',
  Preparing: 'Preparing',
  Ready: 'Ready',
}

export function CustomerDashboard() {
  const session = getLocalSession()
  const [orders, setOrders] = useState<LocalParentOrder[]>([])
  const [tickets, setTickets] = useState<LocalTicket[]>([])
  const [notifications, setNotifications] = useState<LocalNotification[]>([])
  const [notice, setNotice] = useState<Notice>(null)
  const [editingProfile, setEditingProfile] = useState(false)
  const [profileForm, setProfileForm] = useState({ name: session?.name || '', phone: session?.phone || '', email: session?.email || '' })
  const [savingProfile, setSavingProfile] = useState(false)
  const [editNotice, setEditNotice] = useState<Notice>(null)
  const profilePhone = session?.phone || ''

  const startEditProfile = () => {
    setProfileForm({ name: session?.name || '', phone: session?.phone || '', email: session?.email || '' })
    setEditNotice(null)
    setEditingProfile(true)
  }

  const saveProfile = async () => {
    const name = profileForm.name.trim()
    if (!name) {
      setEditNotice({ kind: 'error', text: 'Name is required' })
      return
    }
    setSavingProfile(true)
    setEditNotice(null)
    try {
      const r = await api.patch<{ access_token: string; user: { name: string; email: string; phone: string; role: string } }>('/local/auth/me', {
        name,
        phone: profileForm.phone.trim(),
        email: profileForm.email.trim(),
      })
      if (r.data.access_token) localStorage.setItem('access_token', r.data.access_token)
      saveLocalSession({
        role: session?.role || 'student',
        email: r.data.user.email || session?.email || '',
        name: r.data.user.name || name,
        phone: r.data.user.phone || profileForm.phone.trim(),
      })
      setNotice({ kind: 'ok', text: 'Profile updated successfully' })
      setEditNotice({ kind: 'ok', text: 'Saved!' })
      setEditingProfile(false)
      setTimeout(() => setNotice(null), 2500)
    } catch (err: any) {
      setEditNotice({ kind: 'error', text: err?.response?.data?.detail || 'Could not save your details' })
    } finally {
      setSavingProfile(false)
    }
  }

  useEffect(() => {
    // Notifications come from the shared store (same 10s poller as the navbar
    // bell) so we don't double-fetch the endpoint.
    return subscribeNotifications(setNotifications)
  }, [])

  const load = useCallback(() => {
    Promise.all([
      api.get<LocalParentOrder[]>('/local/orders/parent'),
      api.get<LocalTicket[]>('/local/tickets'),
    ]).then(([o, t]) => { setOrders(cur => same(cur, o.data) ? cur : o.data); setTickets(cur => same(cur, t.data) ? cur : t.data) })
      .catch(() => setNotice({ kind: 'error', text: 'Could not load your data — check your network and try again.' }))
  }, [])

  // Poll every 10s while this tab is visible; background tabs pause and refresh
  // instantly when you switch back.
  usePolling(load, 10000, [load])

  // The backend returns account-owned orders; never guess ownership by contact details.
  const myOrders = orders
  const [orderSearch, setOrderSearch] = useState('')
  const [orderFilter, setOrderFilter] = useState('all')
  const history = myOrders.filter(o => (orderFilter === 'all' || orderGroup(o.status) === orderFilter)
    && `${o.token} ${o.status} ${(o.sub_orders || []).map(s => s.shop_name).join(' ')}`.toLowerCase().includes(orderSearch.trim().toLowerCase()))
  const active = myOrders.filter(o => orderGroup(o.status) === 'active')
  const completed = myOrders.filter(o => orderGroup(o.status) === 'completed')
  const total = completed.reduce((s, o) => s + o.total, 0)
  const myTickets = session?.email ? tickets.filter(t => t.email.toLowerCase() === session.email!.toLowerCase()) : tickets

  const cancelOrder = async (orderId: string) => {
    if (!confirm('Cancel this order? This cannot be undone.')) return
    try {
      const r = await api.patch<LocalParentOrder>(`/local/orders/${orderId}/cancel`)
      setOrders(curr => curr.map(o => o.id === orderId ? r.data : o))
      setNotice({ kind: 'ok', text: 'Order cancelled successfully' })
    } catch (err: any) {
      setNotice({ kind: 'error', text: err?.response?.data?.detail || 'Cannot cancel this order' })
    }
  }

  const cancelled = myOrders.filter(o => o.status === 'Cancelled')

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-6xl px-4 py-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-primary-dark">My Orders</h1>
          <p className="mt-1 text-sm font-medium text-gray-500">{session?.name || session?.email || 'Student'}</p>
        </div>

        {notice && (
          <div className={`mb-4 rounded-btn px-4 py-3 text-sm font-medium border ${notice.kind === 'error' ? 'bg-red-50 text-red-600 border-red-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'}`}>
            {notice.text}
            <button onClick={() => setNotice(null)} className="ml-2 font-bold">✕</button>
          </div>
        )}

        {/* Testing notice */}
        <Link to="/feedback"
          className="group mb-6 flex flex-col gap-3 rounded-card border border-gold-light/60 bg-gradient-to-r from-amber-50 via-white to-emerald-50 p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover sm:flex-row sm:items-center">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-card bg-gradient-to-br from-amber-400 to-orange-500 text-2xl shadow-lg shadow-amber-500/25 transition-transform group-hover:scale-110">🧪</span>
          <div className="min-w-0 flex-1">
            <p className="font-bold text-primary-dark">Help us test DETOMSITE — report bugs & ideas</p>
            <p className="mt-0.5 text-sm font-medium text-gray-500">Spotted something broken or have a suggestion?</p>
          </div>
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-primary px-4 py-2.5 text-sm font-bold text-white shadow-emerald-sm transition-colors group-hover:bg-primary-dark">
            Report now →
          </span>
        </Link>

        <div className="mb-6 grid gap-3 sm:grid-cols-4">
          {[['Total orders', myOrders.length], ['Completed value', `₹${total}`], ['Active', active.length], ['Completed', completed.length]].map(([l, v]) => (
            <div key={l} className="rounded-btn bg-white p-4 shadow-card"><p className="text-xs font-semibold text-gray-500">{l}</p><p className="mt-1 text-2xl font-bold text-primary-dark">{v}</p></div>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
          <div>
            {active.length > 0 && (
              <section className="mb-6">
                <h2 className="mb-3 text-lg font-bold text-primary">Active Orders</h2>
                <div className="space-y-3">
                  {active.map(order => (
                    <div key={order.id} className="rounded-btn bg-white p-4 shadow-card border border-primary-light/30">
                      <div className="mb-2 flex items-start justify-between">
                        <div><p className="text-xs font-semibold text-gray-500">Token</p><p className="text-3xl font-bold text-primary-dark">{order.token}</p></div>
                        <span className={`rounded-lg px-2.5 py-1 text-xs font-bold ${
                          order.status === 'Completed' ? 'bg-emerald-100 text-emerald-700' :
                          order.status === 'Delivered' ? 'bg-emerald-100 text-emerald-600' :
                          order.status === 'Confirmed' ? 'bg-gold-100 text-gold-800' :
                          order.status === 'Cancelled' ? 'bg-red-100 text-red-600' :
                          'bg-blue-100 text-blue-700'
                        }`}>{statusLabels[order.status] || order.status}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {order.sub_orders?.map(sub => (
                          <span className={`rounded-pill px-2.5 py-0.5 text-xs font-bold ${
                            sub.status === 'Delivered' || sub.status === 'Completed' ? 'bg-emerald-50 text-emerald-600' :
                            sub.status === 'Confirmed' ? 'bg-gold-100 text-gold-800' :
                            sub.status === 'Rejected' ? 'bg-red-50 text-red-600' :
                            'bg-sky-50 text-sky-600'
                          }`}>{subStatusLabels[sub.status] || sub.shop_name}</span>
                        ))}
                      </div>
                      <p className="mt-2 text-sm text-gray-500">{order.sub_orders?.map(s => s.items_summary).join(' + ')}</p>
                      <div className="mt-3 flex items-center justify-between text-sm">
                        <span className="font-medium text-primary">₹{order.total}</span>
                        <div className="flex gap-2">
                          <Link to={`/order-result/${order.id}`} className="font-semibold text-primary hover:text-primary">View →</Link>
                          {!['Completed', 'Cancelled', 'Delivered'].includes(order.status) && (
                            <button onClick={() => void cancelOrder(order.id)}
                              className="text-xs font-bold text-red-500 hover:text-red-600 ml-2">Cancel</button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {cancelled.length > 0 && (
              <section className="mb-6 rounded-btn bg-white shadow-card">
                <div className="border-b border-gray-100 px-4 py-3"><h2 className="text-lg font-bold text-primary">Cancelled</h2></div>
                <div className="divide-y divide-gray-50">
                  {cancelled.slice(0, 5).map(order => (
                    <div key={order.id} className="flex items-center justify-between px-4 py-3">
                      <div><p className="font-bold text-gray-600">Token {order.token}</p><p className="text-xs text-gray-400">{order.sub_orders?.map(s => s.shop_name).join(', ') || '—'}</p></div>
                      <span className="rounded-pill bg-red-50 px-2.5 py-1 text-xs font-bold text-red-600">Cancelled</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
            <section className="rounded-btn bg-white shadow-card">
              <div className="border-b border-gray-100 px-4 py-3">
                <h2 className="text-lg font-bold text-primary">Order History</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  <input aria-label="Search orders by token or shop" placeholder="Search token or shop" value={orderSearch} onChange={e => setOrderSearch(e.target.value)} className="rounded-lg border border-gray-200 p-2 text-sm" />
                  <select aria-label="Filter order history" value={orderFilter} onChange={e => setOrderFilter(e.target.value)} className="rounded-lg border border-gray-200 p-2 text-sm">
                    <option value="all">All orders</option><option value="active">Active</option><option value="completed">Completed</option><option value="cancelled">Cancelled / rejected</option>
                  </select>
                  <Link to="/shops" className="rounded-lg bg-primary px-3 py-2 text-sm font-bold text-white">Browse menu</Link>
                  <Link to="/support" className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-bold text-primary">Get help</Link>
                </div>
                {!history.length && <p className="mt-3 text-sm text-gray-500">No orders match your filters.</p>}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[600px] text-sm">
                  <thead className="bg-primary-light/30/50"><tr>{['Token', 'Shops', 'Items', 'Amount', 'Status'].map(h => <th key={h} className="px-4 py-3 text-left text-xs font-bold text-gray-500">{h}</th>)}</tr></thead>
                  <tbody>
                    {history.map(order => (
                      <tr key={order.id} className="border-t border-gray-50">
                        <td className="px-4 py-3 font-bold text-primary-dark">{order.token}</td>
                        <td className="px-4 py-3 font-medium text-gray-600">{order.sub_orders?.map(s => s.shop_name).join(', ') || '—'}</td>
                        <td className="px-4 py-3 text-gray-500">{order.sub_orders?.map(s => s.items_summary).join('; ') || '—'}</td>
                        <td className="px-4 py-3 font-semibold text-primary">₹{order.total}</td>
                        <td className="px-4 py-3"><span className={`rounded-lg px-2 py-0.5 text-xs font-bold ${
                          order.status === 'Completed' || order.status === 'Delivered' ? 'bg-emerald-50 text-emerald-600' :
                          order.status === 'Confirmed' ? 'bg-gold-100 text-gold-800' :
                          order.status === 'Cancelled' ? 'bg-red-50 text-red-600' :
                          'bg-gray-50 text-gray-500'
                        }`}>{statusLabels[order.status] || order.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <div>
            <section className="mb-4 rounded-btn bg-white p-4 shadow-card">
              <h2 className="mb-3 text-lg font-bold text-primary">Profile</h2>
              {editingProfile ? (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-bold text-gray-500">Full name</label>
                    <input
                      value={profileForm.name}
                      onChange={e => setProfileForm({ ...profileForm, name: e.target.value })}
                      className="w-full rounded-btn border border-gray-200 px-3 py-2 text-sm text-gray-800 outline-none focus:border-primary"
                      placeholder="Your full name"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-bold text-gray-500">Phone</label>
                    <input
                      value={profileForm.phone}
                      onChange={e => setProfileForm({ ...profileForm, phone: e.target.value })}
                      className="w-full rounded-btn border border-gray-200 px-3 py-2 text-sm text-gray-800 outline-none focus:border-primary"
                      placeholder="10-digit mobile number"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-bold text-gray-500">Email</label>
                    <input
                      value={profileForm.email}
                      onChange={e => setProfileForm({ ...profileForm, email: e.target.value })}
                      className="w-full rounded-btn border border-gray-200 px-3 py-2 text-sm text-gray-800 outline-none focus:border-primary"
                      placeholder="you@campus.local"
                    />
                  </div>
                  {editNotice && (
                    <p className={`text-xs font-semibold ${editNotice.kind === 'ok' ? 'text-emerald-600' : 'text-red-600'}`}>
                      {editNotice.text}
                    </p>
                  )}
                  <div className="flex gap-2">
                    <button onClick={() => void saveProfile()}
                      disabled={savingProfile}
                      className="flex-1 rounded-btn bg-primary px-3 py-2 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-50">
                      {savingProfile ? 'Saving...' : 'Save changes'}
                    </button>
                    <button onClick={() => { setEditingProfile(false); setEditNotice(null) }}
                      className="rounded-btn border border-gray-200 px-3 py-2 text-sm font-bold text-gray-500 hover:bg-gray-50">
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-1 text-sm text-gray-500">
                  <p><span className="font-medium text-gray-700">Name:</span> {session?.name || '—'}</p>
                  <p><span className="font-medium text-gray-700">Phone:</span> {profilePhone || '—'}</p>
                  <p><span className="font-medium text-gray-700">Email:</span> {session?.email || '—'}</p>
                  <button onClick={startEditProfile}
                    className="mt-2 inline-flex items-center gap-1 rounded-btn bg-gold-light/60 px-3 py-1.5 text-xs font-bold text-gold-800 transition-colors hover:bg-gold-light">
                    ✏️ Edit details
                  </button>
                </div>
              )}
            </section>
            <section className="mb-4 rounded-btn bg-white p-4 shadow-card">
              <h2 className="mb-3 text-lg font-bold text-primary">Notifications</h2>
              <div className="space-y-2">
                {notifications.slice(0, 5).map(n => (
                  <Link key={n.id} to={n.order_id ? `/order-result/${n.order_id}` : '#'} className="block rounded-lg bg-primary-light/30/50 px-3 py-2.5 transition-colors hover:bg-primary-light/30">
                    <p className="text-sm font-semibold text-primary">{n.title}</p>
                    <p className="text-xs font-medium text-gray-500">{n.message}</p>
                  </Link>
                ))}
                {notifications.length === 0 && <p className="text-sm text-gray-400">No notifications</p>}
              </div>
            </section>
            <section className="rounded-btn bg-white p-4 shadow-card">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-bold text-primary">Support</h2>
                <Link to="/support" className="text-sm font-semibold text-primary hover:text-primary">New ticket</Link>
              </div>
              <div className="space-y-2">
                {myTickets.slice(0, 3).map(t => (
                  <div key={t.id} className="rounded-lg bg-primary-light/30/50 px-3 py-2.5">
                    <p className="text-sm font-semibold text-primary">{t.title}</p>
                    <p className="text-xs font-medium text-gray-500">{t.ticket_number} · {t.status}</p>
                  </div>
                ))}
                {myTickets.length === 0 && <p className="text-sm text-gray-400">No tickets</p>}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}
