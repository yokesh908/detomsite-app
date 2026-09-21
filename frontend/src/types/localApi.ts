export interface LocalShop {
  id: string
  name: string
  category: string
  description: string
  rating: number
  opening_time: string
  closing_time: string
  present: number
  status: string
  approval_status: string
  shopkeeper_email: string
  shopkeeper_name: string
  phone: string
  whatsapp_number: string
  ordering_position: number
  is_featured: number
  shop_image: string
  orders_today: number
  revenue_today: number
  current_token: number
  prep_time?: number
}

export interface LocalProduct {
  id: string
  shop_id: string
  name: string
  description: string
  price: number
  pending_price: number | null
  category: string
  inventory: number
  prep_time: number
  available: number
  batch_type?: string
  stock_left?: number
}

export interface LocalOrder {
  id: string
  token: number
  student_name: string
  student_phone: string
  shop_id: string
  shop_name: string
  items: string
  total: number
  delivery_location: string
  delivery_slot: string
  status: string
  created_at: string
}

export interface LocalSubOrder {
  id: string
  parent_order_id: string
  shop_id: string
  shop_name: string
  shop_phone: string
  shop_whatsapp: string
  token: number
  items_summary: string
  items: Array<{
    id: number
    sub_order_id: string
    product_id: string
    product_name: string
    price: number
    quantity: number
    total: number
  }>
  subtotal: number
  commission_5pct: number
  status: string
  accepted_at: string | null
  prepared_at: string | null
  ready_at: string | null
  completed_at: string | null
  delivered_at: string | null
  batch_type: string
  rejection_reason: string
  created_at: string
  parent?: {
    student_name: string
    student_phone: string
    delivery_location: string
    total: number
    payment_method: string
    created_at: string
  }
}

export interface LocalParentOrder {
  id: string
  token: number
  student_name: string
  student_phone: string
  student_email: string
  total: number
  payment_method: string
  payment_status: string
  delivery_location: string
  status: string
  created_at: string
  sub_orders: LocalSubOrder[]
}

export interface BatchInfo {
  batch_type: 'Afternoon' | 'Night'
  token_starts_at: number
  next_token: number
  date_key: string
  accepted_until: string
  delivery_window: string
}

export interface LocalComplaint {
  id: string
  parent_order_id: string
  sub_order_id: string
  student_name: string
  student_phone: string
  shop_id: string
  shop_name: string
  subject: string
  message: string
  proof_url: string
  status: string
  admin_notes: string
  created_at: string
}

export interface LocalRefund {
  id: string
  parent_order_id: string
  sub_order_id: string
  student_name: string
  shop_name: string
  original_amount: number
  refund_amount: number
  refund_type: string
  refund_utr: string
  status: string
  admin_notes: string
  created_at: string
  completed_at: string | null
}

export interface LocalSettlement {
  id: string
  shop_id: string
  shop_name: string
  date_key: string
  gross_sales: number
  commission_5pct: number
  refunds_adjusted: number
  net_payable: number
  cod_collected: number
  status: string
  settlement_utr: string
  created_at: string
  completed_at: string | null
}

export interface LocalAnnouncement {
  id: string
  shop_id: string
  message: string
  is_active: number
  created_at: string
}

export interface LocalMenuChangeRequest {
  id: string
  shop_id: string
  product_id: string
  change_type: string
  field_name: string
  old_value: string
  new_value: string
  status: string
  admin_notes: string
  created_at: string
  reviewed_at: string | null
}

export interface LocalPayment {
  id: string
  order_id: string
  amount: number
  method: string
  status: string
  utr_number: string | null
  screenshot_name: string | null
  created_at: string
}

export interface LocalTicket {
  id: string
  ticket_number: string
  name: string
  email: string
  phone_number: string
  category: string
  title: string
  description: string
  status: string
  created_at: string
}

export interface LocalNotification {
  id: string
  title: string
  message: string
  order_id: string | null
  status: string | null
  is_read: number
  created_at: string
}

export interface LocalFeedback {
  id: string
  user_id: number | null
  username: string
  name: string
  email: string
  category: 'Bug' | 'Improvement' | 'Suggestion' | 'Other'
  subject: string
  message: string
  page: string
  status: 'Open' | 'In Review' | "Fixed" | "Won't Fix"
  /* 'User' = submitted through the portal; 'ATS' = automated test suite */
  source: 'User' | 'ATS'
  created_at: string
}

export interface LocalSummary {
  shops: number
  orderable_shops: number
  products: number
  active_orders: number
  revenue: number
  token_starts_at: number
}

export interface LocalDatabaseStatus {
  connected: boolean
  mode: 'mongo' | 'turso' | 'demo'
  database: string
  persistent: boolean
  message: string
}

export interface LocalPaymentSettings {
  manual_enabled: boolean
  upi_id: string
  receiver_name: string
  instructions: string
  razorpay_enabled: boolean
}

export function canOrderFromShop(shop: LocalShop) {
  // The vendor's Start/Stop toggle is the single source of truth — once a shop
  // is started it stays open until the vendor stops it. Opening/closing hours
  // are informational only and never block ordering (mirrors the backend's
  // _shop_is_orderable so the UI never disagrees with the server).
  return (
    shop.approval_status === 'Approved' &&
    Boolean(shop.present) &&
    shop.status === 'Open'
  )
}

export function shopStatusText(shop: LocalShop) {
  if (shop.approval_status !== 'Approved') return 'Approval pending'
  if (!shop.present) return 'Not accepting now'
  if (shop.status !== 'Open') return shop.status
  return 'Open now'
}
