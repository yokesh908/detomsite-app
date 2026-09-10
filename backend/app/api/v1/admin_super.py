"""
Super Admin routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.models import User, Campus, AuditLog, UserRole, FeatureFlag, Setting
from app.api.v1.auth import get_current_user
from typing import List
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


async def verify_super_admin(current_user: User = Depends(get_current_user)):
    """Verify that user is a super admin"""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can access this resource"
        )
    return current_user


@router.get("/campuses")
async def list_all_campuses(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(verify_super_admin)
):
    """List all campuses"""
    skip = (page - 1) * page_size
    
    campuses = await Campus.find().skip(skip).limit(page_size).to_list()
    return campuses


@router.get("/admins")
async def list_campus_admins(
    campus_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(verify_super_admin)
):
    """List admins for a campus"""
    skip = (page - 1) * page_size
    
    admins = await User.find({
        "campus_id": ObjectId(campus_id),
        "role": UserRole.ADMIN
    }).skip(skip).limit(page_size).to_list()
    
    return admins


@router.post("/admins")
async def create_campus_admin(
    campus_id: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    current_user: User = Depends(verify_super_admin)
):
    """Create new campus admin"""
    try:
        from app.core.security import hash_password
        
        # Check if admin already exists
        existing = await User.find_one(User.email == email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin already exists"
            )
        
        admin = User(
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=UserRole.ADMIN,
            campus_id=ObjectId(campus_id),
            email_verified=True
        )
        
        await admin.save()
        logger.info(f"Admin created for campus: {campus_id}")
        return {"message": "Admin created successfully"}
    except Exception as e:
        logger.error(f"Error creating admin: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error creating admin"
        )


@router.get("/audit-logs")
async def get_audit_logs(
    campus_id: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(verify_super_admin)
):
    """Get audit logs"""
    skip = (page - 1) * page_size
    
    query = {}
    if campus_id:
        query["campus_id"] = ObjectId(campus_id)
    
    logs = await AuditLog.find(query).skip(skip).limit(page_size).to_list()
    return logs


@router.get("/feature-flags")
async def list_feature_flags(
    campus_id: str = Query(None),
    current_user: User = Depends(verify_super_admin)
):
    """List feature flags"""
    query = {}
    if campus_id:
        query["campus_id"] = ObjectId(campus_id)
    else:
        query["campus_id"] = None
    
    flags = await FeatureFlag.find(query).to_list()
    return flags


@router.post("/feature-flags")
async def create_feature_flag(
    name: str,
    enabled: bool,
    percentage: float = 0.0,
    campus_id: str = Query(None),
    current_user: User = Depends(verify_super_admin)
):
    """Create feature flag"""
    try:
        flag = FeatureFlag(
            name=name,
            enabled=enabled,
            percentage=percentage,
            campus_id=ObjectId(campus_id) if campus_id else None
        )
        
        await flag.save()
        logger.info(f"Feature flag created: {name}")
        return {"message": "Feature flag created"}
    except Exception as e:
        logger.error(f"Error creating feature flag: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error creating feature flag"
        )


@router.get("/settings")
async def get_platform_settings(
    current_user: User = Depends(verify_super_admin)
):
    """Get platform settings"""
    settings = await Setting.find({"campus_id": None}).to_list()
    return settings


@router.get("/statistics")
async def get_platform_statistics(
    current_user: User = Depends(verify_super_admin)
):
    """Get platform-wide statistics"""
    try:
        from app.models import Order, User, Campus
        
        total_users = await User.find().count()
        total_campuses = await Campus.find().count()
        total_orders = await Order.find().count()
        
        return {
            "total_users": total_users,
            "total_campuses": total_campuses,
            "total_orders": total_orders
        }
    except Exception as e:
        logger.error(f"Error getting platform statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error retrieving statistics"
        )
