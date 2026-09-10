# DETOMSITE - Three Portal Architecture

This project has been restructured into **3 separate portal websites** plus a **mobile PWA app** for vendors.

## 🔗 Portal URLs (Development)

| Portal | Port | URL | Description |
|--------|------|-----|-------------|
| 🎓 **Student Portal** | `:5173` | http://localhost:5173 | Signup, login, browse shops, order, cart, payments |
| ⚙️ **Admin Portal** | `:5174` | http://localhost:5174 | Dashboard, users, vendors, orders, revenue |
| 👨‍🍳 **Shopkeeper Portal** | `:5175` | http://localhost:5175 | Register shop, install mobile app |
| 📱 **Vendor Mobile App** | `:5175/mobile` | http://localhost:5175/mobile | PWA app for order & product management |

## 🚀 Quick Start

### 1. Start the Backend
```bash
cd backend
pip install -r requirements.txt
python main.py   # or: uvicorn app.main:app --reload --port 8000
```

### 2. Start Each Portal (in separate terminals)
```bash
# Student Portal
cd student
npm install
npm run dev

# Admin Portal
cd admin
npm install
npm run dev

# Shopkeeper Portal
cd shopkeeper
npm install
npm run dev
```

### 3. Default Admin Credentials
- **Username:** `admin` or `12` (from DEFAULT_SUPER_ADMIN_EMAIL)
- **Password:** `8989` (from DEFAULT_SUPER_ADMIN_PASSWORD)

## 🏗️ Architecture

```
detomsite/
├── backend/           # Single FastAPI backend for all portals
│   └── app/
│       └── api/v1/
│           ├── users.py       # Student portal API
│           ├── vendor.py      # Shopkeeper/mobile app API  
│           ├── local_admin.py # Admin portal API
│           └── local.py       # Shared endpoints (shops, orders, payments)
├── student/           # Independent React app (port 5173)
├── admin/             # Independent React app (port 5174)
└── shopkeeper/        # Independent React app + PWA (port 5175)
```

## 🔐 Data Separation

Each portal uses separate localStorage tokens:
- **Student:** `access_token` + `user_data`
- **Admin:** `admin_token` + `admin_user`
- **Shopkeeper:** `vendor_token` + `vendor_user`

Backend enforces role-based access on all endpoints.

## 💳 Payment Flow

- **Two methods in the student portal:** **💳 UPI** (pay now — the shop's UPI
  app opens pre-filled) or **💵 Cash on Delivery**.
- **No admin verification** — UPI money lands directly in the shop's UPI
  account; the vendor confirms it in the vendor app (**Payment Received**),
  and COD orders are completed with **Accept & Complete**.
- The student bill is the **subtotal only** — no service fee is added to the
  customer.

## 💰 Where the 5% goes

- The **admin takes 5% of each vendor's single-day earnings** — never from the
  customer's bill.
- **Vendor app:** shows "Admin Share (5% of today's earnings)" with a **Pay**
  button that opens a UPI payment directed to the admin's UPI ID.
- **Admin portal → Payments:** LIVE vendor-share monitor (paid/pending per
  vendor, mark received) + Revenue page with per-day 5% breakdown.

## 🗄️ Databases

- **Default (dev):** local SQLite (`backend/detomsite_local.db`) — zero setup.
  Backend runs on **port 8000** by default (`PORT=8000` in `backend/.env`).
- **Supabase (production):** set `USE_SUPABASE_DB=True` + `SUPABASE_DATABASE_URL`
  in `backend/.env`, run `backend/supabase/schema.sql` in the Supabase SQL editor.
  See `SUPABASE_SETUP.md` for the full walkthrough.

## 📱 Vendor Mobile App (PWA)

The shopkeeper portal includes a full PWA mobile app at `/mobile`:
- Install on phone via browser "Add to Home Screen"
- Accept & complete orders (COD = Accept & Complete, UPI = Payment Received)
- CRUD products (admin is notified of every product change)
- See today's orders/earnings and the 5% amount due to admin (Pay via UPI)
- History tab with date filters (today / yesterday / last 7 days / all)
- Toggle shop open/closed
