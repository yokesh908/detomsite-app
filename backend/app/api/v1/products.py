"""
Products API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.schemas import ProductResponse, ProductCreate, ProductUpdate
from app.models import Product, Shop, User, UserRole
from app.api.v1.auth import get_current_user
from typing import List
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[ProductResponse])
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    shop_id: str = Query(None),
    campus_id: str = Query(None),
    search: str = Query(None),
    current_user: User = Depends(get_current_user)
):
    """List products with search and filters"""
    skip = (page - 1) * page_size
    
    query = {}
    if campus_id:
        query["campus_id"] = ObjectId(campus_id)
    elif current_user.campus_id:
        query["campus_id"] = current_user.campus_id
    
    if shop_id:
        query["shop_id"] = ObjectId(shop_id)
    
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    
    products = await Product.find(query).skip(skip).limit(page_size).to_list()
    return products


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    shop_id: str = Query(...),
    current_user: User = Depends(get_current_user)
):
    """Create a new product"""
    try:
        shop = await Shop.get(ObjectId(shop_id))
        if not shop:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shop not found"
            )
        
        # Verify shop ownership
        if shop.shopkeeper_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to add products to this shop"
            )
        
        product = Product(
            **data.dict(),
            shop_id=ObjectId(shop_id),
            campus_id=shop.campus_id
        )
        await product.save()
        
        logger.info(f"Product created: {product.name}")
        return product
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get product details"""
    try:
        product = await Product.get(ObjectId(product_id))
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        return product
    except Exception as e:
        logger.error(f"Error getting product: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid product ID"
        )


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    data: ProductUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update product"""
    try:
        product = await Product.get(ObjectId(product_id))
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Verify ownership
        shop = await Shop.get(product.shop_id)
        if shop.shopkeeper_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to update this product"
            )
        
        # Update fields
        product_data = data.dict(exclude_unset=True)
        for field, value in product_data.items():
            setattr(product, field, value)
        
        await product.save()
        logger.info(f"Product updated: {product.name}")
        return product
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating product: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid product ID"
        )


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete product"""
    try:
        product = await Product.get(ObjectId(product_id))
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Verify ownership
        shop = await Shop.get(product.shop_id)
        if shop.shopkeeper_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this product"
            )
        
        await product.delete()
        logger.info(f"Product deleted: {product.name}")
        return {"message": "Product deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid product ID"
        )
