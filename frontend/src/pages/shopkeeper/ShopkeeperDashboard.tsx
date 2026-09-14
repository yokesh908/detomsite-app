import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import { LocalAnnouncement, LocalShop, LocalSubOrder } from '../../types/localApi'
import { getLocalSession } from '../../utils/session'
import { usePolling } from '../../hooks/usePolling'
import { same } from '../../utils/same'

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

  const load = useCallback(async () => {
    try {
      const [s, o, a] = await Promise.all([
        api.get<LocalShop[]>('/local/shops'),
        shop ? api.get<LocalSubOrder[]>(`/local/shop-orders/${shop.id}`) : Promise.resolve({ data: [] }),
        api.get<LocalAnnouncement[]>('/local/announcements'),
      ])
      setShops(cur => same(cur, s.data) ? cur : s.data)
      setSubOrders(cur => same(cur, o.data) ? cur : o.data)
      setAnnouncements(cur => same(cur, a.data) ? cur : a.data)
    } catch { setMessage('Backend not reachable') }
    finally { setLoading(false) }
  }, [shop?.id])

  // Live-update every 10s, but only while this tab is visible — background
  // tabs stop hitting the API, and the screen refreshes the moment you focus
  // back.
  usePolling(load, 10000, [shop?.id])

  const pending = subOrders.filter(o => o.status === 'Pending')
  const active = subOrders.filter(o => ['Accepted', 'Preparing', 'Ready'].includes(o.status))
  const done = subOrders.filter(o => ['Delivered', 'Completed', 'Cancelled', 'Rejected'].includes(o.status))
  const myAnnouncements = announcements.filter(a => shop && a.shop_id === shop.id)

  const setStatus = async (id: string, status: string, notes = '') => {
    const r = await api.patch<LocalSubOrder>(`/local/shop-orders/${id}/status`, { status, notes })
    setSubOrders(curr => curr.map(o => o.id === id ? r.data : o))
    setMessage(`Order ${status.toLowerCase()}`)
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
    const r = await api.post<LocalAnnouncement>('/local/announcements', { shop_id: shop.id, message: newAnnouncement.trim() })
    setNewAnnouncement('')
    setAnnouncements(curr => same(curr, [r.data, ...curr]) ? curr : [r.data, ...curr])
    setMessage('Announcement posted')
  }

  const toggleAnnouncement = async (id: string, isActive: boolean) => {
    const r = await api.patch<LocalAnnouncement>(`/local/announcements/${id}`, { is_active: isActive ? 1 : 0 })
    setAnnouncements(curr => curr.map(a => a.id === id ? r.data : a))
    setMessage(isActive ? 'Announcement activated' : 'Announcement deactivated')
  }

  if (loading) return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-emerald-200 border-t-emerald-600" />
    </div>
  )
  if (!shop) return (
    <div className="flex min-h-screen items-center justify-center bg-white px-6 text-center">
      <div>
        <p className="text-lg font-semibold text-gray-600">No shop found.</p>
        <Link to="/vendor/register" className="mt-3 inline-block rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white">Register a Shop</Link>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Sticky header */}
      <div className="sticky top-0 z-30 bg-white shadow-sm border-b border-gray-100">
        <div className="mx-auto flex max-w-[1800px] items-center justify-between px-3 py-2.5 sm:px-4 sm:py-3">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-bold text-primary-dark sm:text-xl">{shop.name}</h1>
            <p className="text-xs font-semibold text-gray-400">{shop.category} · {shop.rating.toFixed(1)} ★</p>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            {message && <span className="hidden text-xs font-bold text-primary sm:inline">{message}</span>}
            <label className="flex items-center gap-1.5 rounded-pill border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-gray-700 cursor-pointer sm:px-4 sm:py-2 sm:text-sm">
              <input type="checkbox" checked={Boolean(shop.present)} onChange={e => void togglePresent(e.target.checked)}
                disabled={shop.approval_status !== 'Approved'} className="h-3.5 w-3.5 accent-emerald-600 sm:h-4 sm:w-4" />
              {shop.present ? 'Open' : 'Closed'}
            </label>
            <Link to="/shops" className="hidden rounded-pill border border-gray-200 bg-white px-3 py-1.5 text-xs font-bold text-gray-600 sm:block sm:px-4 sm:py-2">Student view</Link>
          </div>
        </div>
        {message && <p className="px-3 pb-2 text-xs font-bold text-primary sm:hidden">{message}</p>}
      </div>

      {shop.approval_status !== 'Approved' && (
        <div className="mx-auto max-w-[1800px] px-3 pt-3 sm:px-4 sm:pt-4">
          <div className="rounded-btn bg-amber-50 border border-amber-200 px-3 py-2.5 sm:px-4 sm:py-3">
            <p className="text-xs font-semibold text-amber-700 sm:text-sm">⏳ Pending Approval — Hidden from students until approved.</p>
          </div>
        </div>
      )}

      <div className="mx-auto max-w-[1800px] px-3 py-4 sm:px-4 sm:py-6">
        {/* Tab bar */}
        <div className="mb-4 flex gap-1 border-b border-gray-100 pb-px sm:mb-6 sm:gap-2">
          {[
            { id: 'orders' as const, label: 'Orders', count: pending.length + active.length },
            { id: 'announcements' as const, label: 'Announcements', count: myAnnouncements.filter(a => a.is_active).length },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-xs font-semibold transition-colors border-b-2 -mb-px sm:px-5 sm:text-sm ${
                tab === t.id ? 'border-emerald-600 text-primary' : 'border-transparent text-gray-400 hover:text-gray-600'
              }`}>{t.label}{t.count ? ` (${t.count})` : ''}</button>
          ))}
        </div>

        {tab === 'orders' && (
          <>
            {/* Stats bar */}
            <div className="mb-4 flex flex-wrap gap-2 sm:mb-6 sm:gap-3">
              {[['Revenue', `₹${shop.revenue_today}`], ['Today', shop.orders_today], ['Pending', pending.length], ['Active', active.length], ['Done', done.length]].map(([l, v]) => (
                <div key={l} className="rounded-pill bg-white border border-gray-100 px-2.5 py-1.5 text-xs shadow-sm sm:px-4 sm:py-2.5 sm:text-sm">
                  <span className="text-gray-500">{l}</span>
                  <span className="ml-1 font-bold text-primary-dark">{v}</span>
                </div>
              ))}
            </div>

            {/* Mobile: single column / Desktop: three columns */}
            <div className="grid gap-4 sm:gap-5 grid-cols-1 lg:grid-cols-3">
              {/* Pending */}
              <section className="rounded-[20px] bg-white border border-amber-200 shadow-sm sm:rounded-[24px]">
                <div className="rounded-t-[20px] bg-amber-50 px-3 py-2.5 border-b border-amber-100 sm:rounded-t-[24px] sm:px-4 sm:py-3">
                  <h2 className="text-base font-bold text-amber-800 sm:text-lg">Pending ({pending.length})</h2>
                </div>
                <div className="space-y-2.5 p-2.5 sm:space-y-3 sm:p-3 max-h-[50vh] overflow-y-auto sm:max-h-[70vh]">
                  {pending.map(sub => (
                    <div key={sub.id} className="rounded-xl border border-amber-200 bg-amber-50/30 p-3 sm:rounded-card sm:p-4">
                      <div className="mb-1.5 flex items-start justify-between sm:mb-2">
                        <span className="text-lg font-bold text-primary-dark sm:text-xl">Token {sub.token}</span>
                        <span className="rounded-pill bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700 sm:text-xs">{sub.batch_type}</span>
                      </div>
                      <p className="text-xs font-bold text-primary-dark sm:text-sm">{sub.items_summary}</p>
                      <p className="mt-0.5 text-base font-bold text-primary sm:text-lg">₹{sub.subtotal}</p>
                      <div className="mt-2 rounded-lg bg-white border border-primary-light/30 p-2.5 sm:p-3">
                        <p className="text-[10px] text-gray-500 sm:text-xs">Student</p>
                        <p className="text-xs font-bold text-primary-dark sm:text-sm">{sub.parent?.student_name || '—'}</p>
                        {sub.parent?.student_phone && (
                          <div className="mt-1 flex flex-wrap gap-1.5 sm:gap-2">
                            <a href={`tel:${sub.parent.student_phone}`}
                              className="inline-flex items-center gap-1 text-xs font-bold text-emerald-600 hover:text-emerald-700 sm:text-sm">
                              📞 {sub.parent.student_phone}
                            </a>
                            <a target="_blank" rel="noreferrer"
                              href={`https://wa.me/${sub.parent.student_phone.replace(/[^0-9]/g, '')}`}
                              className="inline-flex items-center gap-1 rounded-pill bg-emerald-500 px-2 py-0.5 text-[10px] font-bold text-white hover:bg-emerald-600 sm:text-xs">
                              💬 WhatsApp
                            </a>
                          </div>
                        )}
                      </div>
                      <p className="mt-1 text-[10px] text-gray-400 sm:text-xs">📍 {sub.parent?.delivery_location || '—'}</p>
                      <div className="mt-2.5 grid grid-cols-2 gap-2 sm:mt-3">
                        <button onClick={() => void setStatus(sub.id, 'Accepted')}
                          className="rounded-pill bg-primary px-3 py-2 text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary-dark sm:text-sm">
                          Accept
                        </button>
                        <button onClick={() => void setStatus(sub.id, 'Rejected')}
                          className="rounded-pill border border-red-200 bg-white px-3 py-2 text-xs font-bold text-red-600 hover:bg-red-50">
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}
                  {pending.length === 0 && <p className="py-6 text-center text-xs text-gray-400 sm:py-8 sm:text-sm">No pending orders</p>}
                </div>
              </section>

              {/* Active */}
              <section className="rounded-[20px] bg-white border border-blue-200 shadow-sm sm:rounded-[24px]">
                <div className="rounded-t-[20px] bg-blue-50 px-3 py-2.5 border-b border-blue-100 sm:rounded-t-[24px] sm:px-4 sm:py-3">
                  <h2 className="text-base font-bold text-blue-800 sm:text-lg">Active ({active.length})</h2>
                </div>
                <div className="space-y-2.5 p-2.5 sm:space-y-3 sm:p-3 max-h-[50vh] overflow-y-auto sm:max-h-[70vh]">
                  {active.map(sub => {
                    const statusColor: Record<string, string> = {
                      Accepted: 'bg-blue-100 text-blue-700',
                      Preparing: 'bg-amber-100 text-amber-700',
                      Ready: 'bg-emerald-100 text-emerald-700',
                    }
                    return (
                      <div key={sub.id} className="rounded-xl border border-gray-100 bg-gray-50/50 p-3 sm:rounded-card sm:p-4">
                        <div className="mb-1.5 flex items-start justify-between sm:mb-2">
                          <span className="text-lg font-bold text-primary-dark sm:text-xl">Token {sub.token}</span>
                          <span className={`rounded-pill px-2 py-0.5 text-[10px] font-bold ${statusColor[sub.status] || 'bg-gray-100 text-gray-600'} sm:text-xs`}>{sub.status}</span>
                        </div>
                        <p className="text-xs font-bold text-primary-dark sm:text-sm">{sub.items_summary}</p>
                        <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-gray-500 sm:mt-2 sm:gap-2 sm:text-xs">
                          <span>{sub.parent?.student_name || '—'}</span>
                          {sub.parent?.student_phone && (
                            <>
                              <a href={`tel:${sub.parent.student_phone}`}
                                className="inline-flex items-center gap-0.5 font-bold text-emerald-600">
                                📞 {sub.parent.student_phone}
                              </a>
                              <a target="_blank" rel="noreferrer"
                                href={`https://wa.me/${sub.parent.student_phone.replace(/[^0-9]/g, '')}`}
                                className="inline-flex items-center gap-0.5 rounded-pill bg-emerald-500 px-1.5 py-0.5 text-[10px] font-bold text-white sm:text-xs">
                                💬
                              </a>
                            </>
                          )}
                        </div>
                        <div className="mt-2.5 grid grid-cols-3 gap-1.5 sm:mt-3 sm:gap-2">
                          {sub.status === 'Accepted' && (
                            <button onClick={() => void setStatus(sub.id, 'Preparing')}
                              className="rounded-pill bg-amber-500 px-2 py-1.5 text-[10px] font-bold text-white shadow-sm sm:text-xs">Start Prep</button>
                          )}
                          {sub.status === 'Preparing' && (
                            <button onClick={() => void setStatus(sub.id, 'Ready')}
                              className="rounded-pill bg-gold px-2 py-1.5 text-[10px] font-bold text-white shadow-sm sm:text-xs">Ready</button>
                          )}
                          {sub.status === 'Ready' && (
                            <button onClick={() => void setStatus(sub.id, 'Delivered')}
                              className="rounded-pill bg-emerald-500 px-2 py-1.5 text-[10px] font-bold text-white shadow-sm sm:text-xs">Delivered</button>
                          )}
                          {sub.status === 'Accepted' && (
                            <button onClick={() => void setStatus(sub.id, 'Completed')}
                              className="col-span-3 rounded-pill border border-emerald-300 bg-white px-2 py-1.5 text-[10px] font-bold text-primary sm:col-span-2 sm:text-xs">
                              Skip to Done
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                  {active.length === 0 && <p className="py-6 text-center text-xs text-gray-400 sm:py-8 sm:text-sm">No active orders</p>}
                </div>
              </section>

              {/* Completed */}
              <section className="rounded-[20px] bg-white border border-gray-200 shadow-sm sm:rounded-[24px]">
                <div className="rounded-t-[20px] bg-gray-50 px-3 py-2.5 border-b border-gray-100 sm:rounded-t-[24px] sm:px-4 sm:py-3">
                  <h2 className="text-base font-bold text-gray-700 sm:text-lg">Done ({done.length})</h2>
                </div>
                <div className="space-y-1.5 p-2.5 sm:space-y-2 sm:p-3 max-h-[50vh] overflow-y-auto sm:max-h-[70vh]">
                  {done.slice(0, 30).map(sub => (
                    <div key={sub.id} className="flex items-center justify-between rounded-pill bg-gray-50 px-2.5 py-1.5 sm:px-3 sm:py-2">
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-bold text-primary-dark sm:text-sm">Token {sub.token}</span>
                        <span className="ml-1 text-[10px] text-gray-500 sm:text-xs">{sub.parent?.student_name || '—'}</span>
                      </div>
                      <span className={`ml-2 shrink-0 rounded-pill px-1.5 py-0.5 text-[10px] font-bold sm:px-2 sm:text-xs ${
                        sub.status === 'Delivered' || sub.status === 'Completed' ? 'bg-emerald-50 text-emerald-600' :
                        sub.status === 'Cancelled' || sub.status === 'Rejected' ? 'bg-red-50 text-red-600' :
                        'bg-gray-100 text-gray-500'
                      }`}>{sub.status}</span>
                    </div>
                  ))}
                  {done.length === 0 && <p className="py-6 text-center text-xs text-gray-400 sm:py-8 sm:text-sm">No completed orders yet</p>}
                </div>
              </section>
            </div>
          </>
        )}

        {tab === 'announcements' && (
          <div className="max-w-3xl space-y-4 sm:space-y-6">
            <section className="rounded-btn bg-white p-4 shadow-card sm:p-5">
              <h2 className="mb-2 text-base font-bold text-primary sm:text-lg">Post Announcement</h2>
              <p className="mb-2 text-[10px] text-gray-500 sm:text-xs">Appears on the student-facing shop page.</p>
              <textarea
                value={newAnnouncement}
                onChange={e => setNewAnnouncement(e.target.value)}
                className="w-full rounded-btn border-2 border-gray-200 px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-primary sm:px-4 sm:py-3"
                placeholder="e.g. Out of biryani today, but special fried rice available!"
                rows={3}
              />
              <div className="mt-2.5 flex justify-end sm:mt-3">
                <button
                  onClick={() => void postAnnouncement()}
                  disabled={!newAnnouncement.trim()}
                  className="rounded-pill bg-primary px-4 py-2 text-xs font-bold text-white shadow-gold-sm hover:bg-primary-dark disabled:opacity-50 sm:px-5 sm:py-2.5 sm:text-sm"
                >
                  Post to Students
                </button>
              </div>
            </section>

            <section className="rounded-btn bg-white p-4 shadow-card sm:p-5">
              <h2 className="mb-2 text-base font-bold text-primary sm:text-lg">Your Announcements ({myAnnouncements.length})</h2>
              <div className="space-y-2 sm:space-y-3">
                {myAnnouncements.map(a => (
                  <div key={a.id} className="rounded-btn border border-gray-100 bg-gray-50/50 p-3 sm:p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold text-primary-dark sm:text-sm">{a.message}</p>
                        <p className="mt-0.5 text-[10px] text-gray-400 sm:text-xs">{a.created_at?.slice(0, 16)}</p>
                      </div>
                      <label className="flex shrink-0 items-center gap-1.5 cursor-pointer">
                        <span className="text-[10px] font-semibold text-gray-500 sm:text-xs">{a.is_active ? 'On' : 'Off'}</span>
                        <input
                          type="checkbox"
                          checked={Boolean(a.is_active)}
                          onChange={e => void toggleAnnouncement(a.id, e.target.checked)}
                          className="h-3.5 w-3.5 accent-emerald-600 sm:h-4 sm:w-4"
                        />
                      </label>
                    </div>
                  </div>
                ))}
                {myAnnouncements.length === 0 && <p className="text-xs text-gray-400 sm:text-sm">No announcements yet.</p>}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
