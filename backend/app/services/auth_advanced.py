"""
Advanced authentication service with email verification, device tracking, etc.
"""
from app.models import User, AuditLog, UserStatus
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token
from app.core.config import settings
from app.services.email_service import EmailService
from typing import Optional, Tuple
from datetime import datetime, timedelta
from bson import ObjectId
import logging
import secrets
import string

logger = logging.getLogger(__name__)


class AdvancedAuthService:
    """Advanced authentication service"""
    
    @staticmethod
    async def create_email_verification_token(user_id: str) -> str:
        """Create email verification token"""
        token = secrets.token_urlsafe(32)
        # TODO: Store token in Redis with 24h expiry
        return token
    
    @staticmethod
    async def verify_email(user_id: str, token: str) -> Tuple[bool, Optional[str]]:
        """Verify user email with token"""
        try:
            # TODO: Verify token from Redis
            user = await User.get(ObjectId(user_id))
            if not user:
                return False, "User not found"
            
            user.email_verified = True
            await user.save()
            
            logger.info(f"Email verified for user: {user.email}")
            return True, None
        except Exception as e:
            logger.error(f"Error verifying email: {e}")
            return False, str(e)
    
    @staticmethod
    async def create_password_reset_token(email: str) -> Tuple[bool, Optional[str]]:
        """Create password reset token"""
        try:
            user = await User.find_one(User.email == email)
            if not user:
                return False, "User not found"
            
            token = secrets.token_urlsafe(32)
            # TODO: Store token in Redis with 1h expiry
            
            # Send reset email
            reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
            await EmailService.send_password_reset_email(email, reset_link)
            
            logger.info(f"Password reset token created for user: {email}")
            return True, None
        except Exception as e:
            logger.error(f"Error creating password reset token: {e}")
            return False, str(e)
    
    @staticmethod
    async def add_device_token(user_id: str, device_token: str) -> bool:
        """Add device token for push notifications"""
        try:
            user = await User.get(ObjectId(user_id))
            if not user:
                return False
            
            if device_token not in user.device_tokens:
                user.device_tokens.append(device_token)
                await user.save()
                logger.info(f"Device token added for user: {user.email}")
            
            return True
        except Exception as e:
            logger.error(f"Error adding device token: {e}")
            return False
    
    @staticmethod
    async def remove_device_token(user_id: str, device_token: str) -> bool:
        """Remove device token"""
        try:
            user = await User.get(ObjectId(user_id))
            if not user:
                return False
            
            if device_token in user.device_tokens:
                user.device_tokens.remove(device_token)
                await user.save()
                logger.info(f"Device token removed for user: {user.email}")
            
            return True
        except Exception as e:
            logger.error(f"Error removing device token: {e}")
            return False
    
    @staticmethod
    async def log_audit(
        user_id: str,
        campus_id: str,
        action: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        old_value: Optional[dict] = None,
        new_value: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Log audit trail"""
        try:
            audit_log = AuditLog(
                campus_id=ObjectId(campus_id) if campus_id else None,
                user_id=ObjectId(user_id),
                action=action,
                entity_type=entity_type,
                entity_id=ObjectId(entity_id) if entity_id else None,
                old_value=old_value,
                new_value=new_value,
                ip_address=ip_address,
                user_agent=user_agent,
                created_at=datetime.utcnow()
            )
            await audit_log.save()
            logger.info(f"Audit log created: {action}")
            return True
        except Exception as e:
            logger.error(f"Error creating audit log: {e}")
            return False
    
    @staticmethod
    async def suspend_user(user_id: str, reason: str) -> Tuple[bool, Optional[str]]:
        """Suspend user account"""
        try:
            user = await User.get(ObjectId(user_id))
            if not user:
                return False, "User not found"
            
            user.status = UserStatus.SUSPENDED
            await user.save()
            
            logger.info(f"User suspended: {user.email}, Reason: {reason}")
            return True, None
        except Exception as e:
            logger.error(f"Error suspending user: {e}")
            return False, str(e)
    
    @staticmethod
    async def unsuspend_user(user_id: str) -> Tuple[bool, Optional[str]]:
        """Unsuspend user account"""
        try:
            user = await User.get(ObjectId(user_id))
            if not user:
                return False, "User not found"
            
            user.status = UserStatus.ACTIVE
            await user.save()
            
            logger.info(f"User unsuspended: {user.email}")
            return True, None
        except Exception as e:
            logger.error(f"Error unsuspending user: {e}")
            return False, str(e)
