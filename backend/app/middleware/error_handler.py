"""
Error handling middleware
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
import logging
import uuid

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware for error handling"""
    
    async def dispatch(self, request: Request, call_next):
        """Process request and handle errors"""
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(
                f"Unhandled error - Request ID: {request_id}, "
                f"Path: {request.url.path}, Error: {str(e)}"
            )
            
            # Don't expose internal errors in production
            error_message = str(e) if settings.DEBUG else "Internal Server Error"
            
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": error_message,
                    "request_id": request_id
                }
            )


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests"""
    
    async def dispatch(self, request: Request, call_next):
        """Log request and response"""
        logger.info(f"{request.method} {request.url.path}")
        
        response = await call_next(request)
        
        logger.info(f"Response status: {response.status_code}")
        return response
