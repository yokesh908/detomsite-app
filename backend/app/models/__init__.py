"""
Database models for DETOMSITE
"""
from beanie import Document, Indexed, PydanticObjectId
from pydantic import ConfigDict, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

ObjectId = PydanticObjectId


class UserRole(str, Enum):
    """User role enumeration"""
    CUSTOMER = "customer"
    SHOPKEEPER = "shopkeeper"
    DELIVERY_PARTNER = "delivery_partner"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserStatus(str, Enum):
    """User status enumeration"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MongoDocument(Document):
    """Base document config for BSON ObjectId fields."""
    model_config = ConfigDict(arbitrary_types_allowed=True)


class User(MongoDocument):
    """User model for all user types"""
    email: Indexed(EmailStr, unique=True)
    password_hash: str
    first_name: str
    last_name: str
    phone_number: Optional[str] = None
    profile_image: Optional[str] = None
    role: UserRole
    status: UserStatus = UserStatus.ACTIVE
    campus_id: Optional[ObjectId] = None  # Multi-tenancy
    email_verified: bool = False
    force_password_change: bool = False
    last_login: Optional[datetime] = None
    device_tokens: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"


class Campus(MongoDocument):
    """Campus/College model for multi-tenancy"""
    name: str
    slug: Indexed(str, unique=True)
    description: Optional[str] = None
    logo_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    city: str
    state: str
    address: str
    contact_email: str
    contact_phone: str
    commission_percentage: float = 10.0
    is_active: bool = True
    admin_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "campuses"


class ShopStatus(str, Enum):
    """Shop status enumeration"""
    OPEN = "open"
    BUSY = "busy"
    CLOSED = "closed"
    MAINTENANCE = "maintenance"


class Shop(MongoDocument):
    """Shop model"""
    campus_id: Indexed(ObjectId)
    shopkeeper_id: Indexed(ObjectId)
    name: str
    slug: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    category: str  # e.g., "Meals", "Snacks", "Drinks", "Desserts"
    contact_number: str
    opening_time: str  # "09:00"
    closing_time: str  # "21:00"
    delivery_time_minutes: int = 30
    upi_id: Optional[str] = None
    qr_code_url: Optional[str] = None
    status: ShopStatus = ShopStatus.OPEN
    rating: float = 0.0
    total_reviews: int = 0
    is_verified: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "shops"


class Product(MongoDocument):
    """Product model"""
    campus_id: Indexed(ObjectId)
    shop_id: Indexed(ObjectId)
    name: str
    description: Optional[str] = None
    price: float
    images: List[str] = []
    category: str  # "Meals", "Snacks", "Drinks", "Desserts"
    inventory_count: int
    is_available: bool = True
    is_bestseller: bool = False
    is_recommended: bool = False
    variants: List[dict] = []  # e.g., [{"name": "size", "options": ["S", "M", "L"]}]
    addons: List[dict] = []  # e.g., [{"name": "Extra Cheese", "price": 50}]
    rating: float = 0.0
    total_reviews: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "products"


class Category(MongoDocument):
    """Category model"""
    campus_id: Indexed(ObjectId)
    name: str
    slug: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "categories"


class OrderStatus(str, Enum):
    """Order status enumeration"""
    DRAFT = "draft"
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_VERIFICATION = "payment_verification"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REFUNDED = "refunded"


class OrderItem(MongoDocument):
    """Order item sub-document"""
    product_id: ObjectId
    product_name: str
    quantity: int
    price: float
    variant_selections: dict = {}
    addon_selections: List[dict] = []


class Order(MongoDocument):
    """Order model"""
    campus_id: Indexed(ObjectId)
    customer_id: Indexed(ObjectId)
    shop_id: Indexed(ObjectId)
    order_number: str
    items: List[dict]  # List of OrderItem
    subtotal: float
    delivery_fee: float = 0.0
    platform_fee: float = 0.0
    tax: float = 0.0
    total_amount: float
    status: OrderStatus = OrderStatus.DRAFT
    payment_method: Optional[str] = None
    payment_id: Optional[str] = None
    delivery_partner_id: Optional[ObjectId] = None
    estimated_delivery_time: Optional[datetime] = None
    actual_delivery_time: Optional[datetime] = None
    special_instructions: Optional[str] = None
    cancellation_reason: Optional[str] = None
    cancelled_by: Optional[str] = None  # "customer", "shop", "admin"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "orders"


class PaymentStatus(str, Enum):
    """Payment status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"


class Payment(MongoDocument):
    """Payment model"""
    campus_id: Indexed(ObjectId)
    order_id: Indexed(ObjectId)
    customer_id: Indexed(ObjectId)
    amount: float
    currency: str = "INR"
    payment_method: str  # "razorpay", "manual_utr"
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    utr_number: Optional[str] = None
    screenshot_url: Optional[str] = None
    status: PaymentStatus = PaymentStatus.PENDING
    failure_reason: Optional[str] = None
    verified_by_admin: Optional[ObjectId] = None
    verified_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "payments"


class Review(MongoDocument):
    """Review model for products and shops"""
    campus_id: Indexed(ObjectId)
    customer_id: Indexed(ObjectId)
    shop_id: Optional[ObjectId] = None
    product_id: Optional[ObjectId] = None
    rating: float  # 1-5
    title: str
    content: str
    images: List[str] = []
    is_approved: bool = False
    shopkeeper_reply: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "reviews"


class NotificationChannel(str, Enum):
    """Notification channel enumeration"""
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    WHATSAPP = "whatsapp"


class Notification(MongoDocument):
    """Notification model"""
    campus_id: Indexed(ObjectId)
    user_id: Indexed(ObjectId)
    title: str
    message: str
    channels: List[NotificationChannel]
    event_type: str  # "order_placed", "payment_success", etc.
    related_id: Optional[str] = None  # order_id, payment_id, etc.
    is_read: bool = False
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "notifications"


class TicketStatus(str, Enum):
    """Ticket status enumeration"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketCategory(str, Enum):
    """Ticket category enumeration"""
    PAYMENT_ISSUE = "payment_issue"
    ORDER_ISSUE = "order_issue"
    REFUND_ISSUE = "refund_issue"
    VENDOR_COMPLAINT = "vendor_complaint"
    TECHNICAL_ISSUE = "technical_issue"


class TicketMessage(MongoDocument):
    """Ticket message sub-document"""
    sender_id: ObjectId
    sender_type: str  # "customer", "admin", "shopkeeper"
    message: str
    attachments: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Ticket(MongoDocument):
    """Support ticket model"""
    campus_id: Indexed(ObjectId)
    ticket_number: str
    customer_id: Indexed(ObjectId)
    phone_number: str
    category: TicketCategory
    title: str
    description: str
    status: TicketStatus = TicketStatus.OPEN
    priority: str = "medium"  # "low", "medium", "high", "urgent"
    assigned_to: Optional[ObjectId] = None
    order_id: Optional[ObjectId] = None
    messages: List[dict] = []  # List of TicketMessage
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "tickets"


class AuditLog(MongoDocument):
    """Audit log model for compliance"""
    campus_id: Indexed(ObjectId)
    user_id: Indexed(ObjectId)
    action: str  # "login", "logout", "order_created", etc.
    entity_type: str  # "user", "order", "payment", etc.
    entity_id: Optional[ObjectId] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "audit_logs"


class Wallet(MongoDocument):
    """Wallet model for customer money management"""
    campus_id: Indexed(ObjectId)
    user_id: Indexed(ObjectId)
    balance: float = 0.0
    total_credited: float = 0.0
    total_debited: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "wallets"


class DeliveryPartner(MongoDocument):
    """Delivery partner model"""
    campus_id: Indexed(ObjectId)
    user_id: Indexed(ObjectId)
    name: str
    phone_number: str
    vehicle_type: str  # "bike", "bicycle", "scooter"
    vehicle_number: str
    kyc_verified: bool = False
    is_active: bool = True
    total_deliveries: int = 0
    total_earnings: float = 0.0
    average_rating: float = 0.0
    current_location: Optional[dict] = None  # {"lat": 0.0, "lng": 0.0}
    is_online: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "delivery_partners"


class FeatureFlag(MongoDocument):
    """Feature flag model for gradual rollout"""
    campus_id: Optional[ObjectId] = None  # None = global
    name: str
    enabled: bool = False
    percentage: float = 0.0  # Percentage of users
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "feature_flags"


class Setting(MongoDocument):
    """Platform settings model"""
    campus_id: Optional[ObjectId] = None  # None = global
    key: str
    value: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "settings"
