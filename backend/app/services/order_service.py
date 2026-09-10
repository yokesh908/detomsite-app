"""
Order service for order operations
"""
from app.models import Order, OrderStatus, Product, Shop, Payment, PaymentStatus
from app.services.product_service import ProductService
from typing import Tuple, Optional, List
from bson import ObjectId
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class OrderService:
    """Order service"""
    
    @staticmethod
    async def calculate_order_total(items: list) -> dict:
        """Calculate order totals (subtotal, fees, tax, total)"""
        try:
            subtotal = 0
            for item in items:
                product = await Product.get(ObjectId(item["product_id"]))
                if product:
                    subtotal += product.price * item["quantity"]
            
            # Only the 5% platform service fee (no tax, no delivery)
            delivery_fee = 0
            platform_fee = subtotal * 0.05  # 5% platform fee
            tax = 0
            total_amount = subtotal + platform_fee
            
            return {
                "subtotal": subtotal,
                "delivery_fee": delivery_fee,
                "platform_fee": platform_fee,
                "tax": tax,
                "total_amount": total_amount
            }
        except Exception as e:
            logger.error(f"Error calculating order total: {e}")
            return {}
    
    @staticmethod
    async def verify_order_items(items: list) -> Tuple[bool, Optional[str]]:
        """Verify all items in order are available"""
        try:
            for item in items:
                product_id = item.get("product_id")
                quantity = item.get("quantity", 0)
                
                has_inventory = await ProductService.check_inventory(
                    product_id,
                    quantity
                )
                
                if not has_inventory:
                    return False, f"Insufficient inventory for product"
            
            return True, None
        except Exception as e:
            logger.error(f"Error verifying order items: {e}")
            return False, str(e)
    
    @staticmethod
    async def reserve_inventory(order_id: str, items: list) -> Tuple[bool, Optional[str]]:
        """Reserve inventory for order"""
        try:
            for item in items:
                success, error = await ProductService.decrease_inventory(
                    item["product_id"],
                    item["quantity"]
                )
                if not success:
                    # Rollback on failure
                    # TODO: Implement rollback mechanism
                    return False, error
            
            logger.info(f"Inventory reserved for order: {order_id}")
            return True, None
        except Exception as e:
            logger.error(f"Error reserving inventory: {e}")
            return False, str(e)
    
    @staticmethod
    async def release_inventory(order_id: str, items: list) -> bool:
        """Release inventory for cancelled order"""
        try:
            for item in items:
                await ProductService.increase_inventory(
                    item["product_id"],
                    item["quantity"]
                )
            
            logger.info(f"Inventory released for order: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Error releasing inventory: {e}")
            return False
    
    @staticmethod
    async def update_order_status(
        order_id: str,
        new_status: str
    ) -> Tuple[bool, Optional[str]]:
        """Update order status"""
        try:
            order = await Order.get(ObjectId(order_id))
            if not order:
                return False, "Order not found"
            
            order.status = new_status
            if new_status == OrderStatus.DELIVERED:
                order.actual_delivery_time = datetime.utcnow()
            
            await order.save()
            logger.info(f"Order status updated: {order.order_number} -> {new_status}")
            return True, None
        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            return False, str(e)
    
    @staticmethod
    async def get_order_statistics(shop_id: str) -> dict:
        """Get order statistics for shop"""
        try:
            # Get total orders
            total_orders = await Order.find(
                {"shop_id": ObjectId(shop_id)}
            ).count()
            
            # Get today's orders
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
            today_orders = await Order.find({
                "shop_id": ObjectId(shop_id),
                "created_at": {"$gte": today_start}
            }).count()
            
            # Get completed orders
            completed_orders = await Order.find({
                "shop_id": ObjectId(shop_id),
                "status": OrderStatus.COMPLETED
            }).count()
            
            return {
                "total_orders": total_orders,
                "today_orders": today_orders,
                "completed_orders": completed_orders
            }
        except Exception as e:
            logger.error(f"Error getting order statistics: {e}")
            return {}
