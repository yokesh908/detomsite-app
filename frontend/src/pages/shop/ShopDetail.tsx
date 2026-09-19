import { useEffect, useRef, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiCached } from '../../services/api'
import { canOrderFromShop, LocalProduct, LocalShop, shopStatusText } from '../../types/localApi'
import { addProductToCart } from '../../utils/cart'
import { usePolling } from '../../hooks/usePolling'
import { same } from '../../utils/same'

export function ShopDetail() {
  const { shopId } = useParams<{ shopId: string }>()
  const [shop, setShop] = useState<LocalShop | null>(null)
  const [products, setProducts] = useState<LocalProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [added, setAdded] = useState<string | null>(null)
  const addedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(() => {
    if (!shopId) return
    // Shop and menu failures are independent — a bad stock call must not
    // nuke the whole page into "Shop not found".
    apiCached.get<LocalShop>(`/local/shops/${shopId}`, undefined, 6000)
      .then(s => setShop(cur => same(cur, s) ? cur : s))
      .catch(() => setShop(null))
    apiCached.get<LocalProduct[]>('/local/products/stock', undefined, 6000)
      .then(r => setProducts(cur => same(cur, (r || []).filter(p => (p.shop_id || '') === shopId)) ? cur : (r || []).filter(p => (p.shop_id || '') === shopId)))
      .catch(() => setProducts([]))
      .finally(() => setLoading(false))
  }, [shopId])

  // Refresh every 8s while visible so the Open/Closed status and stock stay
  // accurate; background tabs pause and refresh instantly when you switch back.
  usePolling(load, 8000, [shopId])

  useEffect(() => () => { if (addedTimer.current) clearTimeout(addedTimer.current) }, [])

  const handleAdd = (product: LocalProduct) => {
    if (!shop) return
    const p = { ...product }
    addProductToCart(p, shop)
    setAdded(product.id)
    if (addedTimer.current) clearTimeout(addedTimer.current)
    addedTimer.current = setTimeout(() => setAdded(null), 1500)
  }

  if (loading) return <div className="flex min-h-screen items-center justify-center bg-white text-gray-400">Loading...</div>
  if (!shop) return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <p className="text-gray-600 font-semibold">Shop not found</p>
      <Link to="/shops" className="ml-2 text-sm font-bold text-primary">← Browse</Link>
    </div>
  )

  const isOrderable = canOrderFromShop(shop)
  const grouped = products.reduce((acc, p) => {
    acc[p.category] = acc[p.category] || []; acc[p.category].push(p); return acc
  }, {} as Record<string, LocalProduct[]>)

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Shop header — Zomato style */}
      <div className="bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
        <div className="mx-auto max-w-4xl px-4 pt-6 pb-8">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-3xl font-black tracking-tight">{shop.name}</h1>
              <p className="mt-2 text-sm font-medium text-emerald-100/80">{shop.category} · {shop.shopkeeper_name}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-bold">
                <span className="rounded-pill bg-white/10 px-3 py-1"><span className="text-gold">★</span> {shop.rating.toFixed(1)}</span>
                <span className={`rounded-pill px-3 py-1 ${isOrderable ? 'bg-emerald-500/20 text-emerald-300' : 'bg-white/10 text-emerald-100/70'}`}>{shopStatusText(shop)}</span>
                <span className="rounded-pill bg-white/10 px-3 py-1">{shop.opening_time} – {shop.closing_time}</span>
              </div>
              <p className="mt-4 max-w-xl text-sm text-emerald-100/70">{shop.description}</p>
            </div>
            <div className="flex shrink-0 gap-2">
              <a href={`tel:${shop.phone}`}
                className="rounded-pill border border-white/20 bg-white/10 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-white/20">📞 Call shop</a>
              {(shop.whatsapp_number || shop.phone) && (
                <a target="_blank" rel="noreferrer"
                  href={`https://wa.me/${(shop.whatsapp_number || shop.phone).replace(/[^0-9]/g, '')}`}
                  className="rounded-pill bg-gold px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-gold">
                  💬 WhatsApp
                </a>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-4xl px-4 py-6">
        {Object.entries(grouped).map(([cat, items]) => (
          <section key={cat} className="mb-8">
            <h2 className="mb-3 text-lg font-bold text-primary-dark">{cat}</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {items.map(product => {
                return (
                  <div key={product.id} className={`flex items-start justify-between gap-3 rounded-card border p-4 transition-all ${isOrderable ? 'border-primary-light/30 bg-white shadow-[0_8px_25px_rgba(15,118,110,0.08)]' : 'border-primary-light/20 bg-white/70 opacity-60'}`}>
                    <div className="min-w-0 flex-1">
                      <h3 className="font-bold text-primary-dark">{product.name}</h3>
                      {product.description && <p className="mt-0.5 text-xs text-slate-500 leading-relaxed">{product.description}</p>}
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold">
                        <span className="font-bold text-primary">₹{product.price}</span>
                        {product.pending_price ? <span className="text-gold-600">Pending: ₹{product.pending_price}</span> : null}
                        <span className="text-slate-400">· ⏱ {product.prep_time} min</span>
                      </div>
                    </div>
                    {isOrderable ? (
                      <button onClick={() => handleAdd(product)}
                        className={`shrink-0 rounded-pill px-5 py-2 text-xs font-bold transition-all ${added === product.id ? 'bg-primary text-white shadow-gold-sm' : 'bg-primary-light/30 text-primary hover:bg-primary-light'}`}>
                        {added === product.id ? '✓ Added' : '+ ADD'}
                      </button>
                    ) : (
                      <span className="shrink-0 pt-1 text-xs font-semibold text-slate-400">
                        Shop closed
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        ))}
        {products.length === 0 && (
          <div className="rounded-card bg-white p-10 text-center text-gray-400 shadow-card">No menu items yet</div>
        )}

        <div className="mt-8 flex justify-center gap-3">
          <Link to="/cart" className="inline-flex items-center gap-2 rounded-btn bg-primary px-6 py-3 text-sm font-bold text-white shadow-gold transition-all hover:bg-primary-dark hover:shadow-gold-lg">🛒 View Cart</Link>
          <Link to="/shops" className="inline-flex items-center gap-2 rounded-btn border border-primary-light/30 bg-white px-6 py-3 text-sm font-bold text-primary transition-all hover:bg-primary-light/30">Add from another shop</Link>
        </div>
      </div>
    </div>
  )
}