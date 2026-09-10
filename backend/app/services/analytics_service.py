"""
Analytics service for dashboards
"""
from app.models import Order, OrderStatus, Payment, PaymentStatus, Review, User, UserRole
from datetime import datetime, timedelta
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Analytics service"""
    
    @staticmethod
    async def get_customer_analytics(customer_id: str) -> dict:
        """Get customer analytics"""
        try:
            orders = await Order.find({
                "customer_id": ObjectId(customer_id),
                "status": OrderStatus.COMPLETED
            }).to_list()
            
            total_spent = sum(order.total_amount for order in orders)
            total_orders = len(orders)
            average_order_value = total_spent / total_orders if total_orders > 0 else 0
            
            return {
                "total_orders": total_orders,
                "total_spent": total_spent,
                "average_order_value": average_order_value,
                "favorite_shops": await AnalyticsService._get_favorite_shops(
                    customer_id
                )
            }
        except Exception as e:
            logger.error(f"Error getting customer analytics: {e}")
            return {}
    
    @staticmethod
    async def get_shopkeeper_analytics(shopkeeper_id: str) -> dict:
        """Get shopkeeper analytics"""
        try:
            # Get today's orders
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
            today_orders = await Order.find({
                "shopkeeper_id": ObjectId(shopkeeper_id),
                "created_at": {"$gte": today_start}
            }).to_list()
            
            today_revenue = sum(order.total_amount for order in today_orders)
            
            # Get total revenue (all time)
            all_orders = await Order.find({
                "shopkeeper_id": ObjectId(shopkeeper_id),
                "status": OrderStatus.COMPLETED
            }).to_list()
            
            total_revenue = sum(order.total_amount for order in all_orders)
            
            return {
                "today_orders": len(today_orders),
                "today_revenue": today_revenue,
                "total_revenue": total_revenue,
                "total_orders": len(all_orders)
            }
        except Exception as e:
            logger.error(f"Error getting shopkeeper analytics: {e}")
            return {}
    
    @staticmethod
    async def get_campus_analytics(campus_id: str) -> dict:
        """Get campus analytics"""
        try:
            orders = await Order.find({
                "campus_id": ObjectId(campus_id),
                "status": OrderStatus.COMPLETED
            }).to_list()
            
            total_revenue = sum(order.total_amount for order in orders)
            total_orders = len(orders)
            total_customers = len(set(order.customer_id for order in orders))
            
            return {
                "total_orders": total_orders,
                "total_revenue": total_revenue,
                "total_customers": total_customers,
                "average_order_value": total_revenue / total_orders if total_orders > 0 else 0
            }
        except Exception as e:
            logger.error(f"Error getting campus analytics: {e}")
            return {}
    
    @staticmethod
    async def _get_favorite_shops(customer_id: str) -> list:
        """Get customer's favorite shops based on order history"""
        try:
            orders = await Order.find({
                "customer_id": ObjectId(customer_id)
            }).to_list()
            
            shop_order_count = {}
            for order in orders:
                shop_id = str(order.shop_id)
                shop_order_count[shop_id] = shop_order_count.get(shop_id, 0) + 1
            
            # Sort by order count
            favorite_shops = sorted(
                shop_order_count.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            return [{"shop_id": shop_id, "order_count": count}
                    for shop_id, count in favorite_shops]
        except Exception as e:
            logger.error(f"Error getting favorite shops: {e}")
            return []
