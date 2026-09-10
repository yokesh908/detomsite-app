"""
Reviews API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.schemas import ReviewResponse, ReviewCreate
from app.models import Review, Product, Shop, User
from app.api.v1.auth import get_current_user
from typing import List
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[ReviewResponse])
async def list_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    shop_id: str = Query(None),
    product_id: str = Query(None),
    current_user: User = Depends(get_current_user)
):
    """List reviews"""
    skip = (page - 1) * page_size
    
    query = {"campus_id": current_user.campus_id, "is_approved": True}
    
    if shop_id:
        query["shop_id"] = ObjectId(shop_id)
    if product_id:
        query["product_id"] = ObjectId(product_id)
    
    reviews = await Review.find(query).skip(skip).limit(page_size).to_list()
    return reviews


@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    data: ReviewCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new review"""
    try:
        review = Review(
            campus_id=current_user.campus_id,
            customer_id=current_user.id,
            **data.dict()
        )
        
        await review.save()
        logger.info(f"Review created by {current_user.email}")
        return review
    except Exception as e:
        logger.error(f"Error creating review: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get review details"""
    try:
        review = await Review.get(ObjectId(review_id))
        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found"
            )
        return review
    except Exception as e:
        logger.error(f"Error getting review: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid review ID"
        )
