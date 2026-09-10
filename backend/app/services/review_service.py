"""
Review service for reviews and ratings
"""
from app.models import Review, Product, Shop
from typing import Tuple, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class ReviewService:
    """Review service"""
    
    @staticmethod
    async def create_review(
        customer_id: str,
        campus_id: str,
        rating: float,
        title: str,
        content: str,
        shop_id: Optional[str] = None,
        product_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[Review]]:
        """Create a new review"""
        try:
            review = Review(
                customer_id=ObjectId(customer_id),
                campus_id=ObjectId(campus_id),
                rating=rating,
                title=title,
                content=content,
                shop_id=ObjectId(shop_id) if shop_id else None,
                product_id=ObjectId(product_id) if product_id else None,
                is_approved=False  # Requires moderation
            )
            
            await review.save()
            logger.info(f"Review created by {customer_id}")
            return True, None, review
        except Exception as e:
            logger.error(f"Error creating review: {e}")
            return False, str(e), None
    
    @staticmethod
    async def approve_review(review_id: str) -> Tuple[bool, Optional[str]]:
        """Approve review (admin)"""
        try:
            review = await Review.get(ObjectId(review_id))
            if not review:
                return False, "Review not found"
            
            review.is_approved = True
            await review.save()
            
            # Update product/shop rating
            if review.product_id:
                await ReviewService._update_product_rating(str(review.product_id))
            if review.shop_id:
                await ReviewService._update_shop_rating(str(review.shop_id))
            
            logger.info(f"Review approved: {review_id}")
            return True, None
        except Exception as e:
            logger.error(f"Error approving review: {e}")
            return False, str(e)
    
    @staticmethod
    async def reject_review(review_id: str) -> Tuple[bool, Optional[str]]:
        """Reject review (admin)"""
        try:
            review = await Review.get(ObjectId(review_id))
            if not review:
                return False, "Review not found"
            
            await review.delete()
            logger.info(f"Review rejected: {review_id}")
            return True, None
        except Exception as e:
            logger.error(f"Error rejecting review: {e}")
            return False, str(e)
    
    @staticmethod
    async def _update_product_rating(product_id: str) -> None:
        """Update product rating from reviews"""
        try:
            reviews = await Review.find({
                "product_id": ObjectId(product_id),
                "is_approved": True
            }).to_list()
            
            if not reviews:
                return
            
            total_rating = sum(review.rating for review in reviews)
            average_rating = total_rating / len(reviews)
            
            product = await Product.get(ObjectId(product_id))
            if product:
                product.rating = round(average_rating, 2)
                product.total_reviews = len(reviews)
                await product.save()
        except Exception as e:
            logger.error(f"Error updating product rating: {e}")
    
    @staticmethod
    async def _update_shop_rating(shop_id: str) -> None:
        """Update shop rating from reviews"""
        try:
            reviews = await Review.find({
                "shop_id": ObjectId(shop_id),
                "is_approved": True
            }).to_list()
            
            if not reviews:
                return
            
            total_rating = sum(review.rating for review in reviews)
            average_rating = total_rating / len(reviews)
            
            shop = await Shop.get(ObjectId(shop_id))
            if shop:
                shop.rating = round(average_rating, 2)
                shop.total_reviews = len(reviews)
                await shop.save()
        except Exception as e:
            logger.error(f"Error updating shop rating: {e}")
