"""
Campuses API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.schemas import CampusResponse, CampusCreate, PaginationParams
from app.models import Campus, User, UserRole
from app.api.v1.auth import get_current_user
from typing import List
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


@router.get("/", response_model=List[CampusResponse])
async def list_campuses(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user)
):
    """List campuses"""
    skip = (page - 1) * page_size
    
    campuses = await Campus.find().skip(skip).limit(page_size).to_list()
    return campuses


@router.post("/", response_model=CampusResponse, status_code=status.HTTP_201_CREATED)
async def create_campus(
    data: CampusCreate,
    current_user: User = Depends(verify_super_admin)
):
    """Create a new campus (super admin only)"""
    # Check if campus with same slug exists
    existing = await Campus.find_one(Campus.slug == data.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campus with this slug already exists"
        )
    
    campus = Campus(**data.dict())
    await campus.save()
    
    logger.info(f"Campus created: {campus.name}")
    return campus


@router.get("/{campus_id}", response_model=CampusResponse)
async def get_campus(
    campus_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get campus details"""
    from bson import ObjectId
    try:
        campus = await Campus.get(ObjectId(campus_id))
        if not campus:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campus not found"
            )
        return campus
    except Exception as e:
        logger.error(f"Error getting campus: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campus ID"
        )


@router.put("/{campus_id}", response_model=CampusResponse)
async def update_campus(
    campus_id: str,
    data: CampusCreate,
    current_user: User = Depends(verify_super_admin)
):
    """Update campus (super admin only)"""
    from bson import ObjectId
    try:
        campus = await Campus.get(ObjectId(campus_id))
        if not campus:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campus not found"
            )
        
        # Update fields
        campus_data = data.dict(exclude_unset=True)
        for field, value in campus_data.items():
            setattr(campus, field, value)
        
        await campus.save()
        logger.info(f"Campus updated: {campus.name}")
        return campus
    except Exception as e:
        logger.error(f"Error updating campus: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campus ID"
        )
