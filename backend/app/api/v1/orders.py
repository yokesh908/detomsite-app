"""
Orders API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.schemas import OrderResponse, OrderCreate
from app.models import Order, OrderStatus, Product, Shop, User
from app.api.v1.auth import get_current_user
from typing import List
from bson import ObjectId
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[OrderResponse])
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: str = Query(None),
    current_user: User = Depends(get_current_user)
):
    """List orders"""
    skip = (page - 1) * page_size
    
    query = {"campus_id": current_user.campus_id}
    
    # Filter by user role
    if current_user.role == "customer":
        query["customer_id"] = current_user.id
    elif current_user.role == "shopkeeper":
        # Get shops owned by shopkeeper
        shops = await Shop.find({"shopkeeper_id": current_user.id}).to_list()
        shop_ids = [shop.id for shop in shops]
        query["shop_id"] = {"$in": shop_ids}
    
    if status_filter:
        query["status"] = status_filter
    
    orders = await Order.find(query).skip(skip).limit(page_size).to_list()
    return orders


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new order"""
    try:
        # Verify shop exists
        shop = await Shop.get(ObjectId(data.shop_id))
        if not shop:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shop not found"
            )
        
        # Calculate order totals
        subtotal = 0
        order_items = []
        
        for item in data.items:
            product = await Product.get(ObjectId(item.product_id))
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product {item.product_id} not found"
                )
            
            item_total = product.price * item.quantity
            subtotal += item_total
            
            order_items.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": item.quantity,
                "price": product.price,
                "variant_selections": item.variant_selections,
                "addon_selections": item.addon_selections
            })
        
        # Calculate fees — flat ₹10 per order admin commission (no tax, no delivery)
        delivery_fee = 0
        platform_fee = 10  # flat ₹10 per order
        tax = 0
        total_amount = subtotal + platform_fee
        
        # Generate order number
        order_number = f"ORD{ObjectId()}"
        
        order = Order(
            campus_id=current_user.campus_id,
            customer_id=current_user.id,
            shop_id=ObjectId(data.shop_id),
            order_number=order_number,
            items=order_items,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            platform_fee=platform_fee,
            tax=tax,
            total_amount=total_amount,
            status=OrderStatus.DRAFT,
            payment_method=data.payment_method,
            special_instructions=data.special_instructions,
            estimated_delivery_time=datetime.utcnow() + timedelta(
                minutes=shop.delivery_time_minutes
            )
        )
        
        await order.save()
        logger.info(f"Order created: {order.order_number}")
        return order
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get order details"""
    try:
        order = await Order.get(ObjectId(order_id))
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        # Verify access
        if order.customer_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this order"
            )
        
        return order
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid order ID"
        )


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    current_user: User = Depends(get_current_user)
):
    """Cancel order"""
    try:
        order = await Order.get(ObjectId(order_id))
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        # Verify ownership
        if order.customer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to cancel this order"
            )
        
        # Check if order can be cancelled
        if order.status in [OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.COMPLETED]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This order cannot be cancelled"
            )
        
        order.status = OrderStatus.CANCELLED
        order.cancelled_by = "customer"
        await order.save()
        
        logger.info(f"Order cancelled: {order.order_number}")
        return {"message": "Order cancelled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid order ID"
        )
