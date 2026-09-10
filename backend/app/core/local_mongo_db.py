"""
MongoDB-backed store for the runnable DETOMSITE API.

The frontend currently uses the /api/v1/local routes. In production, those
routes need a persistent database instead of the local SQLite demo file, so
this module mirrors the local_demo_db contract using MongoDB collections.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


SHOP_SEED = [
    {
        "id": "1",
        "name": "Pizza Palace",
        "category": "Italian",
        "description": "Campus pizzas, garlic breads, and quick combo meals.",
        "rating": 4.5,
        "opening_time": "12:00 AM",
        "closing_time": "11:59 PM",
        "present": 1,
        "status": "Open",
        "approval_status": "Approved",
        "shopkeeper_name": "Arun Kumar",
        "phone": "9876543210",
        "orders_today": 24,
        "revenue_today": 12450,
        "current_token": 23,
    },
    {
        "id": "2",
        "name": "Burger Bay",
        "category": "Fast Food",
        "description": "Burgers, fries, rolls, and cold drinks for short breaks.",
        "rating": 4.2,
        "opening_time": "09:00 AM",
        "closing_time": "09:30 PM",
        "present": 1,
        "status": "Busy",
        "approval_status": "Approved",
        "shopkeeper_name": "Priya Menon",
        "phone": "9876543211",
        "orders_today": 18,
        "revenue_today": 8560,
        "current_token": 21,
    },
    {
        "id": "3",
        "name": "Biryani House",
        "category": "Indian",
        "description": "Meals, biryani, snacks, and evening tiffin boxes.",
        "rating": 4.6,
        "opening_time": "11:00 AM",
        "closing_time": "11:00 PM",
        "present": 0,
        "status": "Closed",
        "approval_status": "Approved",
        "shopkeeper_name": "Naveen Shah",
        "phone": "9876543212",
        "orders_today": 12,
        "revenue_today": 9320,
        "current_token": 18,
    },
    {
        "id": "4",
        "name": "Tea Point",
        "category": "Cafe",
        "description": "Tea, coffee, puffs, sandwiches, and study-time snacks.",
        "rating": 4.7,
        "opening_time": "07:30 AM",
        "closing_time": "08:00 PM",
        "present": 1,
        "status": "Open",
        "approval_status": "Pending Approval",
        "shopkeeper_name": "Meera Joseph",
        "phone": "9876543213",
        "orders_today": 0,
        "revenue_today": 0,
        "current_token": 18,
    },
]

PRODUCT_SEED = [
    {"id": "p1", "shop_id": "1", "name": "Margherita Pizza", "description": "Cheese pizza with tomato base.", "price": 250, "pending_price": None, "category": "Pizza", "inventory": 18, "prep_time": 15, "available": 1},
    {"id": "p2", "shop_id": "1", "name": "Garlic Bread", "description": "Four pieces with herbed butter.", "price": 100, "pending_price": 120, "category": "Starters", "inventory": 24, "prep_time": 8, "available": 1},
    {"id": "p3", "shop_id": "1", "name": "Coke 250ml", "description": "Chilled beverage.", "price": 50, "pending_price": None, "category": "Beverages", "inventory": 40, "prep_time": 2, "available": 1},
    {"id": "p4", "shop_id": "2", "name": "Classic Veg Burger", "description": "Patty, cheese, lettuce, and house sauce.", "price": 140, "pending_price": None, "category": "Burgers", "inventory": 20, "prep_time": 12, "available": 1},
    {"id": "p5", "shop_id": "2", "name": "Masala Fries", "description": "Crispy fries with campus masala.", "price": 90, "pending_price": None, "category": "Sides", "inventory": 30, "prep_time": 7, "available": 1},
    {"id": "p6", "shop_id": "3", "name": "Chicken Biryani", "description": "Single portion with raita.", "price": 220, "pending_price": None, "category": "Meals", "inventory": 0, "prep_time": 30, "available": 0},
]

ORDER_SEED = [
    {"id": "o1", "token": 23, "student_name": "Yokesh", "student_phone": "9876500001", "shop_id": "1", "shop_name": "Pizza Palace", "items": "2x Margherita Pizza, 1x Coke", "total": 590, "delivery_location": "Hostel A Block 201", "delivery_slot": "Evening", "status": "Pending Acceptance", "created_at": "2026-06-11"},
    {"id": "o2", "token": 22, "student_name": "Anitha", "student_phone": "9876500002", "shop_id": "1", "shop_name": "Pizza Palace", "items": "1x Garlic Bread, 1x Coke", "total": 180, "delivery_location": "Library Gate", "delivery_slot": "Afternoon", "status": "Preparing", "created_at": "2026-06-11"},
    {"id": "o3", "token": 21, "student_name": "Rahul", "student_phone": "9876500003", "shop_id": "2", "shop_name": "Burger Bay", "items": "2x Classic Veg Burger", "total": 310, "delivery_location": "CSE Block", "delivery_slot": "Night", "status": "Ready", "created_at": "2026-06-11"},
    {"id": "o4", "token": 20, "student_name": "Yokesh", "student_phone": "9876500001", "shop_id": "3", "shop_name": "Biryani House", "items": "1x Chicken Biryani", "total": 250, "delivery_location": "Hostel A Block 201", "delivery_slot": "Afternoon", "status": "Completed", "created_at": "2026-06-10"},
]


def _database():
    from app.core.database import get_database

    database = get_database()
    if database is None:
        raise RuntimeError("MongoDB is not connected")
    return database


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _today_key() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def _without_id(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if not document:
        return None
    document.pop("_id", None)
    return document


async def init_local_mongo_db() -> None:
    database = _database()
    await ensure_indexes(database)

    from app.core.config import settings
    if not settings.SEED_DEMO_DATA or await database.local_shops.count_documents({}):
        return

    await database.local_shops.insert_many(SHOP_SEED)
    await database.local_products.insert_many(PRODUCT_SEED)
    await database.local_orders.insert_many(ORDER_SEED)


async def ensure_indexes(database) -> None:
    await database.local_sessions.create_index("email")
    await database.local_shops.create_index("id", unique=True)
    await database.local_shops.create_index([("approval_status", 1), ("present", 1), ("status", 1)])
    await database.local_products.create_index("id", unique=True)
    await database.local_products.create_index("shop_id")
    await database.local_products.create_index([("shop_id", 1), ("category", 1), ("name", 1)])
    await database.local_orders.create_index("id", unique=True)
    await database.local_orders.create_index([("created_at", 1), ("token", -1)])
    await database.local_orders.create_index("shop_id")
    await database.local_payments.create_index("id", unique=True)
    await database.local_payments.create_index("order_id")
    await database.local_tickets.create_index("id", unique=True)
    await database.local_tickets.create_index("email")
    await database.local_notifications.create_index("order_id")
    await database.local_notifications.create_index("sequence")


async def save_session(email: str, name: str, role: str) -> dict[str, Any]:
    database = _database()
    next_id = await database.local_sessions.count_documents({}) + 1
    session = {
        "id": next_id,
        "email": email,
        "name": name,
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
    }
    await database.local_sessions.insert_one(session)
    return _without_id(session) or session


async def list_shops() -> list[dict[str, Any]]:
    database = _database()
    rows = await database.local_shops.find({}, {"_id": 0}).sort("rating", -1).to_list(length=None)
    return rows


async def get_shop(shop_id: str) -> dict[str, Any] | None:
    database = _database()
    row = await database.local_shops.find_one({"id": shop_id}, {"_id": 0})
    return row


async def update_shop(shop_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "name",
        "category",
        "description",
        "opening_time",
        "closing_time",
        "present",
        "status",
        "approval_status",
        "shopkeeper_name",
        "phone",
        "upi_id",
        "upi_enabled",
        "cod_enabled",
    }
    updates = {key: value for key, value in values.items() if key in allowed_fields and value is not None}
    if "present" in updates:
        updates["present"] = 1 if updates["present"] else 0
    if updates:
        await _database().local_shops.update_one({"id": shop_id}, {"$set": updates})
    return await get_shop(shop_id)


async def list_products(shop_id: str | None = None) -> list[dict[str, Any]]:
    query = {"shop_id": shop_id} if shop_id else {}
    rows = await _database().local_products.find(query, {"_id": 0}).sort([("category", 1), ("name", 1)]).to_list(length=None)
    return rows


async def get_product(product_id: str) -> dict[str, Any] | None:
    return await _database().local_products.find_one({"id": product_id}, {"_id": 0})


async def create_product(values: dict[str, Any]) -> dict[str, Any]:
    database = _database()
    product_id = values.get("id") or f"p{await database.local_products.count_documents({}) + 1}"
    product = {
        "id": product_id,
        "shop_id": values["shop_id"],
        "name": values["name"],
        "description": values.get("description", ""),
        "price": values["price"],
        "pending_price": values.get("pending_price"),
        "category": values["category"],
        "inventory": values.get("inventory", 0),
        "prep_time": values.get("prep_time", 10),
        "available": 1 if values.get("available", True) else 0,
    }
    await database.local_products.insert_one(product)
    return _without_id(product) or product


async def update_product(product_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "name",
        "description",
        "price",
        "pending_price",
        "category",
        "inventory",
        "prep_time",
        "available",
    }
    updates = {key: value for key, value in values.items() if key in allowed_fields and (value is not None or key == "pending_price")}
    if "available" in updates:
        updates["available"] = 1 if updates["available"] else 0
    if updates:
        await _database().local_products.update_one({"id": product_id}, {"$set": updates})
    return await get_product(product_id)


async def list_orders() -> list[dict[str, Any]]:
    rows = await _database().local_orders.find({}, {"_id": 0}).sort("token", -1).to_list(length=None)
    return rows


async def get_order(order_id: str) -> dict[str, Any] | None:
    return await _database().local_orders.find_one({"id": order_id}, {"_id": 0})


async def create_notification(
    title: str,
    message: str,
    order_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    database = _database()
    next_id = await database.local_notifications.count_documents({}) + 1
    notification = {
        "id": f"n{next_id}",
        "title": title,
        "message": message,
        "order_id": order_id,
        "status": status,
        "is_read": 0,
        "created_at": datetime.utcnow().isoformat(),
        "sequence": next_id,
    }
    await database.local_notifications.insert_one(notification)
    return _without_id(notification) or notification


async def update_order_status(order_id: str, status: str) -> dict[str, Any] | None:
    database = _database()
    await database.local_orders.update_one({"id": order_id}, {"$set": {"status": status}})
    row = await get_order(order_id)
    if row:
        status_messages = {
            "Confirmed": "Your order has been confirmed.",
            "Preparing": "Your food is being prepared.",
            "Ready": "Your order is ready.",
            "Completed": "Order completed successfully.",
            "Cancelled": "Order cancelled.",
            "Failed": "Payment failed.",
            "Refunded": "Order refunded.",
        }
        await create_notification(
            title="Order completed" if status == "Completed" else "Order status updated",
            message=f"Token {row['token']}: {status_messages.get(status, f'Order is now {status}.')}",
            order_id=order_id,
            status=status,
        )
    return row


async def create_order(values: dict[str, Any]) -> dict[str, Any] | None:
    database = _database()
    shop = await get_shop(values["shop_id"])
    if not shop:
        return None

    subtotal = 0
    item_labels: list[str] = []
    for item in values["items"]:
        product = await get_product(item["product_id"])
        if not product:
            continue
        quantity = int(item["quantity"])
        subtotal += int(product["price"]) * quantity
        item_labels.append(f"{quantity}x {product['name']}")

    if not item_labels:
        return None

    # Only the 5% platform service fee (no tax, no delivery)
    tax = 0
    delivery_fee = 0
    total = subtotal + round(subtotal * 0.05)
    today = _today()
    latest_today = await database.local_orders.find_one(
        {"created_at": today},
        sort=[("token", -1)],
        projection={"_id": 0},
    )
    next_token = (latest_today["token"] if latest_today else 17) + 1
    order_id = f"o{_today_key()}-{next_token}"
    order = {
        "id": order_id,
        "token": next_token,
        "student_name": values.get("student_name", "Student"),
        "student_phone": values.get("student_phone", ""),
        "shop_id": values["shop_id"],
        "shop_name": shop["name"],
        "items": ", ".join(item_labels),
        "total": total,
        "delivery_location": values["delivery_location"],
        "delivery_slot": values["delivery_slot"],
        "status": "Pending Acceptance",
        "created_at": today,
    }
    await database.local_orders.insert_one(order)
    await database.local_shops.update_one(
        {"id": values["shop_id"]},
        {
            "$inc": {"orders_today": 1, "revenue_today": total},
            "$set": {"current_token": next_token},
        },
    )
    await create_notification(
        title="Order placed",
        message=f"Token {next_token}: Waiting for shop confirmation.",
        order_id=order_id,
        status=order["status"],
    )
    return _without_id(order) or order


async def create_payment(
    order_id: str,
    amount: int,
    method: str,
    utr_number: str | None = None,
    screenshot_name: str | None = None,
) -> dict[str, Any] | None:
    database = _database()
    if not await get_order(order_id):
        return None
    next_id = await database.local_payments.count_documents({}) + 1
    payment = {
        "id": f"pay{next_id}",
        "order_id": order_id,
        "amount": amount,
        "method": method,
        "status": "Pending Verification" if method == "Manual UTR" else "Success",
        "utr_number": utr_number,
        "screenshot_name": screenshot_name,
        "created_at": datetime.utcnow().isoformat(),
        "sequence": next_id,
    }
    await database.local_payments.insert_one(payment)
    return _without_id(payment) or payment


async def list_payments() -> list[dict[str, Any]]:
    rows = await _database().local_payments.find({}, {"_id": 0}).sort("sequence", -1).to_list(length=None)
    return rows


async def update_payment_status(payment_id: str, status: str) -> dict[str, Any] | None:
    database = _database()
    await database.local_payments.update_one({"id": payment_id}, {"$set": {"status": status}})
    return await database.local_payments.find_one({"id": payment_id}, {"_id": 0})


async def create_ticket(values: dict[str, Any]) -> dict[str, Any]:
    database = _database()
    next_id = await database.local_tickets.count_documents({}) + 1
    ticket = {
        "id": f"t{next_id}",
        "ticket_number": f"TKT-{1000 + next_id}",
        "name": values["name"],
        "email": values["email"],
        "phone_number": values["phone_number"],
        "category": values["category"],
        "title": values["title"],
        "description": values["description"],
        "status": "Open",
        "created_at": datetime.utcnow().isoformat(),
        "sequence": next_id,
    }
    await database.local_tickets.insert_one(ticket)
    return _without_id(ticket) or ticket


async def list_tickets() -> list[dict[str, Any]]:
    rows = await _database().local_tickets.find({}, {"_id": 0}).sort("sequence", -1).to_list(length=None)
    return rows


async def list_notifications() -> list[dict[str, Any]]:
    rows = await _database().local_notifications.find({}, {"_id": 0}).sort("sequence", -1).limit(20).to_list(length=20)
    return rows


async def get_summary() -> dict[str, Any]:
    shops = await list_shops()
    orders = await list_orders()
    products = await list_products()
    return {
        "shops": len(shops),
        "orderable_shops": len([
            shop for shop in shops
            if shop["approval_status"] == "Approved" and shop["present"] and shop["status"] == "Open"
        ]),
        "products": len(products),
        "active_orders": len([order for order in orders if order["status"] != "Completed"]),
        "revenue": sum(order["total"] for order in orders),
        "token_starts_at": 18,
    }
