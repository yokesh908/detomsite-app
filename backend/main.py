"""
DETOMSITE Backend - Entry Point
"""
if __name__ == "__main__":
    from app.main import app
    import uvicorn
    from app.core.config import settings
    
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
