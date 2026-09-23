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
import { getShopImage } from '../utils/shopImages'

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
  const [activeCategory, setActiveCategory] = useState<string | null>(null)

  // --- Category definitions for Combos & Deals ---
  const CATEGORY_GROUPS = useMemo(() => [
    { key: 'fried', label: 'Fried Items', emoji: '\U0001F39F', hint: 'Fries, fried rice, pakoras & more' },
    { key: 'biryani', label: 'Biryani', emoji: '\U0001F39B', hint: 'Chicken, veg & egg biryani' },
    { key: 'combo', label: 'Combos', emoji: '\U0001F451', hint: 'Complete meal deals at best price' },
  ], [])

  useEffect(() => {
    apiCached.get<LocalShop[]>('/local/shops', { public_only: true }, 10000)
      .then(setShops).catch(() => setShops([]))
    apiCached.get<LocalProduct[]>('/local/products', undefined, 10000).then(setProducts).catch(() => setProducts([]))
    apiCached.get<LocalAnnouncement[]>('/local/announcements', undefined, 10000).then(setAnnouncements).catch(() => setAnnouncements([]))
    apiCached.get<BatchInfo>('/local/batch', undefined, 10000).then(setBatch).catch(() => setBatch(null))
  }, [])

  const query = search.trim().toLowerCase()

  // Closed shops stay invisible to students everywhere
  const filteredShops = useMemo(() => shops.filter(s => canOrderFromShop(s)).filter(s => {
    if (!query) return true
    const shopMatch = `${s.name} ${s.category} ${s.description}`.toLowerCase().includes(query)
    const hasFoodMatch = products.some(p => p.shop_id === s.id && p.name.toLowerCase().includes(query))
    return shopMatch || hasFoodMatch
  }), [shops, products, query])

  const openShops = shops.filter(s => canOrderFromShop(s))
  const openShopIds = useMemo(() => new Set(openShops.map(s => s.id)), [openShops])
  const featured = openShops.slice(0, 4)

  const foodResults = useMemo(() => {
    if (!query) return []
    return products.filter(p => p.name.toLowerCase().includes(query) && openShopIds.has(p.shop_id))
  }, [products, query, openShopIds])

  // --- Category food grouping ---
  const categoryFoods = useMemo(() => {
    const map: Record<string, LocalProduct[]> = { fried: [], biryani: [], combo: [] }
    for (const p of products) {
      if (!openShopIds.has(p.shop_id)) continue
      const cat = (p.category || '').toLowerCase()
      const name = (p.name || '').toLowerCase()
      if (cat.includes('fried') || cat.includes('fries') || cat.includes('pakora') || cat.includes('fried rice') || cat.includes('roll') || name.includes('fried') || name.includes('fries') || name.includes('pakora')) {
        map.fried.push(p)
      } else if (cat.includes('biryani') || name.includes('biryani')) {
        map.biryani.push(p)
      } else if (cat.includes('combo') || name.includes('combo') || name.includes('meal') || name.includes('plate') || cat.includes('meal') || cat.includes('plate')) {
        map.combo.push(p)
      }
    }
    return map
  }, [products, openShopIds])

  const categoryProducts = activeCategory ? categoryFoods[activeCategory] || [] : []

  const handleAdd = (product: LocalProduct, shop: LocalShop) => {
    addProductToCart(product, shop)
  }

  const clearCategoryFilter = () => setActiveCategory(null)

  return (
    <div className="min-h-screen bg-white">
      {/* Top hero */}
      <div className="bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
        <div className="mx-auto max-w-7xl px-4 py-10">
          <div className="flex flex-col items-start gap-3">
            {session && <p className="text-sm font-semibold uppercase tracking-[0.3em] text-gold/80">\U0001F396 {session.name}</p>}
            <h1 className="text-4xl font-black tracking-tight">What's on your mind today?</h1>
            {batch && (
              <div className="flex flex-wrap gap-2 text-xs font-bold">
                <span className="rounded-pill bg-white/10 px-3 py-1.5">{batch.batch_type} batch - deliver {batch.delivery_window}</span>
                <span className="rounded-pill bg-gold/20 px-3 py-1.5 text-gold">Order before {batch.accepted_until}</span>
                <span className="rounded-pill bg-white/10 px-3 py-1.5">Next token #{batch.next_token}</span>
              </div>
            )}
            <div className="mt-3 flex w-full max-w-2xl overflow-hidden rounded-full border border-white/15 bg-white/95 p-2 shadow-2xl shadow-emerald-950/20">
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search shops, dishes, combos..."
                className="flex-1 bg-transparent text-sm text-gray-900 placeholder-slate-400 outline-none" />
              <button
                onClick={() => { if (search.trim()) setSearch('') }}
                className="shrink-0 text-xs font-semibold text-slate-400 hover:text-slate-600 transition-colors"
              >
                Clear
              </button>
            </div>
          </div>

          {/* Announcements */}
          {announcements.filter(a => a.is_active).length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {announcements.filter(a => a.is_active).map(ann => (
                <span key={ann.id} className="shrink-0 rounded-pill bg-white px-3 py-1.5 text-xs font-semibold text-gold-700 shadow-sm">
                  {ann.message}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

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
                    <p className="text-xs font-semibold text-slate-500">{shop.name} - Rs.{product.price}</p>
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
            {featured.map(shop => (
              <Link key={shop.id} to={`/shop/${shop.id}`}
                className="group overflow-hidden rounded-[24px] border border-primary-light/30 bg-white shadow-[0_10px_35px_rgba(15,118,110,0.08)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_45px_rgba(15,118,110,0.16)]">
                <img src={shop.shop_image || getShopImage(shop.category)} alt={`${shop.name} food`} className="h-28 w-full object-cover" onError={event => { event.currentTarget.src = getShopImage() }} />
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

      {/* ===== COMBOS & DEALS: Fried Items, Biryani, Combos ===== */}
      {!query && (
        <section className="mx-auto max-w-7xl px-4 pb-6">
          {/* Category pills */}
          <div className="mb-4 flex flex-wrap gap-2">
            {CATEGORY_GROUPS.map(g => (
              <button
                key={g.key}
                onClick={() => setActiveCategory(activeCategory === g.key ? null : g.key)}
                className={
                  `rounded-full px-4 py-2 text-sm font-bold transition-all ${
                    activeCategory === g.key
                      ? 'bg-primary text-white shadow-md shadow-primary/30'
                      : 'bg-primary-light/20 text-primary-dark hover:bg-primary-light/40'
                  }`
                }
              >
                <span className="mr-1.5">{g.emoji}</span>{g.label}
              </button>
            ))}
            {activeCategory && (
              <button
                onClick={clearCategoryFilter}
                className="rounded-full bg-white/80 px-4 py-2 text-sm font-semibold text-slate-500 shadow-sm hover:bg-white"
              >
                \u2715 Clear
              </button>
            )}
          </div>

          {/* Active filter info bar */}
          {activeCategory && (
            <div className="mb-4 flex items-center gap-2 rounded-xl border border-primary-light/40 bg-primary-light/10 px-4 py-2.5 text-xs font-semibold text-primary-dark">
              <span>Filter active</span>
              <span>Showing {CATEGORY_GROUPS.find(g => g.key === activeCategory)?.label} - {categoryProducts.length} dishes</span>
              <span className="ml-auto text-slate-400">Click dish to add to cart</span>
            </div>
          )}

          {/* Empty state */}
          {activeCategory && categoryProducts.length === 0 && (
            <div className="rounded-[24px] border border-dashed border-primary-light/50 bg-slate-50 p-10 text-center">
              <p className="text-lg font-semibold text-slate-500">No dishes in this category right now</p>
              <p className="mt-1 text-sm text-slate-400">Try another category or check back later!</p>
            </div>
          )}

          {/* Active filter: dish grid */}
          {activeCategory && categoryProducts.length > 0 && (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {categoryProducts.map(product => {
                const shop = shops.find(s => s.id === product.shop_id)
                return (
                  <div
                    key={product.id}
                    className="group overflow-hidden rounded-[24px] border border-primary-light/30 bg-white shadow-[0_10px_35px_rgba(15,118,110,0.08)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_45px_rgba(15,118,110,0.16)]"
                  >
                    <div className="h-36 bg-gradient-to-br from-primary-light/20 to-gold-50 flex items-center justify-center text-5xl">
                      {(product.category || '').toLowerCase().includes('biryani') ? '\U0001F39B' :
                       (product.category || '').toLowerCase().includes('fried') || (product.category || '').toLowerCase().includes('fries') ? '\U0001F39F' : '\U0001F451'}
                    </div>
                    <div className="p-4">
                      <div className="mb-1 flex items-start justify-between gap-2">
                        <h3 className="line-clamp-2 font-bold text-primary-dark text-sm leading-snug">{product.name}</h3>
                        <span className="shrink-0 rounded-pill bg-gold-50 px-2 py-0.5 text-xs font-bold text-gold-700">Rs. {product.price}</span>
                      </div>
                      {product.description && <p className="text-xs font-medium text-slate-500 line-clamp-2 mb-2">{product.description}</p>}
                      <div className="flex items-center justify-between text-[10px] font-semibold text-slate-400 mb-2">
                        <span>{shop ? shop.name : 'Shop'}</span>
                        {product.inventory > 0 ? <span className="text-emerald-600">Available</span> : <span className="text-red-500">Out of stock</span>}
                      </div>
                      {product.inventory > 0 && shop && canOrderFromShop(shop) && (
                        <button
                          onClick={() => handleAdd(product, shop)}
                          className="w-full rounded-btn bg-primary py-2 text-xs font-bold text-white shadow-gold-sm transition-all hover:bg-primary-dark active:scale-[0.98]"
                        >
                          Add +
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* Default: category preview cards */}
          {!activeCategory && (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {CATEGORY_GROUPS.map(g => {
                const count = (categoryFoods[g.key] || []).length
                return (
                  <button
                    key={g.key}
                    onClick={() => setActiveCategory(g.key)}
                    className="group flex flex-col gap-3 rounded-[24px] border-2 border-primary-light/30 bg-white p-5 shadow-card transition-all hover:-translate-y-1 hover:border-primary hover:shadow-gold-sm text-left"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-4xl">{g.emoji}</span>
                      <div>
                        <h3 className="font-bold text-lg text-primary-dark group-hover:text-primary transition-colors">{g.label}</h3>
                        <p className="text-xs font-medium text-slate-500">{g.hint}</p>
                      </div>
                    </div>
                    <div className="ml-12 flex items-center justify-between">
                      <span className="rounded-full bg-primary text-white px-3 py-1 text-xs font-bold">{count} dish{count !== 1 ? 'es' : ''}</span>
                      <span className="text-primary group-hover:translate-x-1 transition-transform text-sm font-bold">View -&gt;</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
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
            {filteredShops.map(shop => (
              <Link key={shop.id} to={`/shop/${shop.id}`}
                className="group overflow-hidden rounded-[24px] border border-primary-light/30 bg-white shadow-[0_10px_35px_rgba(15,118,110,0.08)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_45px_rgba(15,118,110,0.16)]">
                <img src={shop.shop_image || getShopImage(shop.category)} alt={`${shop.name} food`} className="h-28 w-full object-cover" onError={event => { event.currentTarget.src = getShopImage() }} />
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

      {/* Bottom CTA */}
      <div className="mx-auto max-w-7xl px-4 pb-10">
        <div className="rounded-[24px] border border-gold/30 bg-gradient-to-br from-gold-50 to-emerald-50 p-6 text-center">
          <p className="text-sm font-semibold text-gold-700">Are you a campus shopkeeper?</p>
          <Link to="/vendor/register" className="mt-3 inline-block rounded-btn bg-gold px-5 py-2.5 text-sm font-bold text-white transition-all hover:bg-gold">Register your shop -&gt;</Link>
        </div>
      </div>
    </div>
  )
}
