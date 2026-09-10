"""
Shop service for shop operations
"""
from app.models import Shop, Product, User, UserRole
from typing import Tuple, Optional, List
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class ShopService:
    """Shop service"""
    
    @staticmethod
    async def create_shop(
        name: str,
        shopkeeper_id: str,
        campus_id: str,
        **kwargs
    ) -> Tuple[bool, Optional[str], Optional[Shop]]:
        """Create a new shop"""
        try:
            # Check if shop already exists for shopkeeper
            existing_shop = await Shop.find_one(
                Shop.shopkeeper_id == ObjectId(shopkeeper_id)
            )
            
            if existing_shop:
                return False, "Shopkeeper already has a shop", None
            
            shop = Shop(
                shopkeeper_id=ObjectId(shopkeeper_id),
                campus_id=ObjectId(campus_id),
                name=name,
                **kwargs
            )
            
            await shop.save()
            logger.info(f"Shop created: {name}")
            return True, None, shop
        except Exception as e:
            logger.error(f"Error creating shop: {e}")
            return False, str(e), None
    
    @staticmethod
    async def get_shop_statistics(shop_id: str) -> dict:
        """Get shop statistics"""
        try:
            shop = await Shop.get(ObjectId(shop_id))
            if not shop:
                return {}
            
            # Get total products
            products = await Product.find({"shop_id": shop.id}).to_list()
            
            # Get shop rating from reviews
            # TODO: Calculate from reviews collection
            
            return {
                "shop_id": str(shop.id),
                "name": shop.name,
                "total_products": len(products),
                "rating": shop.rating,
                "total_reviews": shop.total_reviews,
                "status": shop.status,
                "is_verified": shop.is_verified
            }
        except Exception as e:
            logger.error(f"Error getting shop statistics: {e}")
            return {}
    
    @staticmethod
    async def update_shop_status(
        shop_id: str,
        status: str
    ) -> Tuple[bool, Optional[str]]:
        """Update shop status"""
        try:
            shop = await Shop.get(ObjectId(shop_id))
            if not shop:
                return False, "Shop not found"
            
            shop.status = status
            await shop.save()
            
            logger.info(f"Shop status updated: {shop.name} -> {status}")
            return True, None
        except Exception as e:
            logger.error(f"Error updating shop status: {e}")
            return False, str(e)
    
    @staticmethod
    async def verify_shop(shop_id: str) -> Tuple[bool, Optional[str]]:
        """Verify shop (admin only)"""
        try:
            shop = await Shop.get(ObjectId(shop_id))
            if not shop:
                return False, "Shop not found"
            
            shop.is_verified = True
            await shop.save()
            
            logger.info(f"Shop verified: {shop.name}")
            return True, None
        except Exception as e:
            logger.error(f"Error verifying shop: {e}")
            return False, str(e)
