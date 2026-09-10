# DETOMSITE Deployment Guide

The repo has **one backend** (FastAPI + Supabase Postgres) and **three independent
portal apps** — each portal is its own Vercel project.

```
detomsite/
├── backend/                  → Render (Python web service) + keep-alive cron
├── frontend/student/         → Vercel project (root directory: frontend/student)
├── frontend/admin/           → Vercel project (root directory: frontend/admin)
└── frontend/shopkeeper/      → Vercel project (root directory: frontend/shopkeeper) + PWA
```

> The top-level `student/`, `admin/`, `shopkeeper/` folders in the repo are
> **local-only duplicates** and are NOT deployed.

## 1. Backend → Render

Create a **Web Service** on [render.com](https://render.com) from the GitHub repo:

- Root Directory: `backend`
- Environment: `Python`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Environment variables:

```env
USE_SUPABASE_DB=True
USE_LOCAL_DB=False
USE_TURSO_DB=False
SUPABASE_DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
JWT_SECRET=replace-with-long-random-secret
DEBUG=False
FRONTEND_URL=https://<shopkeeper>.vercel.app
BACKEND_URL=https://<your-backend>.onrender.com
ALLOWED_ORIGINS=https://<student>.vercel.app,https://<admin>.vercel.app,https://<shopkeeper>.vercel.app
DEFAULT_SUPER_ADMIN_EMAIL=12@gmail.com
DEFAULT_SUPER_ADMIN_PASSWORD=8989
```

> Keep it awake: `backend/render.yaml` defines a **keep-alive cron job** that
> pings `/health` every 10 minutes so the free tier never sleeps.

## 2. Portals → Vercel (3 projects)

For **each** portal on [vercel.com](https://vercel.com) (import the same GitHub repo):

| Portal | Root Directory | Vercel env var |
|--------|---------------|----------------|
| Student | `frontend/student` | `VITE_API_URL=https://<backend>.onrender.com/api/v1` |
| Admin | `frontend/admin` | `VITE_API_URL=https://<backend>.onrender.com/api/v1` |
| Shopkeeper | `frontend/shopkeeper` | `VITE_API_URL=https://<backend>.onrender.com/api/v1` |

Framework auto-detects **Vite**; Build `npm run build`; Output `dist`.

After the frontends are live, make sure Render's `ALLOWED_ORIGINS` matches the
real Vercel URLs.

## 3. Phone install (vendor app)

Open `https://<shopkeeper>.vercel.app` on the phone → Chrome menu → **Install app**
(Android) or Safari → Share → **Add to Home Screen** (iPhone).

## Notes

- Each portal has `vercel.json` SPA rewrites, so deep links like `/mobile` work.
- Admin login: username `12`, password `8989` (from `DEFAULT_SUPER_ADMIN_*`).
- The Supabase schema (`backend/supabase/schema.sql`) is applied automatically at backend
  startup via idempotent migrations — no manual SQL needed.
