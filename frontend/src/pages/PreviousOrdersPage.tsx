import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { LocalParentOrder } from '../types/localApi'

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function OrderCard({ order, index }: { order: LocalParentOrder; index: number }) {
  const navigate = useNavigate()
  const statusColors: Record<string, string> = {
    Pending: 'bg-amber-100 text-amber-700 border-amber-200',
    Confirmed: 'bg-blue-100 text-blue-700 border-blue-200',
    Accepted: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    Preparing: 'bg-purple-100 text-purple-700 border-purple-200',
    Ready: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    Delivered: 'bg-green-100 text-green-700 border-green-200',
    Completed: 'bg-gray-100 text-gray-700 border-gray-200',
    Cancelled: 'bg-red-100 text-red-700 border-red-200',
  }
  const statusClass = statusColors[order.status] || 'bg-gray-100 text-gray-700 border-gray-200'

  return (
    <div key={order.id} className={`rounded-xl border ${index % 2 === 0 ? 'bg-white shadow-sm' : 'bg-gray-50/50'} p-5 transition-all hover:shadow-md`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-lg font-bold text-primary-dark">#{order.token}</span>
            <span className={`shrink-0 rounded-full border px-3 py-0.5 text-xs font-bold uppercase tracking-wide ${statusClass}`}>
              {order.status}
            </span>
          </div>
          <p className="text-sm text-gray-500">{order.payment_method} · {formatDate(order.created_at)}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {order.sub_orders?.map((sub, i) => (
              <span key={i} className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                🏪 {sub.shop_name}
              </span>
            ))}
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xl font-bold text-primary">₹{order.total}</p>
          <p className="text-xs text-gray-400">Total</p>
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <button onClick={() => navigate(`/order-result/${order.id}`)} className="flex-1 rounded-btn bg-primary px-4 py-2 text-sm font-bold text-white hover:bg-primary-dark transition-colors">View Details</button>
        {order.status === 'Pending' && (
          <button onClick={() => { if (confirm('Cancel this order?')) { api.patch(`/local/orders/${order.id}/cancel`).then(() => navigate(0)) } }} className="rounded-btn border border-red-200 bg-white px-4 py-2 text-sm font-bold text-red-600 hover:bg-red-50 transition-colors">Cancel</button>
        )}
      </div>
    </div>
  )
}

export function PreviousOrdersPage() {
  const [orders, setOrders] = useState<LocalParentOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'active' | 'completed' | 'cancelled'>('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      api.get<LocalParentOrder[]>('/local/orders/parent')
        .then(res => setOrders(res.data || []))
        .catch(() => setOrders([]))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(timer)
  }, [])

  const filtered = orders.filter((o: LocalParentOrder) => {
    const matchesFilter =
      filter === 'all' ||
      (filter === 'active' && ['Pending', 'Confirmed', 'Accepted', 'Preparing', 'Ready'].includes(o.status)) ||
      (filter === 'completed' && ['Delivered', 'Completed'].includes(o.status)) ||
      (filter === 'cancelled' && o.status === 'Cancelled')
    const matchesSearch = search.trim() === '' ||
      `${o.token} ${o.status} ${o.sub_orders?.map((s: any) => s.shop_name).join(' ')}`.toLowerCase().includes(search.toLowerCase())
    return matchesFilter && matchesSearch
  })

  const stats = {
    total: orders.length,
    active: orders.filter((o: LocalParentOrder) => ['Pending', 'Confirmed', 'Accepted', 'Preparing', 'Ready'].includes(o.status)).length,
    completed: orders.filter((o: LocalParentOrder) => ['Delivered', 'Completed'].includes(o.status)).length,
    cancelled: orders.filter((o: LocalParentOrder) => o.status === 'Cancelled').length,
    totalSpent: orders.filter((o: LocalParentOrder) => ['Delivered', 'Completed'].includes(o.status)).reduce((s: number, o: LocalParentOrder) => s + o.total, 0),
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-primary-dark">My Previous Orders</h1>
          <p className="mt-1 text-sm text-gray-500">View your complete order history</p>
        </div>

        <div className="mb-8 grid grid-cols-2 sm:grid-cols-5 gap-4">
          <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Total Orders</p>
            <p className="mt-1 text-2xl font-bold text-primary-dark">{stats.total}</p>
          </div>
          <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Active</p>
            <p className="mt-1 text-2xl font-bold text-amber-600">{stats.active}</p>
          </div>
          <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Completed</p>
            <p className="mt-1 text-2xl font-bold text-emerald-600">{stats.completed}</p>
          </div>
          <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Cancelled</p>
            <p className="mt-1 text-2xl font-bold text-red-500">{stats.cancelled}</p>
          </div>
          <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Total Spent</p>
            <p className="mt-1 text-2xl font-bold text-primary">₹{stats.totalSpent}</p>
          </div>
        </div>

        <div className="mb-6 flex flex-wrap gap-3">
          {(['all', 'active', 'completed', 'cancelled'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${filter === f ? 'bg-primary text-white shadow-sm' : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'}`}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
          <div className="relative ml-auto">
            <input type="text" placeholder="Search by shop or token..." value={search} onChange={e => setSearch(e.target.value)} className="h-9 w-48 rounded-full border border-gray-200 bg-white pl-9 pr-3 text-sm text-gray-700 placeholder-gray-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-200 border-t-emerald-600" />
              <p className="text-sm font-medium text-gray-400">Loading your orders...</p>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl bg-white p-12 text-center shadow-sm border border-gray-100">
            <div className="text-5xl mb-4">📦</div>
            <h3 className="text-lg font-bold text-gray-700">No orders found</h3>
            <p className="mt-1 text-sm text-gray-500">{search ? 'Try a different search term' : 'Your order history will appear once you place an order'}</p>
            {!search && (<Link to="/shops" className="mt-4 inline-flex rounded-btn bg-primary px-6 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-primary-dark">Browse Shops →</Link>)}
          </div>
        ) : (
          <div className="space-y-3">{filtered.map((order: LocalParentOrder, i: number) => <OrderCard key={order.id} order={order} index={i} />)}</div>
        )}
      </div>
    </div>
  )
}
