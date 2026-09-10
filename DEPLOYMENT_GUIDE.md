# DETOMSITE Deployment Guide

This guide continues from the existing DETOMSITE codebase. It does not require rebuilding the project.

## 1. Create MongoDB Atlas Database

1. Create a MongoDB Atlas cluster.
2. Create a database user.
3. Add your Vercel/server IP access rule. For quick Vercel testing, allow `0.0.0.0/0`, then tighten later.
4. Copy the MongoDB connection string.

Required backend environment variables:

```env
MONGODB_URL=mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/detomsite?retryWrites=true&w=majority
DATABASE_NAME=detomsite
JWT_SECRET=replace-with-long-random-secret
FRONTEND_URL=https://your-frontend.vercel.app
BACKEND_URL=https://your-backend.vercel.app
USE_LOCAL_DB=False
SEED_DEMO_DATA=False
ALLOWED_ORIGINS=https://your-frontend.vercel.app,https://your-backend.vercel.app,http://localhost:5173
DEFAULT_SUPER_ADMIN_EMAIL=12@gmail.com
DEFAULT_SUPER_ADMIN_PASSWORD=8989
```

Payment variables can stay empty until the payment gateway is completed.

## 2. Backend Deploy To Vercel

From the backend folder:

```bash
cd backend
npx vercel login
npx vercel --prod
```

Set the backend environment variables in the Vercel project settings before the production deploy.

After deploy, verify:

```bash
curl https://your-backend.vercel.app/health
curl https://your-backend.vercel.app/api/v1/local/summary
```

## 3. Frontend Deploy To Vercel

Set frontend environment variable:

```env
VITE_API_URL=https://your-backend.vercel.app/api/v1
```

From the frontend folder:

```bash
cd frontend
npx vercel --prod
```

After frontend URL is final, update backend:

```env
FRONTEND_URL=https://your-frontend.vercel.app
ALLOWED_ORIGINS=https://your-frontend.vercel.app,https://your-backend.vercel.app,http://localhost:5173
```

Redeploy backend after updating CORS.

## 4. Validation Commands

Frontend build:

```bash
cd frontend
npm run build
```

Backend validation:

```bash
cd backend
venv/bin/python -m compileall app
```

MongoDB connection, index, and CRUD test:

```bash
cd backend
MONGODB_URL="mongodb+srv://..." DATABASE_NAME="detomsite" venv/bin/python scripts/check_mongo.py
```

Deployment readiness:

```bash
python3 backend/scripts/deployment_readiness.py
```

## 5. Expected Production Behavior

- MongoDB collections and indexes are created automatically at backend startup.
- Demo rows are not inserted unless `SEED_DEMO_DATA=True`.
- Local development still uses SQLite when `USE_LOCAL_DB=True`.
- Existing frontend routes continue to use `/api/v1/local/*`, backed by MongoDB in production.
