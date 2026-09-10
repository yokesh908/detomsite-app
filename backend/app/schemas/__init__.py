"""
Pydantic schemas for API requests and responses
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    """User role enumeration"""
    CUSTOMER = "customer"
    SHOPKEEPER = "shopkeeper"
    DELIVERY_PARTNER = "delivery_partner"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: Optional[str] = None


class UserRegister(UserBase):
    """User registration schema"""
    password: str = Field(..., min_length=8)
    role: UserRole


class UserLogin(BaseModel):
    """User login schema"""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User response schema"""
    id: str = Field(..., alias="_id")
    email: str
    first_name: str
    last_name: str
    phone_number: Optional[str]
    profile_image: Optional[str]
    role: str
    status: str
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class TokenResponse(BaseModel):
    """Token response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class CampusBase(BaseModel):
    """Base campus schema"""
    name: str
    slug: str
    description: Optional[str] = None
    city: str
    state: str
    address: str
    contact_email: EmailStr
    contact_phone: str
    commission_percentage: float = 10.0


class CampusCreate(CampusBase):
    """Campus creation schema"""
    pass


class CampusResponse(CampusBase):
    """Campus response schema"""
    id: str = Field(..., alias="_id")
    is_active: bool
    admin_count: int
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class ShopStatus(str, Enum):
    """Shop status enumeration"""
    OPEN = "open"
    BUSY = "busy"
    CLOSED = "closed"
    MAINTENANCE = "maintenance"


class ShopBase(BaseModel):
    """Base shop schema"""
    name: str
    description: Optional[str] = None
    category: str
    contact_number: str
    opening_time: str
    closing_time: str
    delivery_time_minutes: int = 30
    upi_id: Optional[str] = None


class ShopCreate(ShopBase):
    """Shop creation schema"""
    pass


class ShopUpdate(BaseModel):
    """Shop update schema"""
    name: Optional[str] = None
    description: Optional[str] = None
    contact_number: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    status: Optional[ShopStatus] = None


class ShopResponse(ShopBase):
    """Shop response schema"""
    id: str = Field(..., alias="_id")
    shopkeeper_id: str
    logo_url: Optional[str]
    cover_image_url: Optional[str]
    status: str
    rating: float
    total_reviews: int
    is_verified: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class ProductBase(BaseModel):
    """Base product schema"""
    name: str
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    category: str
    inventory_count: int = Field(..., ge=0)


class ProductCreate(ProductBase):
    """Product creation schema"""
    pass


class ProductUpdate(BaseModel):
    """Product update schema"""
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    inventory_count: Optional[int] = Field(None, ge=0)
    is_available: Optional[bool] = None
    is_bestseller: Optional[bool] = None
    is_recommended: Optional[bool] = None


class ProductResponse(ProductBase):
    """Product response schema"""
    id: str = Field(..., alias="_id")
    shop_id: str
    images: List[str]
    is_available: bool
    is_bestseller: bool
    is_recommended: bool
    rating: float
    total_reviews: int
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class CartItem(BaseModel):
    """Cart item schema"""
    product_id: str
    quantity: int = Field(..., gt=0)
    variant_selections: dict = {}
    addon_selections: List[dict] = []


class Cart(BaseModel):
    """Cart schema"""
    items: List[CartItem]
    shop_id: str


class OrderItemResponse(BaseModel):
    """Order item response schema"""
    product_id: str
    product_name: str
    quantity: int
    price: float
    variant_selections: dict
    addon_selections: List[dict]


class OrderCreate(BaseModel):
    """Order creation schema"""
    shop_id: str
    items: List[CartItem]
    special_instructions: Optional[str] = None
    payment_method: str  # "razorpay", "manual_utr"


class OrderResponse(BaseModel):
    """Order response schema"""
    id: str = Field(..., alias="_id")
    order_number: str
    customer_id: str
    shop_id: str
    items: List[OrderItemResponse]
    subtotal: float
    delivery_fee: float
    platform_fee: float
    tax: float
    total_amount: float
    status: str
    payment_id: Optional[str]
    estimated_delivery_time: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class PaymentCreate(BaseModel):
    """Payment creation schema"""
    order_id: str
    payment_method: str


class RazorpayWebhook(BaseModel):
    """Razorpay webhook schema"""
    event: str
    payload: dict


class ManualUTRVerify(BaseModel):
    """Manual UTR verification schema"""
    order_id: str
    utr_number: str
    screenshot_url: str


class ReviewBase(BaseModel):
    """Base review schema"""
    rating: float = Field(..., ge=1, le=5)
    title: str
    content: str


class ReviewCreate(ReviewBase):
    """Review creation schema"""
    product_id: Optional[str] = None
    shop_id: Optional[str] = None


class ReviewResponse(ReviewBase):
    """Review response schema"""
    id: str = Field(..., alias="_id")
    customer_id: str
    is_approved: bool
    shopkeeper_reply: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class TicketCreate(BaseModel):
    """Ticket creation schema"""
    category: str
    phone_number: str
    title: str
    description: str
    order_id: Optional[str] = None


class TicketMessageCreate(BaseModel):
    """Ticket message creation schema"""
    message: str


class TicketResponse(BaseModel):
    """Ticket response schema"""
    id: str = Field(..., alias="_id")
    ticket_number: str
    category: str
    title: str
    description: str
    status: str
    priority: str
    customer_id: str
    phone_number: str
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# Pagination schema
class PaginationParams(BaseModel):
    """Pagination parameters"""
    page: int = Field(1, ge=1)
    page_size: int = Field(10, ge=1, le=100)
    search: Optional[str] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = Field("asc", pattern="^(asc|desc)$")
