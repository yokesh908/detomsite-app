"""
Support Tickets API routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query
from app.schemas import TicketResponse, TicketCreate, TicketMessageCreate
from app.models import Ticket, TicketStatus, User
from app.api.v1.auth import get_current_user
from typing import List
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[TicketResponse])
async def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: str = Query(None),
    current_user: User = Depends(get_current_user)
):
    """List support tickets"""
    skip = (page - 1) * page_size
    
    query = {"campus_id": current_user.campus_id}
    
    if current_user.role == "customer":
        query["customer_id"] = current_user.id
    
    if status_filter:
        query["status"] = status_filter
    
    tickets = await Ticket.find(query).skip(skip).limit(page_size).to_list()
    return tickets


@router.post("/", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    data: TicketCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new support ticket"""
    try:
        ticket_number = f"TKT{ObjectId()}"
        
        ticket = Ticket(
            campus_id=current_user.campus_id,
            ticket_number=ticket_number,
            customer_id=current_user.id,
            **data.dict()
        )
        
        await ticket.save()
        logger.info(f"Ticket created: {ticket_number}")
        return ticket
    except Exception as e:
        logger.error(f"Error creating ticket: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get ticket details"""
    try:
        ticket = await Ticket.get(ObjectId(ticket_id))
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        
        # Verify access
        if ticket.customer_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this ticket"
            )
        
        return ticket
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ticket: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid ticket ID"
        )


@router.post("/{ticket_id}/message")
async def add_ticket_message(
    ticket_id: str,
    data: TicketMessageCreate,
    current_user: User = Depends(get_current_user)
):
    """Add message to ticket"""
    try:
        ticket = await Ticket.get(ObjectId(ticket_id))
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )
        
        message = {
            "sender_id": current_user.id,
            "sender_type": current_user.role,
            "message": data.message,
            "created_at": datetime.utcnow()
        }
        
        ticket.messages.append(message)
        await ticket.save()
        
        logger.info(f"Message added to ticket: {ticket.ticket_number}")
        return {"message": "Message added successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding ticket message: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request"
        )
