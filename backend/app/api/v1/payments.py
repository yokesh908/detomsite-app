"""
Payments API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.schemas import PaymentCreate, RazorpayWebhook, ManualUTRVerify
from app.models import Payment, PaymentStatus, Order, OrderStatus, User
from app.api.v1.auth import get_current_user
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/create-razorpay-order")
async def create_razorpay_order(
    data: PaymentCreate,
    current_user: User = Depends(get_current_user)
):
    """Create Razorpay order for payment"""
    try:
        order = await Order.get(ObjectId(data.order_id))
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        # Verify customer
        if order.customer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to pay for this order"
            )
        
        # TODO: Integrate with Razorpay API
        # For now, create a payment record
        payment = Payment(
            campus_id=current_user.campus_id,
            order_id=order.id,
            customer_id=current_user.id,
            amount=order.total_amount,
            payment_method="razorpay",
            status=PaymentStatus.PENDING
        )
        
        await payment.save()
        
        # Return Razorpay order details (mock for now)
        return {
            "razorpay_order_id": f"order_{ObjectId()}",
            "amount": order.total_amount,
            "currency": "INR",
            "customer_id": str(current_user.id),
            "description": f"Order {order.order_number}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating Razorpay order: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )


@router.post("/razorpay-webhook")
async def razorpay_webhook(
    data: RazorpayWebhook
):
    """Handle Razorpay webhook"""
    try:
        # TODO: Verify webhook signature
        
        if data.event == "payment.authorized":
            # Update payment status
            payment_id = data.payload.get("payment", {}).get("id")
            order_id = data.payload.get("order", {}).get("id")
            
            # TODO: Update payment and order status
            logger.info(f"Payment authorized: {payment_id}")
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling Razorpay webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook"
        )


@router.post("/manual-utr-verify")
async def verify_manual_utr(
    data: ManualUTRVerify,
    current_user: User = Depends(get_current_user)
):
    """Verify manual UTR payment"""
    try:
        order = await Order.get(ObjectId(data.order_id))
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        # Verify customer
        if order.customer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to verify this payment"
            )
        
        # Create payment record
        payment = Payment(
            campus_id=current_user.campus_id,
            order_id=order.id,
            customer_id=current_user.id,
            amount=order.total_amount,
            payment_method="manual_utr",
            utr_number=data.utr_number,
            screenshot_url=data.screenshot_url,
            status=PaymentStatus.PENDING
        )
        
        await payment.save()
        
        # Update order status
        order.status = OrderStatus.PAYMENT_VERIFICATION
        order.payment_id = str(payment.id)
        await order.save()
        
        logger.info(f"Manual UTR payment submitted: {data.utr_number}")
        return {"message": "Payment submitted for verification"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying manual UTR: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )


@router.get("/{payment_id}")
async def get_payment(
    payment_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get payment details"""
    try:
        payment = await Payment.get(ObjectId(payment_id))
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found"
            )
        
        # Verify access
        if payment.customer_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this payment"
            )
        
        return payment
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting payment: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment ID"
        )
