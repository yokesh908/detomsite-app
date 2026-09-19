import { StoredCartItem } from './cart'

/* Per the DETOMSITE business model the STUDENT pays ONLY the food subtotal.
   There are no student fees, no delivery fees, no tax, no COD fee.
   The platform's flat ₹10-per-order commission is deducted from each shop's share and is
   never added to the student's bill. */
export function getBillBreakdown(items: StoredCartItem[]) {
  const subtotal = items.reduce((sum, item) => sum + item.price, 0)
  const total = subtotal
  return {
    subtotal,
    tax: 0,
    delivery: 0,
    platformFee: 0,
    gatewayFee: 0,
    total,
    vendorReceives: subtotal,
  }
}