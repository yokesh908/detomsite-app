# DETOMSITE — Campus Food Ordering Platform

One command to go live. No server, no database setup, no code.

## Deploy (5 minutes, mostly just clicking "Authorize" in your browser)

```bash
bash deploy.sh
```

The script:
1. Installs the Vercel + Supabase tools it needs,
2. Logs you in (Vercel, then Supabase — click Authorize in the browser),
3. Creates a free Supabase database and loads every table,
4. Deploys the backend and the frontend to Vercel,
5. Prints your app URL + admin login at the end
   (also saved to `.deploy-credentials.txt`).

That's it. Open the printed URL and log in.

## What you get

| Piece | Where |
|---|---|
| Student / shopkeeper / admin app | `frontend/` → Vercel |
| Backend API (FastAPI) | `backend/` → Vercel |
| Database | Supabase (free Postgres), created automatically |

## Local development

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (in a 2nd terminal)
cd frontend
npm install
npm run dev
```

## Notes

- Your admin password is generated automatically and shown at the end of the deploy.
- Re-run `bash deploy.sh` to re-deploy after changes (it reuses the same projects).
- If the backend ever has trouble on Vercel's free serverless, the script tells you
  how to move it to Render (free) in two clicks — everything else stays the same.