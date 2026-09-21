import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getCartByShop, StoredCartItem, setProductQuantity, removeProductFromCart } from '../utils/cart'
import { getBillBreakdown } from '../utils/billing'

export function CartPage() {
  const navigate = useNavigate()
  const [_items, setItems] = useState<StoredCartItem[]>(() => getCartByShop().flatMap(g => g.items))
  const groups = getCartByShop()
  const bill = getBillBreakdown(groups.flatMap(g => g.items))

  useEffect(() => {
    const sync = () => setItems(getCartByShop().flatMap(g => g.items))
    window.addEventListener('detomsite-cart-updated', sync)
    return () => window.removeEventListener('detomsite-cart-updated', sync)
  }, [])

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-primary-dark">Your Cart</h1>
          <p className="mt-1 text-sm font-medium text-gray-500">
            {groups.length === 0 ? 'No items' : `${groups.length} shop${groups.length > 1 ? 's' : ''} · one payment, one token`}
          </p>
        </div>

        {groups.length === 0 ? (
          <div className="rounded-btn bg-white p-8 text-center shadow-card">
            <p className="mb-4 text-lg font-semibold text-gray-600">Your cart is empty</p>
            <Link to="/shops" className="inline-flex rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark">Browse restaurants →</Link>
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
            <div className="space-y-5">
              {/* Combo offer banner when ordering from 2+ shops */}
              {groups.length > 1 && (
                <div className="rounded-btn border border-gold/30 bg-gold-50 p-4 text-sm font-semibold text-gold-700">
                  🎉 Combo offer! You're ordering from {groups.length} shops — pay ONE combined bill and get ONE token (all sub-orders arrive together).
                </div>
              )}

              {groups.map(group => (
                <div key={group.shop_id} className="overflow-hidden rounded-btn bg-white shadow-card">
                  <div className="flex items-center justify-between border-b border-gray-100 bg-emerald-50/60 px-4 py-2.5">
                    <h3 className="font-bold text-primary-dark">🏪 {group.shop_name}</h3>
                    <span className="text-xs font-bold text-primary">Subtotal ₹{group.subtotal}</span>
                  </div>
                  <div className="divide-y divide-gray-50">
                  {group.items.map(item => (
                      <div key={item.product_id} className="flex items-center justify-between gap-4 p-4">
                        <div className="min-w-0 flex-1">
                          <h4 className="font-bold text-primary-dark">{item.name}</h4>
                          <p className="text-sm text-gray-500">Rs.{item.price} each</p>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => setProductQuantity(item.product_id, Math.max(1, item.quantity - 1))}
                              className="h-7 w-7 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200"
                            >-</button>
                            <span className="w-7 text-center text-sm font-bold">{item.quantity}</span>
                            <button
                              type="button"
                              onClick={() => setProductQuantity(item.product_id, item.quantity + 1)}
                              className="h-7 w-7 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200"
                            >+</button>
                          </div>
                          <span className="min-w-[4rem] text-right font-bold text-primary">Rs.{item.price * item.quantity}</span>
                          <button
                            onClick={() => removeProductFromCart(item.product_id)}
                            className="text-xs font-semibold text-red-500 hover:text-red-700"
                          >Remove</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="h-fit rounded-btn bg-white p-5 shadow-gold">
              <h2 className="mb-4 text-lg font-bold text-primary-dark">Bill Details</h2>
              <div className="space-y-2 text-sm">
                {groups.map(g => (
                  <div key={g.shop_id} className="flex justify-between">
                    <span className="text-gray-500">{g.shop_name}</span>
                    <span className="font-semibold text-primary">₹{g.subtotal}</span>
                  </div>
                ))}
                <div className="flex justify-between border-t border-gray-100 pt-3 text-lg font-bold text-primary-dark">
                  <span>Total ({groups.length} shops)</span><span>₹{bill.total}</span>
                </div>
                <p className="pt-1 text-xs text-gray-400">No delivery fee, no taxes. The flat ₹10 platform fee per order is deducted from each shop, not you.</p>
              </div>
              <button onClick={() => navigate('/payment')}
                className="mt-5 w-full rounded-btn bg-primary px-5 py-3 text-sm font-bold text-white shadow-gold transition-all hover:bg-primary-dark hover:shadow-gold-lg">
                Proceed to Payment →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
