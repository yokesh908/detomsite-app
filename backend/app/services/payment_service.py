"""
Payment service for payment operations
"""
from app.models import Payment, PaymentStatus, Order, OrderStatus
from typing import Tuple, Optional
from bson import ObjectId
import logging
import hashlib
import hmac

logger = logging.getLogger(__name__)


class PaymentService:
    """Payment service"""
    
    @staticmethod
    async def verify_razorpay_webhook(
        body: str,
        signature: str,
        webhook_secret: str
    ) -> bool:
        """Verify Razorpay webhook signature"""
        try:
            generated_signature = hmac.new(
                webhook_secret.encode(),
                body.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, generated_signature)
        except Exception as e:
            logger.error(f"Error verifying Razorpay webhook: {e}")
            return False
    
    @staticmethod
    async def handle_razorpay_success(
        razorpay_payment_id: str,
        razorpay_order_id: str,
        razorpay_signature: str,
        order_id: str
    ) -> Tuple[bool, Optional[str]]:
        """Handle successful Razorpay payment"""
        try:
            # Find payment record
            payment = await Payment.find_one({
                "razorpay_order_id": razorpay_order_id
            })
            
            if not payment:
                return False, "Payment record not found"
            
            # Update payment
            payment.razorpay_payment_id = razorpay_payment_id
            payment.razorpay_signature = razorpay_signature
            payment.status = PaymentStatus.SUCCESS
            await payment.save()
            
            # Update order
            order = await Order.get(ObjectId(order_id))
            if order:
                order.status = OrderStatus.CONFIRMED
                order.payment_id = str(payment.id)
                await order.save()
            
            logger.info(f"Razorpay payment processed successfully: {razorpay_payment_id}")
            return True, None
        except Exception as e:
            logger.error(f"Error handling Razorpay success: {e}")
            return False, str(e)
    
    @staticmethod
    async def handle_razorpay_failure(
        razorpay_order_id: str,
        failure_reason: str
    ) -> Tuple[bool, Optional[str]]:
        """Handle failed Razorpay payment"""
        try:
            payment = await Payment.find_one({
                "razorpay_order_id": razorpay_order_id
            })
            
            if not payment:
                return False, "Payment record not found"
            
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = failure_reason
            await payment.save()
            
            logger.info(f"Razorpay payment failed: {razorpay_order_id}")
            return True, None
        except Exception as e:
            logger.error(f"Error handling Razorpay failure: {e}")
            return False, str(e)
    
    @staticmethod
    async def verify_manual_utr(
        payment_id: str,
        verified: bool,
        verified_by_admin: str
    ) -> Tuple[bool, Optional[str]]:
        """Verify manual UTR payment"""
        try:
            payment = await Payment.get(ObjectId(payment_id))
            if not payment:
                return False, "Payment not found"
            
            if verified:
                payment.status = PaymentStatus.SUCCESS
                
                # Update associated order
                order = await Order.find_one({
                    "_id": payment.order_id
                })
                if order:
                    order.status = OrderStatus.CONFIRMED
                    await order.save()
            else:
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = "Manual verification failed"
            
            payment.verified_by_admin = ObjectId(verified_by_admin)
            payment.verified_at = payment.verified_at or datetime.utcnow()
            await payment.save()
            
            logger.info(f"Manual UTR payment verified: {payment.utr_number}")
            return True, None
        except Exception as e:
            logger.error(f"Error verifying manual UTR: {e}")
            return False, str(e)
    
    @staticmethod
    async def process_refund(
        payment_id: str,
        refund_amount: float,
        reason: str
    ) -> Tuple[bool, Optional[str]]:
        """Process refund for payment"""
        try:
            payment = await Payment.get(ObjectId(payment_id))
            if not payment:
                return False, "Payment not found"
            
            if payment.status not in [PaymentStatus.SUCCESS, PaymentStatus.REFUND_PENDING]:
                return False, "Payment cannot be refunded"
            
            payment.status = PaymentStatus.REFUNDED
            await payment.save()
            
            # Update order
            order = await Order.find_one({
                "_id": payment.order_id
            })
            if order:
                order.status = OrderStatus.REFUNDED
                await order.save()
            
            logger.info(f"Refund processed: {payment_id}, Amount: {refund_amount}")
            return True, None
        except Exception as e:
            logger.error(f"Error processing refund: {e}")
            return False, str(e)


from datetime import datetime
