"""
MongoDB Atlas readiness check for DETOMSITE.

Checks:
- required environment values
- MongoDB connection ping
- production collection indexes
- a temporary CRUD operation
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime


REQUIRED = ["MONGODB_URL", "DATABASE_NAME"]


async def main() -> int:
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if missing:
        print(f"MongoDB check skipped: missing {', '.join(missing)}")
        return 2

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.core.local_mongo_db import ensure_indexes
    except ImportError as exc:
        print(f"MongoDB check failed: missing dependency {exc.name}")
        return 2

    client = AsyncIOMotorClient(os.environ["MONGODB_URL"], serverSelectionTimeoutMS=8000)
    database = client[os.environ["DATABASE_NAME"]]

    try:
        await client.admin.command("ping")
        await ensure_indexes(database)

        marker = f"deployment-check-{datetime.utcnow().isoformat()}"
        result = await database.deployment_checks.insert_one({"marker": marker, "created_at": datetime.utcnow()})
        found = await database.deployment_checks.find_one({"_id": result.inserted_id})
        await database.deployment_checks.delete_one({"_id": result.inserted_id})

        if not found:
            print("MongoDB check failed: CRUD read did not return inserted document")
            return 1

        collections = await database.list_collection_names()
        print("MongoDB check passed")
        print(f"Database: {os.environ['DATABASE_NAME']}")
        print(f"Collections: {', '.join(sorted(collections))}")
        return 0
    except Exception as exc:
        print(f"MongoDB check failed: {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
