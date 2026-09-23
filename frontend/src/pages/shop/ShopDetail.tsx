import { useEffect, useRef, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiCached } from '../../services/api'
import { canOrderFromShop, LocalProduct, LocalShop, shopStatusText } from '../../types/localApi'
import { addProductToCart, getCart } from '../../utils/cart'
import { usePolling } from '../../hooks/usePolling'
import { same } from '../../utils/same'
import { getShopImage } from '../../utils/shopImages'

export function ShopDetail() {
  const { shopId } = useParams<{ shopId: string }>()
  const [shop, setShop] = useState<LocalShop | null>(null)
  const [products, setProducts] = useState<LocalProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [added, setAdded] = useState<string | null>(null)
  const [selectedQty, setSelectedQty] = useState<Record<string, number>>({})
  const addedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cartQtyFor = (productId: string): number => {
    return getCart().find(item => item.product_id === productId)?.quantity ?? 0
  }

  const handleAdd = (product: LocalProduct) => {
    if (!shop) return
    const p = { ...product }
    const qty = selectedQty[product.id] || 1
    addProductToCart(p, shop, qty)
    setAdded(product.id)
    setSelectedQty({})
    if (addedTimer.current) clearTimeout(addedTimer.current)
    addedTimer.current = setTimeout(() => setAdded(null), 1500)
  }

  const load = useCallback(() => {
    if (!shopId) return
    apiCached.get<LocalShop>('/local/shops/' + shopId, undefined, 6000)
      .then(s => setShop(cur => same(cur, s) ? cur : s))
      .catch(() => setShop(null))
    apiCached.get<LocalProduct[]>('/local/products', undefined, 6000)
      .then(r => {
        const filtered = (r || []).filter(p => (p.shop_id || '') === shopId)
        setProducts(cur => same(cur, filtered) ? cur : filtered)
      })
      .catch(() => setProducts([]))
      .finally(() => setLoading(false))
  }, [shopId])

  usePolling(load, 8000, [shopId])

  useEffect(() => () => { if (addedTimer.current) clearTimeout(addedTimer.current) }, [])

  if (loading) return <div className="flex min-h-screen items-center justify-center bg-white text-gray-400">Loading...</div>
  if (!shop) return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <p className="text-gray-600 font-semibold">Shop not found</p>
      <Link to="/shops" className="ml-2 text-sm font-bold text-primary">Back to shops</Link>
    </div>
  )

  const isOrderable = canOrderFromShop(shop)
  const grouped = products.reduce((acc, p) => {
    acc[p.category] = acc[p.category] || []
    acc[p.category].push(p)
    return acc
  }, {} as Record<string, LocalProduct[]>)

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
        <div className="mx-auto max-w-4xl px-4 pt-6 pb-8">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <img src={shop.shop_image || getShopImage(shop.category)} alt={`${shop.name} food`} className="h-28 w-full rounded-card object-cover sm:order-2 sm:h-32 sm:w-48" onError={event => { event.currentTarget.src = getShopImage() }} />
            <div>
              <h1 className="text-3xl font-black tracking-tight">{shop.name}</h1>
              <p className="mt-2 text-sm font-medium text-emerald-100/80">{shop.category} by {shop.shopkeeper_name}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-bold">
                <span className="rounded-full bg-white/10 px-3 py-1">Rating {shop.rating}</span>
                <span className="rounded-full bg-white/10 px-3 py-1">{shopStatusText(shop)}</span>
                <span className="rounded-full bg-white/10 px-3 py-1">Prep: {shop.prep_time} min</span>
              </div>
              {shop.description && <p className="mt-3 max-w-2xl text-sm text-emerald-100/70 leading-relaxed">{shop.description}</p>}
            </div>
            <div className="flex shrink-0 gap-2">
              <a href={"tel:" + shop.phone}
                className="rounded-full border border-white/20 bg-white/10 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-white/20">Call</a>
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
                const cartQty = cartQtyFor(product.id)
                const showStepper = isOrderable && added !== product.id
                const qty = selectedQty[product.id] || 1
                return (
                  <div key={product.id} className={"flex items-start justify-between gap-3 rounded-card border p-4 transition-all " + (isOrderable ? "border-primary-light/30 bg-white shadow" : "border-primary-light/20 bg-white/70 opacity-60")}>
                    <div className="min-w-0 flex-1">
                      <h3 className="font-bold text-primary-dark">{product.name}</h3>
                      {product.description && <p className="mt-0.5 text-xs text-slate-500 leading-relaxed">{product.description}</p>}
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold">
                        <span className="font-bold text-primary">Rs.{product.price}</span>
                        {product.pending_price ? <span className="text-gold-600">Pending: Rs.{product.pending_price}</span> : null}
                        <span className="text-slate-400">Prep: {product.prep_time} min</span>
                      </div>
                      {cartQty > 0 && (
                        <span className="mt-1 block text-xs font-semibold text-gold-600">In cart: {cartQty}</span>
                      )}
                    </div>
                    {isOrderable ? (
                      showStepper ? (
                        <div className="flex shrink-0 flex-col items-end gap-2">
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => setSelectedQty(prev => ({ ...prev, [product.id]: Math.max(1, (prev[product.id] || 1) - 1) }))}
                              className="h-8 w-8 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200"
                            >-</button>
                            <span className="w-8 text-center text-sm font-bold">{qty}</span>
                            <button
                              type="button"
                              onClick={() => setSelectedQty(prev => ({ ...prev, [product.id]: (prev[product.id] || 1) + 1 }))}
                              className="h-8 w-8 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200"
                            >+</button>
                          </div>
                          <button
                            onClick={() => handleAdd(product)}
                            className="rounded-full bg-primary px-3 py-1.5 text-xs font-bold text-white transition-all hover:bg-primary-dark"
                          >
                            Add to Cart
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleAdd(product)}
                          className={"shrink-0 rounded-full px-5 py-2 text-xs font-bold transition-all " + (added === product.id ? "bg-primary text-white" : "bg-primary-light/30 text-primary hover:bg-primary-light")}
                        >
                          {added === product.id ? "+ ADDED" : "+ ADD"}
                        </button>
                      )
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
          <Link to="/cart" className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-bold text-white transition-all hover:bg-primary-dark">View Cart</Link>
          <Link to="/shops" className="inline-flex items-center gap-2 rounded-full border border-primary-light/30 bg-white px-6 py-3 text-sm font-bold text-primary transition-all hover:bg-primary-light/30">Add from another shop</Link>
        </div>
      </div>
    </div>
  )
}
