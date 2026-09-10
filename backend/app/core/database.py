"""
Database connection and session management
"""
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from beanie import init_beanie
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

db_client: AsyncIOMotorClient | None = None
database: AsyncIOMotorDatabase | None = None


async def connect_to_mongo():
    """Connect to MongoDB"""
    global db_client, database
    try:
        db_client = AsyncIOMotorClient(settings.MONGODB_URL)
        database = db_client[settings.DATABASE_NAME]
        
        # Initialize Beanie with all models
        from app.models import (
            User, Campus, Shop, Product, Category, Order,
            Payment, Review, Notification, Ticket, AuditLog,
            Wallet, DeliveryPartner, FeatureFlag, Setting
        )
        
        await init_beanie(
            database=database,
            document_models=[
                User, Campus, Shop, Product, Category, Order,
                Payment, Review, Notification, Ticket, AuditLog,
                Wallet, DeliveryPartner, FeatureFlag, Setting
            ]
        )
        logger.info("Connected to MongoDB")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise


async def close_mongo_connection():
    """Close MongoDB connection"""
    global db_client
    if db_client:
        db_client.close()
        logger.info("Disconnected from MongoDB")


def get_database() -> Any:
    """Get the database instance"""
    return database
