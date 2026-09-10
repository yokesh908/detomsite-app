# Supabase setup for DETOMSITE (full migration)

DETOMSITE now supports **Supabase (Postgres)** as its production database.
The backend keeps serving all APIs — you only switch where the data lives.

- **Default (dev):** local SQLite — zero setup, data in `backend/detomsite_local.db`
- **Production:** Supabase Postgres — set `USE_SUPABASE_DB=True` and one env var

No other code changes are needed: the backend detects the mode from `.env`.

---

## 1. Create a Supabase project

1. Go to https://supabase.com → **New project** (free tier is fine).
2. Pick a region close to you, set a strong **database password**, save it.
3. After creation, open **Project Settings → Database → Connection string**.

Copy the **URI connection string**, it looks like:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

> ⚠️ Replace `<password>` with the database password you set in step 2.

---

## 2. Run the schema

1. In the Supabase dashboard open **SQL Editor → New query**.
2. Open the file `backend/supabase/schema.sql` from this repo and paste the whole thing.
3. Click **Run**.

This creates all tables:

| Table | Purpose |
|---|---|
| `users` | all three roles (student / shopkeeper / admin), one per row |
| `sessions` | login/session history |
| `user_registrations` | signup log for the admin dashboard |
| `shops` | shop details + approval status |
| `products` | menu items with prices |
| `orders` | orders incl. `subtotal`, `service_fee` (5%), `tax`, `delivery_fee`, `total` |
| `payments` | UPI/UTR + Razorpay payment records |
| `tickets` | support tickets |
| `notifications` | order updates + vendor-change alerts for admin |
| `app_settings` | payment toggles, UPI id, instructions |

---

## 3. Configure the backend `.env`

In `backend/.env` (copy `backend/.env.example` if missing) set:

```env
USE_LOCAL_DB=False
USE_TURSO_DB=False
USE_SUPABASE_DB=True

# Your Supabase Postgres connection string from step 1
SUPABASE_DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres

# (optional) Frontend keys — used only for optional profile sync
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<your-anon-key>
```

> You can also use the individual settings instead of the full URL:
> `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`, `SUPABASE_DB_USER`, `SUPABASE_DB_PASSWORD`, `SUPABASE_DB_NAME`.

---

## 4. Install the Postgres driver

```bash
cd backend
pip install -r requirements.txt   # includes psycopg2-binary
```

---

## 5. Start the backend

```bash
cd backend
python main.py            # → http://localhost:8000
```

Open http://localhost:8000/api/v1/local/status — it will report the Supabase mode.

---

## 6. Default admin login

- Username: **12** (from `DEFAULT_SUPER_ADMIN_EMAIL=12@gmail.com`)
- Password: **8989** (from `DEFAULT_SUPER_ADMIN_PASSWORD`)

The admin login endpoint checks the DB first, then falls back to these env
credentials — so it works immediately even before you add an admin row.

---

## 7. Payment setup (free UPI, no gateway)

The **free** payment flow needs no account or API keys:

1. Log in to the **Admin portal** (`http://localhost:5174`).
2. Open the admin dashboard → **Payment Settings** (on the Dashboard page).
3. Toggle **Enable manual UPI/UTR payments** and set:
   - **UPI ID** — e.g. `yourname@okhdfcbank` (your actual UPI handle)
   - **Receiver name** — the name shown to students
   - Instructions if you like.
4. Students now see a **"Pay via UPI App"** button that opens GPay / PhonePe /
   Paytm directly with the amount pre-filled (`upi://pay?...` deep link — free,
   no gateway involved). They pay, enter the UTR, and the admin verifies it in
   the **Payments** tab of the admin portal.

**Razorpay** (optional, professional checkout) also remains wired — just add
`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` to `backend/.env` and enable it in
payment settings.

---

## 8. How the 5% platform fee works

- Every order stores `service_fee = 5% of food subtotal` (per item).
- The **student bill** shows: Subtotal + **Service Fee (5%)** + Tax (5%) + Delivery = Total.
- The **vendor** sees "Due to Admin (5%)" and their net earnings on the dashboard.
- The **admin** sees their total 5% share, today's share, and per-day breakdowns
  with **date filtering** on the Revenue page.

---

## 9. Optional: Row Level Security

By default the backend enforces role access (students, vendors, admins all get
separate portals and endpoints). If you also want DB-level RLS (extra privacy),
run this in the SQL editor after creating the tables:

```sql
alter table public.users enable row level security;
alter table public.shops enable row level security;
alter table public.orders enable row level security;
alter table public.payments enable row level security;
alter table public.products enable row level security;
```

For a quick start you can leave RLS off — the API layer already isolates each
role's data.

---

## 10. Go back to SQLite (dev mode) anytime

Set `USE_SUPABASE_DB=False` and `USE_LOCAL_DB=True` — the backend falls back to
the SQLite file and all three portals keep working.
