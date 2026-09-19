"""
Authentication service
"""
from app.models import User, UserRole, UserStatus, Campus
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token
from app.core.config import settings
from typing import Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


async def init_default_super_admin():
    """Initialize default super admin on first startup"""
    try:
        # Check if super admin exists
        existing_super_admin = await User.find_one(
            User.role == UserRole.SUPER_ADMIN
        )
        
        if existing_super_admin:
            logger.info("Super admin already exists")
            return
        
        # Create default super admin
        password_hash = hash_password(settings.DEFAULT_SUPER_ADMIN_PASSWORD)
        super_admin = User(
            email=settings.DEFAULT_SUPER_ADMIN_EMAIL,
            password_hash=password_hash,
            first_name="Super",
            last_name="Admin",
            role=UserRole.SUPER_ADMIN,
            status=UserStatus.ACTIVE,
            email_verified=True,
            force_password_change=True,  # Force change on first login
        )
        
        await super_admin.save()
        logger.info(f"Default super admin created: {settings.DEFAULT_SUPER_ADMIN_EMAIL}")
    except Exception as e:
        logger.error(f"Error initializing default super admin: {e}")


async def authenticate_user(
    email: str,
    password: str
) -> Optional[User]:
    """Authenticate user by email and password"""
    try:
        user = await User.find_one(User.email == email)
        if not user:
            return None
        
        if not verify_password(password, user.password_hash):
            return None
        
        # Update last login
        user.last_login = datetime.utcnow()
        await user.save()
        
        return user
    except Exception as e:
        logger.error(f"Error authenticating user: {e}")
        return None


async def register_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role: UserRole,
    phone_number: Optional[str] = None,
    campus_id: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[User]]:
    """Register a new user"""
    try:
        # Check if user already exists
        existing_user = await User.find_one(User.email == email)
        if existing_user:
            return False, "User already exists", None
        
        # Create new user
        password_hash = hash_password(password)
        user = User(
            email=email,
            password_hash=password_hash,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
            role=role,
            status=UserStatus.ACTIVE,
            campus_id=campus_id,
        )
        
        await user.save()
        logger.info(f"User registered: {email}")
        
        return True, None, user
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        return False, str(e), None


async def create_tokens(user: User) -> dict:
    """Create access and refresh tokens for user"""
    try:
        data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "campus_id": str(user.campus_id) if user.campus_id else None,
        }
        
        access_token = create_access_token(data)
        refresh_token = create_refresh_token(data)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
    except Exception as e:
        logger.error(f"Error creating tokens: {e}")
        return {}


async def update_user_password(
    user_id: str,
    old_password: str,
    new_password: str
) -> Tuple[bool, Optional[str]]:
    """Update user password"""
    try:
        from bson import ObjectId
        user = await User.get(ObjectId(user_id))
        
        if not user:
            return False, "User not found"
        
        if not verify_password(old_password, user.password_hash):
            return False, "Invalid current password"
        
        user.password_hash = hash_password(new_password)
        user.force_password_change = False
        await user.save()
        
        logger.info(f"Password updated for user: {user.email}")
        return True, None
    except Exception as e:
        logger.error(f"Error updating password: {e}")
        return False, str(e)


async def reset_password(
    email: str,
    reset_token: str,
    new_password: str
) -> Tuple[bool, Optional[str]]:
    """Reset user password using reset token"""
    try:
        user = await User.find_one(User.email == email)
        
        if not user:
            return False, "User not found"
        
        # TODO: Implement reset token verification
        
        user.password_hash = hash_password(new_password)
        await user.save()
        
        logger.info(f"Password reset for user: {email}")
        return True, None
    except Exception as e:
        logger.error(f"Error resetting password: {e}")
        return False, str(e)
