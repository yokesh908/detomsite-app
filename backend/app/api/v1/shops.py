"""
Shops API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.schemas import ShopResponse, ShopCreate, ShopUpdate
from app.models import Shop, User, UserRole
from app.api.v1.auth import get_current_user
from typing import List
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[ShopResponse])
async def list_shops(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    campus_id: str = Query(None),
    current_user: User = Depends(get_current_user)
):
    """List shops"""
    skip = (page - 1) * page_size
    
    query = {}
    if campus_id:
        query["campus_id"] = ObjectId(campus_id)
    else:
        query["campus_id"] = current_user.campus_id
    
    shops = await Shop.find(query).skip(skip).limit(page_size).to_list()
    return shops


@router.post("/", response_model=ShopResponse, status_code=status.HTTP_201_CREATED)
async def create_shop(
    data: ShopCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new shop (shopkeeper only)"""
    if current_user.role != UserRole.SHOPKEEPER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only shopkeepers can create shops"
        )
    
    shop = Shop(
        **data.dict(),
        shopkeeper_id=current_user.id,
        campus_id=current_user.campus_id
    )
    await shop.save()
    
    logger.info(f"Shop created: {shop.name}")
    return shop


@router.get("/{shop_id}", response_model=ShopResponse)
async def get_shop(
    shop_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get shop details"""
    try:
        shop = await Shop.get(ObjectId(shop_id))
        if not shop:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shop not found"
            )
        return shop
    except Exception as e:
        logger.error(f"Error getting shop: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid shop ID"
        )


@router.put("/{shop_id}", response_model=ShopResponse)
async def update_shop(
    shop_id: str,
    data: ShopUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update shop"""
    try:
        shop = await Shop.get(ObjectId(shop_id))
        if not shop:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shop not found"
            )
        
        # Verify ownership
        if shop.shopkeeper_id != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to update this shop"
            )
        
        # Update fields
        shop_data = data.dict(exclude_unset=True)
        for field, value in shop_data.items():
            setattr(shop, field, value)
        
        await shop.save()
        logger.info(f"Shop updated: {shop.name}")
        return shop
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating shop: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid shop ID"
        )
