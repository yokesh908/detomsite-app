import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import { LocalAnnouncement, LocalShop, LocalSubOrder } from '../../types/localApi'
import { getLocalSession } from '../../utils/session'

export function ShopkeeperDashboard() {
  const [shops, setShops] = useState<LocalShop[]>([])
  const [subOrders, setSubOrders] = useState<LocalSubOrder[]>([])
  const [announcements, setAnnouncements] = useState<LocalAnnouncement[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [tab, setTab] = useState<'orders' | 'announcements'>('orders')
  const [newAnnouncement, setNewAnnouncement] = useState('')
  const session = getLocalSession()

  const shop = shops.find(s => s.shopkeeper_email?.toLowerCase() === session?.email?.toLowerCase()) || shops[0]

  const load = async () => {
    setLoading(true)
    try {
      const [s, o, a] = await Promise.all([
        api.get<LocalShop[]>('/local/shops'),
        shop ? api.get<LocalSubOrder[]>(`/local/shop-orders/${shop.id}`) : Promise.resolve({ data: [] }),
        api.get<LocalAnnouncement[]>('/local/announcements'),
      ])
      setShops(s.data); setSubOrders(o.data); setAnnouncements(a.data)
    } catch { setMessage('Backend not reachable') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load(); const i = window.setInterval(load, 8000); return () => window.clearInterval(i) }, [shop?.id])

  const pending = subOrders.filter(o => o.status === 'Pending')
  const active = subOrders.filter(o => ['Accepted', 'Preparing', 'Ready'].includes(o.status))
  const done = subOrders.filter(o => ['Delivered', 'Completed', 'Cancelled', 'Rejected'].includes(o.status))

  const myAnnouncements = announcements.filter(a => shop && a.shop_id === shop.id)

  const setStatus = async (id: string, status: string, notes = '') => {
    const r = await api.patch<LocalSubOrder>(`/local/shop-orders/${id}/status`, { status, notes })
    setSubOrders(curr => curr.map(o => o.id === id ? r.data : o))
    setMessage(`Sub-order ${status.toLowerCase()}`)
    void load()
  }

  const togglePresent = async (present: boolean) => {
    if (!shop) return
    if (shop.approval_status !== 'Approved') { setMessage('Admin approval required'); return }
    const r = await api.patch<LocalShop>(`/local/shops/${shop.id}`, { present })
    setShops(curr => curr.map(s => s.id === shop.id ? r.data : s))
    setMessage(present ? 'Accepting orders' : 'Not accepting')
  }

  const postAnnouncement = async () => {
    if (!shop || !newAnnouncement.trim()) return
    await api.post('/local/announcements', { shop_id: shop.id, message: newAnnouncement.trim() })
    setNewAnnouncement('')
    setMessage('Announcement posted')
    void load()
  }

  const toggleAnnouncement = async (id: string, isActive: boolean) => {
    await api.patch(`/local/announcements/${id}`, { is_active: isActive ? 1 : 0 })
    setMessage(isActive ? 'Announcement activated' : 'Announcement deactivated')
    void load()
  }

  if (loading) return <div className="flex min-h-screen items-center justify-center bg-white text-gray-400">Loading...</div>
  if (!shop) return <div className="flex min-h-screen items-center justify-center bg-white text-gray-600 font-semibold">No shop found. <Link to="/vendor/register" className="ml-1 text-primary">Register one</Link></div>

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Full-screen header bar */}
      <div className="sticky top-0 z-30 bg-white shadow-sm border-b border-gray-100">
        <div className="mx-auto flex max-w-[1800px] items-center justify-between px-4 py-3">
          <div>
            <h1 className="text-xl font-bold text-primary-dark">{shop.name}</h1>
            <p className="text-xs font-semibold text-gray-400">{shop.category} · {shop.rating.toFixed(1)} ★</p>
          </div>
          <div className="flex items-center gap-3">
            {message && <span className="text-xs font-bold text-primary">{message}</span>}
            <label className="flex items-center gap-2 rounded-pill border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 cursor-pointer">
              <input type="checkbox" checked={Boolean(shop.present)} onChange={e => void togglePresent(e.target.checked)}
                disabled={shop.approval_status !== 'Approved'} className="h-4 w-4 accent-emerald-600" />
              {shop.present ? 'Accepting' : 'Closed'}
            </label>
            <Link to="/shops" className="rounded-pill border border-gray-200 bg-white px-4 py-2 text-xs font-bold text-gray-600">Student view</Link>
          </div>
        </div>
      </div>

      {shop.approval_status !== 'Approved' && (
        <div className="mx-auto max-w-[1800px] px-4 pt-4">
          <div className="rounded-btn bg-gold-50 border border-gold-200 px-4 py-3">
            <p className="text-sm font-semibold text-gold-700">⏳ Your shop is <strong>Pending Approval</strong>. Hidden from students until approved.</p>
          </div>
        </div>
      )}

      <div className="mx-auto max-w-[1800px] px-4 py-6">
        {/* Tab bar */}
        <div className="mb-6 flex gap-2 border-b border-gray-100 pb-px">
          {[
            { id: 'orders' as const, label: 'Orders', count: pending.length + active.length },
            { id: 'announcements' as const, label: 'Announcements', count: myAnnouncements.filter(a => a.is_active).length },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-5 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px ${
                tab === t.id ? 'border-emerald-600 text-primary' : 'border-transparent text-gray-400 hover:text-gray-600'
              }`}>{t.label}{t.count ? ` (${t.count})` : ''}</button>
          ))}
        </div>

        {tab === 'orders' && (
          <>
            {/* Stats bar */}
            <div className="mb-6 flex flex-wrap gap-3">
              {[['Revenue', `₹${shop.revenue_today}`], ['Orders today', shop.orders_today], ['Pending', pending.length], ['Active', active.length], ['Done today', done.length]].map(([l, v]) => (
                <div key={l} className="rounded-pill bg-white border border-gray-100 px-4 py-2.5 text-sm shadow-sm">
                  <span className="text-gray-500">{l}:</span>
                  <span className="ml-1.5 font-bold text-primary-dark">{v}</span>
                </div>
              ))}
            </div>

            {/* Three-column order board */}
            <div className="grid gap-5 lg:grid-cols-3">
              {/* Pending */}
              <section className="rounded-[24px] bg-white border border-amber-200 shadow-sm">
                <div className="rounded-t-[24px] bg-amber-50 px-4 py-3 border-b border-amber-100">
                  <h2 className="text-lg font-bold text-amber-800">Pending ({pending.length})</h2>
                </div>
                <div className="space-y-3 p-3 max-h-[70vh] overflow-y-auto">
                  {pending.map(sub => (
                    <div key={sub.id} className="rounded-card border border-amber-200 bg-amber-50/30 p-4">
                      <div className="mb-2 flex items-start justify-between">
                        <span className="text-xl font-bold text-primary-dark">Token {sub.token}</span>
                        <span className="rounded-pill bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-700">{sub.batch_type}</span>
                      </div>
                      <p className="text-sm font-bold text-primary-dark">{sub.items_summary}</p>
                      <p className="mt-1 text-lg font-bold text-primary">₹{sub.subtotal}</p>
                      <div className="mt-2 rounded-lg bg-white border border-primary-light/30 p-3">
                        <p className="text-xs text-gray-500">Student</p>
                        <p className="text-sm font-bold text-primary-dark">{sub.parent?.student_name || '—'}</p>
                        {sub.parent?.student_phone && (
                          <div className="mt-1 flex flex-wrap gap-2">
                            <a href={`tel:${sub.parent.student_phone}`}
                              className="inline-flex items-center gap-1.5 text-sm font-bold text-emerald-600 hover:text-emerald-700">
                              📞 {sub.parent.student_phone}
                            </a>
                            <a target="_blank" rel="noreferrer"
                              href={`https://wa.me/${sub.parent.student_phone.replace(/[^0-9]/g, '')}`}
                              className="inline-flex items-center gap-1.5 rounded-pill bg-emerald-500 px-2.5 py-0.5 text-xs font-bold text-white hover:bg-emerald-600">
                              💬 WhatsApp
                            </a>
                          </div>
                        )}
                      </div>
                      <p className="mt-1.5 text-xs text-gray-400">📍 {sub.parent?.delivery_location || '—'}</p>
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        <button onClick={() => void setStatus(sub.id, 'Accepted')}
                          className="rounded-pill bg-primary px-3 py-2 text-sm font-bold text-white shadow-sm transition-colors hover:bg-primary-dark">
                          Accept
                        </button>
                        <button onClick={() => void setStatus(sub.id, 'Rejected')}
                          className="rounded-pill border border-red-200 bg-white px-3 py-2 text-sm font-bold text-red-600 hover:bg-red-50">
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}
                  {pending.length === 0 && <p className="py-8 text-center text-sm text-gray-400">No pending orders</p>}
                </div>
              </section>

              {/* Active */}
              <section className="rounded-[24px] bg-white border border-blue-200 shadow-sm">
                <div className="rounded-t-[24px] bg-blue-50 px-4 py-3 border-b border-blue-100">
                  <h2 className="text-lg font-bold text-blue-800">Active ({active.length})</h2>
                </div>
                <div className="space-y-3 p-3 max-h-[70vh] overflow-y-auto">
                  {active.map(sub => {
                    const statusColor: Record<string, string> = {
                      Accepted: 'bg-blue-100 text-blue-700',
                      Preparing: 'bg-amber-100 text-amber-700',
                      Ready: 'bg-emerald-100 text-emerald-700',
                    }
                    return (
                      <div key={sub.id} className="rounded-card border border-gray-100 bg-gray-50/50 p-4">
                        <div className="mb-2 flex items-start justify-between">
                          <span className="text-xl font-bold text-primary-dark">Token {sub.token}</span>
                          <span className={`rounded-pill px-2 py-0.5 text-xs font-bold ${statusColor[sub.status] || 'bg-gray-100 text-gray-600'}`}>{sub.status}</span>
                        </div>
                        <p className="text-sm font-bold text-primary-dark">{sub.items_summary}</p>
                        <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                          <span>{sub.parent?.student_name || '—'}</span>
                          {sub.parent?.student_phone && (
                            <>
                              <a href={`tel:${sub.parent.student_phone}`}
                                className="inline-flex items-center gap-1 font-bold text-emerald-600">
                                📞 {sub.parent.student_phone}
                              </a>
                              <a target="_blank" rel="noreferrer"
                                href={`https://wa.me/${sub.parent.student_phone.replace(/[^0-9]/g, '')}`}
                                className="inline-flex items-center gap-1 rounded-pill bg-emerald-500 px-2 py-0.5 text-xs font-bold text-white">
                                💬
                              </a>
                            </>
                          )}
                        </div>
                        <div className="mt-3 grid grid-cols-3 gap-2">
                          {sub.status === 'Accepted' && (
                            <button onClick={() => void setStatus(sub.id, 'Preparing')}
                              className="rounded-pill bg-amber-500 px-2 py-2 text-xs font-bold text-white shadow-sm">Start Prep</button>
                          )}
                          {sub.status === 'Preparing' && (
                            <button onClick={() => void setStatus(sub.id, 'Ready')}
                              className="rounded-pill bg-gold px-2 py-2 text-xs font-bold text-white shadow-sm">Ready</button>
                          )}
                          {sub.status === 'Ready' && (
                            <button onClick={() => void setStatus(sub.id, 'Delivered')}
                              className="rounded-pill bg-emerald-500 px-2 py-2 text-xs font-bold text-white shadow-sm">Delivered</button>
                          )}
                          {sub.status === 'Accepted' && (
                            <button onClick={() => void setStatus(sub.id, 'Completed')}
                              className="col-span-2 rounded-pill border border-emerald-300 bg-white px-2 py-2 text-xs font-bold text-primary">
                              Skip to Done
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                  {active.length === 0 && <p className="py-8 text-center text-sm text-gray-400">No active orders</p>}
                </div>
              </section>

              {/* Completed / Cancelled */}
              <section className="rounded-[24px] bg-white border border-gray-200 shadow-sm">
                <div className="rounded-t-[24px] bg-gray-50 px-4 py-3 border-b border-gray-100">
                  <h2 className="text-lg font-bold text-gray-700">Done today ({done.length})</h2>
                </div>
                <div className="space-y-2 p-3 max-h-[70vh] overflow-y-auto">
                  {done.slice(0, 30).map(sub => (
                    <div key={sub.id} className="flex items-center justify-between rounded-pill bg-gray-50 px-3 py-2">
                      <div>
                        <span className="font-bold text-primary-dark">Token {sub.token}</span>
                        <span className="ml-2 text-xs text-gray-500">{sub.parent?.student_name || '—'}</span>
                      </div>
                      <span className={`rounded-pill px-2 py-0.5 text-xs font-bold ${
                        sub.status === 'Delivered' || sub.status === 'Completed' ? 'bg-emerald-50 text-emerald-600' :
                        sub.status === 'Cancelled' || sub.status === 'Rejected' ? 'bg-red-50 text-red-600' :
                        'bg-gray-100 text-gray-500'
                      }`}>{sub.status}</span>
                    </div>
                  ))}
                  {done.length === 0 && <p className="py-8 text-center text-sm text-gray-400">No completed orders yet today</p>}
                </div>
              </section>
            </div>
          </>
        )}

        {tab === 'announcements' && (
          <div className="max-w-3xl space-y-6">
            {/* Post new */}
            <section className="rounded-btn bg-white p-5 shadow-card">
              <h2 className="mb-3 text-lg font-bold text-primary">Post Announcement</h2>
              <p className="mb-3 text-xs text-gray-500">This message appears on the student-facing shop page as a notification bar.</p>
              <textarea
                value={newAnnouncement}
                onChange={e => setNewAnnouncement(e.target.value)}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-3 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm"
                placeholder="e.g. Out of biryani today, but special fried rice available!"
                rows={3}
              />
              <div className="mt-3 flex justify-end">
                <button
                  onClick={() => void postAnnouncement()}
                  disabled={!newAnnouncement.trim()}
                  className="rounded-pill bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark disabled:opacity-50"
                >
                  Post to Students
                </button>
              </div>
            </section>

            {/* Existing announcements */}
            <section className="rounded-btn bg-white p-5 shadow-card">
              <h2 className="mb-3 text-lg font-bold text-primary">Your Announcements ({myAnnouncements.length})</h2>
              <div className="space-y-3">
                {myAnnouncements.map(a => (
                  <div key={a.id} className="rounded-btn border border-gray-100 bg-gray-50/50 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-primary-dark">{a.message}</p>
                        <p className="mt-1 text-xs text-gray-400">{a.created_at?.slice(0, 16)}</p>
                      </div>
                      <label className="flex shrink-0 items-center gap-2 cursor-pointer">
                        <span className="text-xs font-semibold text-gray-500">{a.is_active ? 'Active' : 'Off'}</span>
                        <input
                          type="checkbox"
                          checked={Boolean(a.is_active)}
                          onChange={e => void toggleAnnouncement(a.id, e.target.checked)}
                          className="h-4 w-4 accent-emerald-600"
                        />
                      </label>
                    </div>
                  </div>
                ))}
                {myAnnouncements.length === 0 && <p className="text-sm text-gray-400">No announcements yet. Post one above to notify students!</p>}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
