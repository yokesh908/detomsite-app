import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiCached } from '../services/api'
import {
  canOrderFromShop,
  LocalAnnouncement,
  LocalProduct,
  LocalShop,
  shopStatusText,
} from '../types/localApi'
import { getLocalSession } from '../utils/session'
import { addProductToCart } from '../utils/cart'

const gradients = ['from-emerald-500 to-emerald-700', 'from-amber-400 to-orange-500', 'from-emerald-600 to-emerald-800', 'from-teal-400 to-emerald-600']

interface BatchInfo {
  batch_type: 'Afternoon' | 'Night'
  next_token: number
  accepted_until: string
  delivery_window: string
}

export function Home() {
  const session = getLocalSession()
  const [shops, setShops] = useState<LocalShop[]>([])
  const [products, setProducts] = useState<LocalProduct[]>([])
  const [announcements, setAnnouncements] = useState<LocalAnnouncement[]>([])
  const [batch, setBatch] = useState<BatchInfo | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    apiCached.get<LocalShop[]>('/local/shops', { public_only: true }, 10000)
      .then(setShops).catch(() => setShops([]))
    apiCached.get<LocalProduct[]>('/local/products', undefined, 10000).then(setProducts).catch(() => setProducts([]))
    apiCached.get<LocalAnnouncement[]>('/local/announcements', undefined, 10000).then(setAnnouncements).catch(() => setAnnouncements([]))
    apiCached.get<BatchInfo>('/local/batch', undefined, 10000).then(setBatch).catch(() => setBatch(null))
  }, [])

  const query = search.trim().toLowerCase()

  // Closed shops stay invisible to students everywhere — only shops that are
  // actually accepting orders appear in search results and listings.
  const filteredShops = useMemo(() => shops.filter(s => canOrderFromShop(s)).filter(s => {
    if (!query) return true
    const shopMatch = `${s.name} ${s.category} ${s.description}`.toLowerCase().includes(query)
    const hasFoodMatch = products.some(p => p.shop_id === s.id && p.name.toLowerCase().includes(query))
    return shopMatch || hasFoodMatch
  }), [shops, products, query])

  // Combined "food" results: matching dishes from OPEN shops only, so a search
  // never advertises food that cannot be ordered right now. Availability is
  // enforced at render time (Add vs Closed/Out badge).
  const openShops = shops.filter(s => canOrderFromShop(s))
  const openShopIds = useMemo(() => new Set(openShops.map(s => s.id)), [openShops])
  const featured = openShops.slice(0, 4)

  // Combined "food" results: matching dishes from OPEN shops only, so a search
  // never advertises food that cannot be ordered right now. Availability is
  // enforced at render time (Add vs Closed/Out badge).
  const foodResults = useMemo(() => {
    if (!query) return []
    return products.filter(p => p.name.toLowerCase().includes(query) && openShopIds.has(p.shop_id))
  }, [products, query, openShopIds])

  const handleAdd = (product: LocalProduct, shop: LocalShop) => {
    addProductToCart(product, shop)
  }

  return (
    <div className="min-h-screen bg-white">
      {/* Top hero — swiggy-style search bar */}
      <div className="bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
        <div className="mx-auto max-w-7xl px-4 py-10">
          <div className="flex flex-col items-start gap-3">
            {session && <p className="text-sm font-semibold uppercase tracking-[0.3em] text-gold/80">🎓 {session.name}</p>}
            <h1 className="text-4xl font-black tracking-tight">What's on your mind today?</h1>
            {batch && (
              <div className="flex flex-wrap gap-2 text-xs font-bold">
                <span className="rounded-pill bg-white/10 px-3 py-1.5">{batch.batch_type} batch · deliver {batch.delivery_window}</span>
                <span className="rounded-pill bg-gold/20 px-3 py-1.5 text-gold">Order before {batch.accepted_until}</span>
                <span className="rounded-pill bg-white/10 px-3 py-1.5">Next token #{batch.next_token}</span>
              </div>
            )}
            <div className="mt-3 flex w-full max-w-2xl overflow-hidden rounded-full border border-white/15 bg-white/95 p-2 shadow-2xl shadow-emerald-950/20">
              <input value={search} onChange={e => setSearch(e.target.value)}
                className="min-w-0 flex-1 bg-transparent px-4 py-2.5 text-slate-700 placeholder-slate-400 outline-none"
                placeholder="Search for restaurants, dishes, or shops..." />
              <Link to="/cart" className="flex shrink-0 items-center gap-1.5 rounded-full bg-primary px-5 py-2.5 text-sm font-bold text-white transition-colors hover:bg-primary-dark">🛒 Cart</Link>
            </div>
          </div>
        </div>
      </div>

      {/* Notification / announcement bar from shops */}
      {announcements.length > 0 && (
        <div className="mx-auto max-w-7xl px-4 pt-5">
          <div className="flex items-center gap-2 overflow-x-auto rounded-card border border-gold/30 bg-gold-50 p-3">
            <span className="shrink-0 text-lg">📢</span>
            {announcements.map(ann => (
              <span key={ann.id} className="shrink-0 rounded-pill bg-white px-3 py-1.5 text-xs font-semibold text-gold-700 shadow-sm">
                {ann.message}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Search food results */}
      {foodResults.length > 0 && (
        <section className="mx-auto max-w-7xl px-4 py-6">
          <h2 className="mb-3 text-lg font-bold text-primary-dark">Dishes matching "{search.trim()}"</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {foodResults.slice(0, 8).map(product => {
              const shop = shops.find(s => s.id === product.shop_id)
              if (!shop) return null
              return (
                <div key={product.id} className="flex items-center justify-between rounded-btn border border-primary-light/30 bg-white p-3 shadow-[0_8px_25px_rgba(15,118,110,0.08)]">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-bold text-primary-dark">{product.name}</h3>
                    <p className="text-xs font-semibold text-slate-500">{shop.name} · ₹{product.price}</p>
                  </div>
                  {canOrderFromShop(shop) && Boolean(product.available) && product.inventory > 0 ? (
                    <button onClick={() => handleAdd(product, shop)}
                      className="shrink-0 rounded-pill bg-primary-light/30 px-3 py-1.5 text-xs font-bold text-primary transition-colors hover:bg-primary hover:text-white">Add</button>
                  ) : (
                    <span className="shrink-0 text-xs font-semibold text-slate-400">{product.inventory <= 0 ? 'Out' : 'Closed'}</span>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {query && filteredShops.length === 0 && foodResults.length === 0 && (
        <div className="mx-auto max-w-7xl px-4 py-10 text-center text-slate-500">No shops or dishes match "{search.trim()}".</div>
      )}

      {/* Featured open shops */}
      {featured.length > 0 && !query && (
        <section className="mx-auto max-w-7xl px-4 py-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-bold text-primary-dark">Open now</h2>
            <Link to="/shops" className="text-sm font-semibold text-primary hover:text-primary-dark">View all</Link>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {featured.map((shop, i) => (
              <Link key={shop.id} to={`/shop/${shop.id}`}
                className="group overflow-hidden rounded-[24px] border border-primary-light/30 bg-white shadow-[0_10px_35px_rgba(15,118,110,0.08)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_45px_rgba(15,118,110,0.16)]">
                {shop.shop_image ? (
                  <img src={shop.shop_image} alt={shop.name} className={`h-28 w-full object-cover`} />
                ) : (
                  <div className={`h-28 bg-gradient-to-br ${gradients[i % gradients.length]}`} />
                )}
                <div className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div><h3 className="font-bold text-primary-dark">{shop.name}</h3><p className="text-sm font-medium text-slate-500">{shop.category}</p></div>
                    <span className="shrink-0 rounded-pill bg-primary-light/30 px-2.5 py-1 text-xs font-bold text-primary">{shop.rating.toFixed(1)}</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-xs font-semibold">
                    <span className="text-primary">{shopStatusText(shop)}</span>
                    <span className="text-slate-400">{shop.opening_time}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* All restaurants */}
      <section className="mx-auto max-w-7xl px-4 pb-10">
        {!query && <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold text-primary-dark">All restaurants</h2>
          <p className="text-sm font-semibold text-slate-500">{filteredShops.length} available</p>
        </div>}
        {filteredShops.length === 0 ? (
          !query && <div className="rounded-[24px] border border-dashed border-primary-light/50 bg-slate-50 p-10 text-center text-slate-500">No shops have joined DETOMSITE yet.</div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {filteredShops.map((shop, i) => (
              <Link key={shop.id} to={`/shop/${shop.id}`}
                className="group overflow-hidden rounded-[24px] border border-primary-light/30 bg-white shadow-[0_10px_35px_rgba(15,118,110,0.08)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_45px_rgba(15,118,110,0.16)]">
                {shop.shop_image ? (
                  <img src={shop.shop_image} alt={shop.name} className="h-28 w-full object-cover" />
                ) : (
                  <div className={`h-28 bg-gradient-to-br ${gradients[i % gradients.length]}`} />
                )}
                <div className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div><h3 className="font-bold text-primary-dark">{shop.name}</h3><p className="text-sm font-medium text-slate-500">{shop.category}</p></div>
                    <span className="shrink-0 rounded-pill bg-primary-light/30 px-2.5 py-1 text-xs font-bold text-primary">{shop.rating.toFixed(1)}</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-xs font-semibold">
                    <span className={canOrderFromShop(shop) ? 'text-primary' : 'text-slate-400'}>{shopStatusText(shop)}</span>
                    <span className="text-slate-400">{shop.opening_time}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Bottom CTA for shopkeepers */}
      <div className="mx-auto max-w-7xl px-4 pb-10">
        <div className="rounded-[24px] border border-gold/30 bg-gradient-to-br from-gold-50 to-emerald-50 p-6 text-center">
          <p className="text-sm font-semibold text-gold-700">Are you a campus shopkeeper?</p>
          <Link to="/vendor/register" className="mt-3 inline-block rounded-btn bg-gold px-5 py-2.5 text-sm font-bold text-white transition-all hover:bg-gold">Register your shop →</Link>
        </div>
      </div>
    </div>
  )
}