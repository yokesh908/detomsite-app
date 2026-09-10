# DETOMSITE V3.1 - Complete File Index

## Project Location
`/home/yokeshwaran/detomsite/`

## Directory Structure

```
detomsite/
├── backend/                          # FastAPI Backend
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI Application Entry Point
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── auth.py          # Authentication Endpoints
│   │   │       ├── users.py         # User Management Endpoints
│   │   │       ├── campuses.py      # Campus Management Endpoints
│   │   │       ├── shops.py         # Shop Management Endpoints
│   │   │       ├── products.py      # Product Management Endpoints
│   │   │       ├── orders.py        # Order Processing Endpoints
│   │   │       ├── payments.py      # Payment Processing Endpoints
│   │   │       ├── reviews.py       # Review Management Endpoints
│   │   │       ├── tickets.py       # Support Ticket Endpoints
│   │   │       ├── admin.py         # Admin Dashboard Endpoints
│   │   │       └── admin_super.py   # Super Admin Endpoints
│   │   ├── models/
│   │   │   └── __init__.py          # All Beanie Models (14 collections)
│   │   ├── schemas/
│   │   │   └── __init__.py          # Pydantic Schemas for Validation
│   │   ├── services/
│   │   │   ├── __init__.py          # Basic Auth Service
│   │   │   ├── auth_service.py      # Auth Service Module
│   │   │   ├── auth_advanced.py     # Advanced Auth (Email, Password Reset)
│   │   │   ├── email_service.py     # Email Notifications
│   │   │   ├── shop_service.py      # Shop Business Logic
│   │   │   ├── product_service.py   # Product Business Logic
│   │   │   ├── order_service.py     # Order Processing Logic
│   │   │   ├── payment_service.py   # Payment Processing Logic
│   │   │   ├── review_service.py    # Review & Rating Logic
│   │   │   ├── notification_service.py # Notifications
│   │   │   └── analytics_service.py # Analytics & Statistics
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py            # Configuration Management
│   │   │   ├── security.py          # JWT & Password Hashing
│   │   │   └── database.py          # MongoDB Connection
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   └── error_handler.py     # Error Handling & Logging
│   │   └── utils/
│   │       └── __init__.py
│   ├── tests/
│   │   ├── conftest.py              # Test Configuration
│   │   └── test_auth.py             # Authentication Tests
│   ├── scripts/
│   │   └── seed.py                  # Database Seeding Script
│   ├── main.py                      # Entry Point
│   ├── requirements.txt             # Python Dependencies
│   ├── .env.example                 # Environment Template
│   ├── .gitignore                   # Git Ignore Rules
│   ├── Dockerfile                   # Docker Image
│   └── vercel.json                  # Vercel Deployment Config
│
├── student/                         # Student portal (React + Vite, port 5173)
│   ├── src/App.tsx                 # Root Component
│   ├── src/services/api.ts         # Axios API Client
│   ├── public/                     # Static assets
│   ├── index.html                  # HTML Entry Point
│   ├── package.json                # NPM Dependencies
│   ├── vite.config.ts              # Vite Configuration
│   └── vercel.json                 # Vercel Deployment Config
├── admin/                           # Admin portal (React + Vite, port 5174)
│   ├── src/App.tsx                 # Root Component
│   ├── src/services/api.ts         # Axios API Client
│   ├── index.html                  # HTML Entry Point
│   ├── package.json                # NPM Dependencies
│   ├── vite.config.ts              # Vite Configuration
│   └── vercel.json                 # Vercel Deployment Config
├── shopkeeper/                      # Vendor portal + PWA (port 5175)
│   ├── src/App.tsx                 # Root Component (mobile app UI)
│   ├── src/services/api.ts         # Axios API Client
│   ├── public/mobile/              # PWA manifest, icons, service worker
│   ├── index.html                  # HTML Entry Point
│   ├── package.json                # NPM Dependencies
│   ├── vite.config.ts              # Vite Configuration
│   └── vercel.json                 # Vercel Deployment Config
├── .github/
│   └── workflows/
│       └── ci-cd.yml               # GitHub Actions Pipeline
│
├── docker-compose.yml              # Docker Compose Configuration
├── README.md                        # Project Documentation
├── SETUP_GUIDE.md                  # Setup Instructions
├── PROJECT_SUMMARY.md              # Implementation Summary
├── DEPLOYMENT_CHECKLIST.md         # Pre-Deployment Checklist
└── FILE_INDEX.md                   # This File
```

## File Count Summary

- **Backend**: 45+ Python files
- **Frontend**: 15+ TypeScript/React files
- **Configuration**: 12 config files
- **Documentation**: 5 markdown files
- **Infrastructure**: 3 Docker/CI files

**Total: 80+ Production-Ready Files**

## Key Files to Know

### Essential Backend Files
1. `backend/app/main.py` - FastAPI Application
2. `backend/app/models/__init__.py` - Database Models
3. `backend/app/schemas/__init__.py` - Request/Response Schemas
4. `backend/requirements.txt` - Dependencies
5. `backend/.env.example` - Configuration Template

### Essential Portal Files (3 independent apps)
1. `student/src/App.tsx` - Student portal root component
2. `admin/src/App.tsx` - Admin portal root component
3. `shopkeeper/src/App.tsx` - Vendor mobile app root component
4. `shopkeeper/public/mobile/manifest.json` - PWA manifest
5. `student|admin|shopkeeper/.env.example` - VITE_API_URL templates

### Configuration Files
1. `docker-compose.yml` - Local Development
2. `.github/workflows/ci-cd.yml` - CI/CD Pipeline
3. `DEPLOYMENT_CHECKLIST.md` - Production Deployment Guide
4. `SETUP_GUIDE.md` - Developer Setup

## Quick Start Commands

### Backend
```bash
cd backend
cp .env.example .env
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Portals (each in its own terminal)
```bash
cd student   # or admin / shopkeeper
npm install
npm run dev
```

### Docker (Recommended)
```bash
docker-compose up --build
```

## API Endpoints Overview

### Authentication
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- POST /api/v1/auth/logout
- GET /api/v1/auth/me
- POST /api/v1/auth/change-password

### Resources
- /api/v1/users/ - User management
- /api/v1/campuses/ - Campus management (super admin)
- /api/v1/shops/ - Shop management
- /api/v1/products/ - Product management
- /api/v1/orders/ - Order processing
- /api/v1/payments/ - Payment handling
- /api/v1/reviews/ - Reviews and ratings
- /api/v1/tickets/ - Support tickets

### Admin
- /api/v1/admin/ - Admin dashboard
- /api/v1/super-admin/ - Super admin dashboard

## Documentation Files

1. **README.md** - Project overview and quick start
2. **SETUP_GUIDE.md** - Detailed setup instructions
3. **PROJECT_SUMMARY.md** - Feature completion status
4. **DEPLOYMENT_CHECKLIST.md** - Pre-production checklist
5. **API Documentation** - Available at /docs after running backend

## Environment Variables Required

### Backend (.env)
- MONGODB_URL
- REDIS_URL
- SECRET_KEY
- DEFAULT_SUPER_ADMIN_EMAIL
- DEFAULT_SUPER_ADMIN_PASSWORD
- RAZORPAY_KEY_ID
- RAZORPAY_KEY_SECRET
- CLOUDINARY_CLOUD_NAME
- CLOUDINARY_API_KEY
- CLOUDINARY_API_SECRET
- SENTRY_DSN (optional)

### Frontend (.env / Vercel env var)
- VITE_API_URL (set in each portal's Vercel project to the deployed backend)
- VITE_RAZORPAY_KEY_ID (optional)
- VITE_CLOUDINARY_CLOUD_NAME (optional)

## Local Access

The frontend asks for Student or Shopkeeper on first entry and saves that email in the browser. Production admin credentials should be supplied through environment variables.

## Testing

### Backend
```bash
cd backend
pytest tests/ --cov=app
```

### Portals
```bash
cd student   # or admin / shopkeeper
npm run build
```

## Deployment

### Render (Backend)
Deploy `backend/` to Render (Python) with `USE_SUPABASE_DB=True` + Supabase
connection string. `backend/render.yaml` includes a keep-alive cron.

### Vercel (Portals — 3 projects)
```bash
cd student   # then cd ../admin, cd ../shopkeeper
vercel --prod   # Root Directory = the portal folder; set VITE_API_URL
```

### Docker
```bash
docker-compose -f docker-compose.prod.yml up -d
```

## Support & Documentation

- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI**: http://localhost:8000/openapi.json
- **GitHub**: All source code versioned
- **Docker Hub**: Ready for container registry

---

**Project Status**: Production-Ready ✓
**Last Updated**: 2024
**Version**: 3.1.0
