export type ShopStatus = 'Open' | 'Busy' | 'Closed' | 'Maintenance'
export type ApprovalStatus = 'Approved' | 'Pending Approval'
export type DeliverySlot = 'Morning' | 'Afternoon' | 'Evening' | 'Night'
export type OrderStatus =
  | 'Pending Payment'
  | 'Pending Acceptance'
  | 'Confirmed'
  | 'Preparing'
  | 'Ready'
  | 'Completed'
  | 'Cancelled'
  | 'Failed'
  | 'Refunded'

export interface Shop {
  id: string
  name: string

  category: string
  description: string
  image: string
  rating: number
  openingTime: string
  closingTime: string
  present: boolean
  status: ShopStatus
  approvalStatus: ApprovalStatus
  shopkeeperName: string
  phone: string
  ordersToday: number
  revenueToday: number
  pendingOrders: number
  activeOrders: number
  currentToken: number
}

export interface Product {
  id: string
  shopId: string
  name: string
  description: string
  price: number
  pendingPrice?: number
  category: string
  image: string
  inventory: number
  prepTime: number
  available: boolean
}

export interface Order {
  id: string
  token: number
  studentName: string
  studentPhone: string
  shopId: string
  shopName: string
  items: string
  total: number
  deliveryLocation: string
  deliverySlot: DeliverySlot
  status: OrderStatus
  createdAt: string
}

export const deliverySlots: Record<DeliverySlot, string> = {
  Morning: '08:00 AM - 11:00 AM',
  Afternoon: '12:00 PM - 04:00 PM',
  Evening: '05:00 PM - 08:00 PM',
  Night: '08:00 PM - 11:00 PM',
}

export const shops: Shop[] = [
  {
    id: '1',
    name: 'Pizza Palace',
    category: 'Italian',
    description: 'Campus pizzas, garlic breads, and quick combo meals.',
    image: '🍕',
    rating: 4.5,
    openingTime: '08:00 AM',
    closingTime: '10:00 PM',
    present: true,
    status: 'Open',
    approvalStatus: 'Approved',
    shopkeeperName: 'Arun Kumar',
    phone: '9876543210',
    ordersToday: 24,
    revenueToday: 12450,
    pendingOrders: 3,
    activeOrders: 5,
    currentToken: 23,
  },
  {
    id: '2',
    name: 'Burger Bay',
    category: 'Fast Food',
    description: 'Burgers, fries, rolls, and cold drinks for short breaks.',
    image: '🍔',
    rating: 4.2,
    openingTime: '09:00 AM',
    closingTime: '09:30 PM',
    present: true,
    status: 'Busy',
    approvalStatus: 'Approved',
    shopkeeperName: 'Priya Menon',
    phone: '9876543211',
    ordersToday: 18,
    revenueToday: 8560,
    pendingOrders: 2,
    activeOrders: 6,
    currentToken: 21,
  },
  {
    id: '3',
    name: 'Biryani House',
    category: 'Indian',
    description: 'Meals, biryani, snacks, and evening tiffin boxes.',
    image: '🍛',
    rating: 4.6,
    openingTime: '11:00 AM',
    closingTime: '11:00 PM',
    present: false,
    status: 'Closed',
    approvalStatus: 'Approved',
    shopkeeperName: 'Naveen Shah',
    phone: '9876543212',
    ordersToday: 12,
    revenueToday: 9320,
    pendingOrders: 0,
    activeOrders: 0,
    currentToken: 18,
  },
  {
    id: '4',
    name: 'Tea Point',
    category: 'Cafe',
    description: 'Tea, coffee, puffs, sandwiches, and study-time snacks.',
    image: '☕',
    rating: 4.7,
    openingTime: '07:30 AM',
    closingTime: '08:00 PM',
    present: true,
    status: 'Open',
    approvalStatus: 'Pending Approval',
    shopkeeperName: 'Meera Joseph',
    phone: '9876543213',
    ordersToday: 0,
    revenueToday: 0,
    pendingOrders: 0,
    activeOrders: 0,
    currentToken: 18,
  },
]

export const products: Product[] = [
  {
    id: 'p1',
    shopId: '1',
    name: 'Margherita Pizza',
    description: 'Cheese pizza with tomato base.',
    price: 250,
    category: 'Pizza',
    image: '🍕',
    inventory: 18,
    prepTime: 15,
    available: true,
  },
  {
    id: 'p2',
    shopId: '1',
    name: 'Garlic Bread',
    description: 'Four pieces with herbed butter.',
    price: 100,
    pendingPrice: 120,
    category: 'Starters',
    image: '🍞',
    inventory: 24,
    prepTime: 8,
    available: true,
  },
  {
    id: 'p3',
    shopId: '1',
    name: 'Coke 250ml',
    description: 'Chilled beverage.',
    price: 50,
    category: 'Beverages',
    image: '🥤',
    inventory: 40,
    prepTime: 2,
    available: true,
  },
  {
    id: 'p4',
    shopId: '2',
    name: 'Classic Veg Burger',
    description: 'Patty, cheese, lettuce, and house sauce.',
    price: 140,
    category: 'Burgers',
    image: '🍔',
    inventory: 20,
    prepTime: 12,
    available: true,
  },
  {
    id: 'p5',
    shopId: '2',
    name: 'Masala Fries',
    description: 'Crispy fries with campus masala.',
    price: 90,
    category: 'Sides',
    image: '🍟',
    inventory: 30,
    prepTime: 7,
    available: true,
  },
  {
    id: 'p6',
    shopId: '3',
    name: 'Chicken Biryani',
    description: 'Single portion with raita.',
    price: 220,
    category: 'Meals',
    image: '🍛',
    inventory: 0,
    prepTime: 30,
    available: false,
  },
]

export const orders: Order[] = [
  {
    id: 'o1',
    token: 23,
    studentName: 'Yokesh',
    studentPhone: '9876500001',
    shopId: '1',
    shopName: 'Pizza Palace',
    items: '2x Margherita Pizza, 1x Coke',
    total: 590,
    deliveryLocation: 'Hostel A Block 201',
    deliverySlot: 'Evening',
    status: 'Pending Acceptance',
    createdAt: '2026-06-11',
  },
  {
    id: 'o2',
    token: 22,
    studentName: 'Anitha',
    studentPhone: '9876500002',
    shopId: '1',
    shopName: 'Pizza Palace',
    items: '1x Garlic Bread, 1x Coke',
    total: 180,
    deliveryLocation: 'Library Gate',
    deliverySlot: 'Afternoon',
    status: 'Preparing',
    createdAt: '2026-06-11',
  },
  {
    id: 'o3',
    token: 21,
    studentName: 'Rahul',
    studentPhone: '9876500003',
    shopId: '2',
    shopName: 'Burger Bay',
    items: '2x Classic Veg Burger',
    total: 310,
    deliveryLocation: 'CSE Block',
    deliverySlot: 'Night',
    status: 'Ready',
    createdAt: '2026-06-11',
  },
  {
    id: 'o4',
    token: 20,
    studentName: 'Yokesh',
    studentPhone: '9876500001',
    shopId: '3',
    shopName: 'Biryani House',
    items: '1x Chicken Biryani',
    total: 250,
    deliveryLocation: 'Hostel A Block 201',
    deliverySlot: 'Afternoon',
    status: 'Completed',
    createdAt: '2026-06-10',
  },
]

export function canAcceptOrders(shop: Shop) {
  return shop.approvalStatus === 'Approved' && shop.present && shop.status === 'Open'
}

export function availabilityText(shop: Shop) {
  if (shop.approvalStatus !== 'Approved') return 'Pending admin approval'
  if (!shop.present) return 'Hidden from students'
  if (shop.status !== 'Open') return `Shop ${shop.status.toLowerCase()}`
  return `${shop.openingTime} - ${shop.closingTime}`
}
