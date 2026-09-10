"""
Admin routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.models import User, Shop, Payment, PaymentStatus, Review, Order, UserRole
from app.api.v1.auth import get_current_user
from app.services.review_service import ReviewService
from app.services.payment_service import PaymentService
from typing import List
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


async def verify_admin(current_user: User = Depends(get_current_user)):
    """Verify that user is an admin"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access this resource"
        )
    return current_user


@router.get("/vendors")
async def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(verify_admin)
):
    """List all vendors (shopkeepers)"""
    skip = (page - 1) * page_size
    
    vendors = await User.find(
        {"role": UserRole.SHOPKEEPER}
    ).skip(skip).limit(page_size).to_list()
    
    return vendors


@router.post("/vendors/{vendor_id}/approve")
async def approve_vendor(
    vendor_id: str,
    current_user: User = Depends(verify_admin)
):
    """Approve vendor (shopkeeper)"""
    try:
        vendor = await User.get(ObjectId(vendor_id))
        if not vendor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor not found"
            )
        
        # TODO: Implement KYC verification logic
        # Update vendor status
        vendor.email_verified = True
        await vendor.save()
        
        logger.info(f"Vendor approved: {vendor.email}")
        return {"message": "Vendor approved"}
    except Exception as e:
        logger.error(f"Error approving vendor: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid vendor ID"
        )


@router.post("/vendors/{vendor_id}/reject")
async def reject_vendor(
    vendor_id: str,
    reason: str = Query(...),
    current_user: User = Depends(verify_admin)
):
    """Reject vendor"""
    try:
        vendor = await User.get(ObjectId(vendor_id))
        if not vendor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor not found"
            )
        
        vendor.status = "rejected"
        await vendor.save()
        
        # TODO: Send rejection email
        logger.info(f"Vendor rejected: {vendor.email}, Reason: {reason}")
        return {"message": "Vendor rejected"}
    except Exception as e:
        logger.error(f"Error rejecting vendor: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid vendor ID"
        )


@router.get("/payments/pending")
async def list_pending_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(verify_admin)
):
    """List pending manual UTR payments for verification"""
    skip = (page - 1) * page_size
    
    payments = await Payment.find(
        {"status": PaymentStatus.PENDING, "payment_method": "manual_utr"}
    ).skip(skip).limit(page_size).to_list()
    
    return payments


@router.post("/payments/{payment_id}/verify")
async def verify_manual_payment(
    payment_id: str,
    verified: bool = Query(...),
    current_user: User = Depends(verify_admin)
):
    """Verify or reject manual UTR payment"""
    success, error = await PaymentService.verify_manual_utr(
        payment_id,
        verified,
        str(current_user.id)
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )
    
    return {"message": "Payment verified"}


@router.get("/reviews/pending")
async def list_pending_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(verify_admin)
):
    """List pending reviews for moderation"""
    skip = (page - 1) * page_size
    
    reviews = await Review.find(
        {"is_approved": False, "campus_id": current_user.campus_id}
    ).skip(skip).limit(page_size).to_list()
    
    return reviews


@router.post("/reviews/{review_id}/approve")
async def approve_review(
    review_id: str,
    current_user: User = Depends(verify_admin)
):
    """Approve review"""
    success, error = await ReviewService.approve_review(review_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )
    
    return {"message": "Review approved"}


@router.post("/reviews/{review_id}/reject")
async def reject_review(
    review_id: str,
    current_user: User = Depends(verify_admin)
):
    """Reject review"""
    success, error = await ReviewService.reject_review(review_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )
    
    return {"message": "Review rejected"}


@router.get("/statistics")
async def get_admin_statistics(
    current_user: User = Depends(verify_admin)
):
    """Get admin dashboard statistics"""
    try:
        # Get campus-wide statistics
        orders = await Order.find(
            {"campus_id": current_user.campus_id}
        ).to_list()
        
        total_revenue = sum(o.total_amount for o in orders)
        total_orders = len(orders)
        
        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "pending_payments": await Payment.find(
                {"status": PaymentStatus.PENDING}
            ).count(),
            "pending_reviews": await Review.find(
                {"is_approved": False}
            ).count()
        }
    except Exception as e:
        logger.error(f"Error getting admin statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error retrieving statistics"
        )
