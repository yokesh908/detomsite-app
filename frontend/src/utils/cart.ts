import { LocalProduct, LocalShop } from '../types/localApi'

export interface StoredCartItem {
  product_id: string
  shop_id: string
  shop_name: string
  name: string
  price: number
  category: string
  quantity: number
}

export interface CartShopGroup {
  shop_id: string
  shop_name: string
  items: StoredCartItem[]
  subtotal: number
}

const CART_KEY = 'detomsite-cart'

export function getCart(): StoredCartItem[] {
  try {
    const rawCart = localStorage.getItem(CART_KEY)
    if (!rawCart) return []
    const parsed = JSON.parse(rawCart)
    // A corrupted value (object, string, …) used to hard-crash every page that
    // renders the cart — accept only a real array of items.
    if (!Array.isArray(parsed)) return []
    return parsed.filter(item => item && typeof item === 'object' && !Number.isNaN(Number(item.price)))
  } catch {
    return []
  }
}

/**
 * Group cart items by shop (multi-shop combo).
 * Returns one group per shop so checkout/payment can split per shop.
 */
export function getCartByShop(): CartShopGroup[] {
  const items = getCart()
  const map = new Map<string, CartShopGroup>()
  for (const item of items) {
    let group = map.get(item.shop_id)
    if (!group) {
      group = { shop_id: item.shop_id, shop_name: item.shop_name, items: [], subtotal: 0 }
      map.set(item.shop_id, group)
    }
    group.items.push(item)
    group.subtotal += item.price * item.quantity
  }
  return Array.from(map.values())
}

export function saveCart(items: StoredCartItem[]) {
  localStorage.setItem(CART_KEY, JSON.stringify(items))
  window.dispatchEvent(new Event('detomsite-cart-updated'))
}

export function clearCart() {
  saveCart([])
}

/** Add a product to the cart with a given quantity. If the product is already
 *  in the cart, the quantity is incremented (merged) instead. */
export function addProductToCart(product: LocalProduct, shop: LocalShop, quantity = 1) {
  const current = getCart()
  const existing = current.find(item => item.product_id === product.id)
  let nextItems: StoredCartItem[]
  if (existing) {
    nextItems = current.map(item =>
      item.product_id === product.id
        ? { ...item, quantity: item.quantity + quantity }
        : item
    )
  } else {
    nextItems = [
      ...current,
      {
        product_id: product.id,
        shop_id: shop.id,
        shop_name: shop.name,
        name: product.name,
        price: product.price,
        category: product.category,
        quantity,
      },
    ]
  }
  saveCart(nextItems)
  return nextItems
}

/** Set an explicit quantity for a product (used by stepper -/+ buttons). */
export function setProductQuantity(product_id: string, quantity: number) {
  const current = getCart()
  if (quantity <= 0) {
    const nextItems = current.filter(item => item.product_id !== product_id)
    saveCart(nextItems)
    return nextItems
  }
  const nextItems = current.map(item =>
    item.product_id === product_id ? { ...item, quantity } : item
  )
  saveCart(nextItems)
  return nextItems
}

/** Remove a product entirely from the cart. */
export function removeProductFromCart(product_id: string) {
  const nextItems = getCart().filter(item => item.product_id !== product_id)
  saveCart(nextItems)
  return nextItems
}

/** Convert a cart shop group into the backend's checkout payload shape. */
export function toPaymentGroup(group: CartShopGroup) {
  return {
    shop_id: group.shop_id,
    items: group.items.map(item => ({ product_id: item.product_id, quantity: item.quantity })),
  }
}
