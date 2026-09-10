"""
Product service for product operations
"""
from app.models import Product, Shop
from typing import Tuple, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class ProductService:
    """Product service"""
    
    @staticmethod
    async def check_inventory(product_id: str, quantity: int) -> bool:
        """Check if product has sufficient inventory"""
        try:
            product = await Product.get(ObjectId(product_id))
            if not product:
                return False
            
            return product.inventory_count >= quantity and product.is_available
        except Exception as e:
            logger.error(f"Error checking inventory: {e}")
            return False
    
    @staticmethod
    async def decrease_inventory(
        product_id: str,
        quantity: int
    ) -> Tuple[bool, Optional[str]]:
        """Decrease product inventory"""
        try:
            product = await Product.get(ObjectId(product_id))
            if not product:
                return False, "Product not found"
            
            if product.inventory_count < quantity:
                return False, "Insufficient inventory"
            
            product.inventory_count -= quantity
            
            # Update availability
            if product.inventory_count == 0:
                product.is_available = False
            
            await product.save()
            logger.info(f"Inventory decreased for product: {product.name}")
            return True, None
        except Exception as e:
            logger.error(f"Error decreasing inventory: {e}")
            return False, str(e)
    
    @staticmethod
    async def increase_inventory(
        product_id: str,
        quantity: int
    ) -> Tuple[bool, Optional[str]]:
        """Increase product inventory (for refunds, returns, etc.)"""
        try:
            product = await Product.get(ObjectId(product_id))
            if not product:
                return False, "Product not found"
            
            product.inventory_count += quantity
            product.is_available = True
            
            await product.save()
            logger.info(f"Inventory increased for product: {product.name}")
            return True, None
        except Exception as e:
            logger.error(f"Error increasing inventory: {e}")
            return False, str(e)
    
    @staticmethod
    async def get_bestsellers(shop_id: str, limit: int = 10) -> list:
        """Get bestselling products for a shop"""
        try:
            products = await Product.find(
                {"shop_id": ObjectId(shop_id), "is_bestseller": True}
            ).limit(limit).to_list()
            return products
        except Exception as e:
            logger.error(f"Error getting bestsellers: {e}")
            return []
    
    @staticmethod
    async def get_recommended_products(shop_id: str, limit: int = 10) -> list:
        """Get recommended products for a shop"""
        try:
            products = await Product.find(
                {"shop_id": ObjectId(shop_id), "is_recommended": True}
            ).limit(limit).to_list()
            return products
        except Exception as e:
            logger.error(f"Error getting recommended products: {e}")
            return []
