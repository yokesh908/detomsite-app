"""
Notification service
"""
from app.models import Notification, NotificationChannel, User
from typing import List
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Notification service"""
    
    @staticmethod
    async def send_notification(
        user_id: str,
        campus_id: str,
        title: str,
        message: str,
        channels: List[str],
        event_type: str,
        related_id: Optional[str] = None
    ) -> bool:
        """Send notification to user"""
        try:
            notification = Notification(
                user_id=ObjectId(user_id),
                campus_id=ObjectId(campus_id),
                title=title,
                message=message,
                channels=[NotificationChannel(c) for c in channels],
                event_type=event_type,
                related_id=related_id,
                is_read=False
            )
            
            await notification.save()
            
            # Send through different channels
            for channel in channels:
                if channel == "push":
                    await NotificationService._send_push_notification(
                        user_id,
                        title,
                        message
                    )
                elif channel == "email":
                    await NotificationService._send_email_notification(
                        user_id,
                        title,
                        message
                    )
            
            logger.info(f"Notification sent to user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False
    
    @staticmethod
    async def _send_push_notification(
        user_id: str,
        title: str,
        message: str
    ) -> None:
        """Send push notification"""
        try:
            user = await User.get(ObjectId(user_id))
            if not user or not user.device_tokens:
                return
            
            # TODO: Integrate with FCM or similar service
            logger.info(f"Push notification sent to user: {user_id}")
        except Exception as e:
            logger.error(f"Error sending push notification: {e}")
    
    @staticmethod
    async def _send_email_notification(
        user_id: str,
        title: str,
        message: str
    ) -> None:
        """Send email notification"""
        try:
            user = await User.get(ObjectId(user_id))
            if not user:
                return
            
            # TODO: Integrate with email service
            logger.info(f"Email notification sent to user: {user.email}")
        except Exception as e:
            logger.error(f"Error sending email notification: {e}")
    
    @staticmethod
    async def mark_as_read(notification_id: str) -> bool:
        """Mark notification as read"""
        try:
            notification = await Notification.get(ObjectId(notification_id))
            if not notification:
                return False
            
            notification.is_read = True
            notification.read_at = datetime.utcnow()
            await notification.save()
            
            return True
        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            return False


from typing import Optional
