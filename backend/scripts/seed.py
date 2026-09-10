"""
Database seed script for initial data
"""
import asyncio
from motor.motor_asyncio import AsyncClient
from app.models import Campus, Category, Setting
from app.core.config import settings
from datetime import datetime


async def seed_database():
    """Seed database with initial data"""
    try:
        client = AsyncClient(settings.MONGODB_URL)
        db = client[settings.DATABASE_NAME]
        
        print("Seeding database...")
        
        # Create default campus if not exists
        campuses = db["campuses"]
        existing_campus = await campuses.find_one({"slug": "test-campus"})
        
        if not existing_campus:
            campus_data = {
                "name": "Test Campus",
                "slug": "test-campus",
                "description": "Default test campus",
                "city": "Test City",
                "state": "Test State",
                "address": "123 Test Street",
                "contact_email": "admin@testcampus.com",
                "contact_phone": "1234567890",
                "commission_percentage": 10.0,
                "is_active": True,
                "admin_count": 0,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await campuses.insert_one(campus_data)
            print("✓ Created default campus")
        
        # Create default categories
        categories = db["categories"]
        default_categories = [
            {"name": "Meals", "slug": "meals"},
            {"name": "Snacks", "slug": "snacks"},
            {"name": "Drinks", "slug": "drinks"},
            {"name": "Desserts", "slug": "desserts"},
        ]
        
        for cat in default_categories:
            existing_cat = await categories.find_one({"slug": cat["slug"]})
            if not existing_cat:
                cat_data = {
                    **cat,
                    "campus_id": None,  # Global categories
                    "is_active": True,
                    "created_at": datetime.utcnow()
                }
                await categories.insert_one(cat_data)
        print(f"✓ Created {len(default_categories)} default categories")
        
        print("✓ Database seeding complete")
        client.close()
        
    except Exception as e:
        print(f"✗ Error seeding database: {e}")


if __name__ == "__main__":
    asyncio.run(seed_database())
