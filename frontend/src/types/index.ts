/*
 * TypeScript type definitions
 */
export interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  phoneNumber?: string;
  profileImage?: string;
  role: UserRole;
  status: UserStatus;
  emailVerified: boolean;
  createdAt: string;
}

export enum UserRole {
  CUSTOMER = "customer",
  SHOPKEEPER = "shopkeeper",
  DELIVERY_PARTNER = "delivery_partner",
  ADMIN = "admin",
  SUPER_ADMIN = "super_admin",
}

export enum UserStatus {
  ACTIVE = "active",
  SUSPENDED = "suspended",
  DELETED = "deleted",
}

export interface Campus {
  id: string;
  name: string;
  slug: string;
  description?: string;
  logoUrl?: string;
  coverImageUrl?: string;
  city: string;
  state: string;
  address: string;
  contactEmail: string;
  contactPhone: string;
  commissionPercentage: number;
  isActive: boolean;
  adminCount: number;
  createdAt: string;
}

export interface Shop {
  id: string;
  campusId: string;
  shopkeeperId: string;
  name: string;
  slug: string;
  description?: string;
  logoUrl?: string;
  coverImageUrl?: string;
  category: string;
  contactNumber: string;
  openingTime: string;
  closingTime: string;
  deliveryTimeMinutes: number;
  upiId?: string;
  qrCodeUrl?: string;
  status: ShopStatus;
  rating: number;
  totalReviews: number;
  isVerified: boolean;
  isActive: boolean;
  createdAt: string;
}

export enum ShopStatus {
  OPEN = "open",
  BUSY = "busy",
  CLOSED = "closed",
  MAINTENANCE = "maintenance",
}

export interface Product {
  id: string;
  campusId: string;
  shopId: string;
  name: string;
  description?: string;
  price: number;
  images: string[];
  category: string;
  inventoryCount: number;
  isAvailable: boolean;
  isBestseller: boolean;
  isRecommended: boolean;
  rating: number;
  totalReviews: number;
  createdAt: string;
}

export interface Order {
  id: string;
  orderNumber: string;
  customerId: string;
  shopId: string;
  items: OrderItem[];
  subtotal: number;
  deliveryFee: number;
  platformFee: number;
  tax: number;
  totalAmount: number;
  status: OrderStatus;
  paymentId?: string;
  estimatedDeliveryTime?: string;
  createdAt: string;
}

export interface OrderItem {
  productId: string;
  productName: string;
  quantity: number;
  price: number;
  variantSelections: Record<string, string>;
  addonSelections: Array<{ name: string; price: number }>;
}

export enum OrderStatus {
  DRAFT = "draft",
  PENDING_PAYMENT = "pending_payment",
  PAYMENT_VERIFICATION = "payment_verification",
  CONFIRMED = "confirmed",
  PREPARING = "preparing",
  READY = "ready",
  PICKED_UP = "picked_up",
  DELIVERED = "delivered",
  COMPLETED = "completed",
  CANCELLED = "cancelled",
  FAILED = "failed",
  REFUNDED = "refunded",
}

export interface Payment {
  id: string;
  orderId: string;
  customerId: string;
  amount: number;
  currency: string;
  paymentMethod: string;
  status: PaymentStatus;
  createdAt: string;
}

export enum PaymentStatus {
  PENDING = "pending",
  PROCESSING = "processing",
  SUCCESS = "success",
  FAILED = "failed",
  REFUND_PENDING = "refund_pending",
  REFUNDED = "refunded",
}

export interface Review {
  id: string;
  customerId: string;
  shopId?: string;
  productId?: string;
  rating: number;
  title: string;
  content: string;
  images: string[];
  isApproved: boolean;
  shopkeeperReply?: string;
  createdAt: string;
}

export interface Ticket {
  id: string;
  ticketNumber: string;
  customerId: string;
  category: TicketCategory;
  title: string;
  description: string;
  status: TicketStatus;
  priority: string;
  messages: TicketMessage[];
  createdAt: string;
}

export interface TicketMessage {
  senderId: string;
  senderType: string;
  message: string;
  attachments: string[];
  createdAt: string;
}

export enum TicketStatus {
  OPEN = "open",
  IN_PROGRESS = "in_progress",
  RESOLVED = "resolved",
  CLOSED = "closed",
}

export enum TicketCategory {
  PAYMENT_ISSUE = "payment_issue",
  ORDER_ISSUE = "order_issue",
  REFUND_ISSUE = "refund_issue",
  VENDOR_COMPLAINT = "vendor_complaint",
  TECHNICAL_ISSUE = "technical_issue",
}
