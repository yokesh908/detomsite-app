-- ============================================================
-- DETOMSITE — Supabase schema
-- Run this in Supabase Dashboard → SQL Editor → New query → Run
-- ============================================================

create extension if not exists pgcrypto;

-- ─── Users (all three roles in one table, role-separated access) ───
create table if not exists public.users (
  id bigserial primary key,
  username text unique not null,
  password_hash text not null,
  name text not null,
  email text not null default '',
  phone text not null default '',
  role text not null check (role in ('student', 'shopkeeper', 'admin')),
  created_at timestamptz not null default now()
);
-- One account per email (case-insensitive, non-empty only). Registration is
-- rejected with "email already registered" when this index would be violated.
create unique index if not exists idx_users_email_unique
  on public.users (lower(email)) where email <> '';

-- ─── Sessions / login history ───
create table if not exists public.sessions (
  id bigserial primary key,
  email text not null,
  name text not null,
  role text not null,
  created_at timestamptz not null default now()
);

-- ─── User registrations (admin activity log) ───
create table if not exists public.user_registrations (
  id bigserial primary key,
  username text not null,
  name text not null,
  email text not null default '',
  phone text not null default '',
  role text not null,
  created_at timestamptz not null default now()
);

-- ─── Shops ───
create table if not exists public.shops (
  id text primary key,
  name text not null,
  category text not null,
  description text not null default '',
  rating numeric not null default 0,
  opening_time text not null default '09:00 AM',
  closing_time text not null default '09:00 PM',
  present boolean not null default false,
  status text not null default 'Closed',
  approval_status text not null default 'Pending Approval',
  shopkeeper_email text not null default '',
  shopkeeper_name text not null default '',
  phone text not null default '',
  upi_id text not null default '',
  upi_enabled boolean not null default true,
  cod_enabled boolean not null default true,
  orders_today integer not null default 0,
  revenue_today integer not null default 0,
  current_token integer not null default 18,
  is_removed boolean not null default false,
  admin_dues_balance integer not null default 0,
  admin_dues_last_paid_at timestamptz,
  created_at timestamptz not null default now()
);

-- ─── Products ───
create table if not exists public.products (
  id text primary key,
  shop_id text not null references public.shops(id) on delete cascade,
  name text not null,
  description text not null default '',
  price integer not null,
  pending_price integer,
  category text not null,
  inventory integer not null default 0,
  prep_time integer not null default 10,
  available boolean not null default true,
  created_at timestamptz not null default now()
);

-- ─── Orders (with the full 5% fee breakdown stored per order) ───
create table if not exists public.orders (
  id text primary key,
  token integer not null,
  student_name text not null,
  student_phone text not null default '',
  shop_id text not null references public.shops(id) on delete cascade,
  shop_name text not null,
  items text not null,
  subtotal integer not null default 0,
  service_fee integer not null default 0,      -- 5% platform service fee (admin's cut)
  tax integer not null default 0,
  delivery_fee integer not null default 0,
  total integer not null default 0,
  delivery_location text not null,
  delivery_slot text not null,
  status text not null default 'Pending Acceptance',
  payment_method text not null default 'UPI',  -- 'UPI' | 'COD' | 'Razorpay'
  created_at timestamptz not null default now()
);

-- ─── Payments ───
create table if not exists public.payments (
  id text primary key,
  order_id text not null references public.orders(id) on delete cascade,
  amount integer not null,
  method text not null,
  status text not null default 'Pending Verification',
  utr_number text,
  screenshot_name text,
  created_at timestamptz not null default now()
);

-- ─── Support tickets ───
create table if not exists public.tickets (
  id text primary key,
  ticket_number text not null unique,
  name text not null,
  email text not null,
  phone_number text not null,
  category text not null,
  title text not null,
  description text not null,
  status text not null default 'Open',
  created_at timestamptz not null default now()
);

-- ─── Notifications (order updates, vendor product changes, admin alerts) ───
create table if not exists public.notifications (
  id text primary key,
  title text not null,
  message text not null,
  order_id text references public.orders(id) on delete set null,
  status text,
  target_role text not null default '',  -- 'admin' | 'student' | 'shopkeeper' | '' (all)
  is_read boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists idx_notifications_target_role on public.notifications (target_role);

-- ─── App settings (payment toggles, UPI id, etc.) ───
create table if not exists public.app_settings (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

-- ─── Password resets (double email OTP verification) ───
-- Forgot-password flow stores a 6-digit OTP per step (1 then 2) with expiry.
create table if not exists public.password_resets (
  id bigserial primary key,
  username text not null,
  otp text not null,
  step integer not null default 1,
  expires_at timestamptz not null,
  used boolean not null default false,
  attempts integer not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists idx_password_resets_username on public.password_resets (username, used);

-- ─── Web push subscriptions (vendor app order notifications) ───
-- One row per device+browser; the vendor app registers these after the user
-- grants notification permission. endpoint is unique per subscription.
create table if not exists public.push_subscriptions (
  endpoint text primary key,
  shop_id text not null references public.shops(id) on delete cascade,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_push_subscriptions_shop_id on public.push_subscriptions (shop_id);

-- ─── Site feedback / bug reports (students → admin) ───
-- Students test the site and contribute bugs + improvement ideas; the admin
-- reviews who sent what and tracks status on the admin Feedback page.
create table if not exists public.site_feedback (
  id text primary key,
  user_id bigint,
  username text not null default '',
  name text not null default '',
  email text not null default '',
  category text not null default 'Bug',
  subject text not null default '',
  message text not null default '',
  page text not null default '',
  status text not null default 'Open',
  -- 'User' = real student via the portal; 'ATS' = automated test suite
  source text not null default 'User',
  created_at timestamptz not null default now()
);
create index if not exists idx_site_feedback_status on public.site_feedback (status);
create index if not exists idx_site_feedback_user on public.site_feedback (user_id);
create index if not exists idx_site_feedback_source on public.site_feedback (source);

-- ─── Profiles (optional frontend login sync — browser → Supabase REST) ───
-- Used by syncProfileToSupabase() in frontend/src/services/supabase.ts
create table if not exists public.profiles (
  id text primary key,
  email text not null default '',
  name text not null default '',
  role text not null default '',
  created_at timestamptz not null default now()
);

-- The browser uses the PUBLIC anon key for this sync, so allow INSERT only
-- (no RLS policies needed; the API layer is the real gatekeeper).
grant insert on table public.profiles to anon;

-- ─── Indexes for fast admin filtering ───
create index if not exists idx_shops_approval_status on public.shops (approval_status);
create index if not exists idx_orders_status on public.orders (status);
create index if not exists idx_orders_created_at on public.orders (created_at);
create index if not exists idx_orders_shop_id on public.orders (shop_id);
create index if not exists idx_products_shop_id on public.products (shop_id);
create index if not exists idx_payments_order_id on public.payments (order_id);
create index if not exists idx_payments_created_at on public.payments (created_at);

-- ─── Indexes for vendor portal speed (dashboard/history/product CRUD) ───
-- Every vendor request looks up their shop by shopkeeper_email; without this
-- index Postgres scans the whole shops table on each request. The lookup is
-- case-insensitive, so a functional index on LOWER(shopkeeper_email) serves it.
create index if not exists idx_shops_shopkeeper_email on public.shops (shopkeeper_email);
create index if not exists idx_shops_shopkeeper_email_lower on public.shops (lower(shopkeeper_email));
-- The vendor dashboard/history reads orders for a single shop ordered by
-- token; the composite index serves both the WHERE and the ORDER BY.
create index if not exists idx_orders_shop_id_token on public.orders (shop_id, token desc);

-- ─── Share payments (5% commission paid by shops to the admin) ───
-- The vendor dashboard and admin reports read these on every load.
create table if not exists public.share_payments (
  id text primary key,
  shop_id text not null,
  shop_name text not null default '',
  amount integer not null default 0,
  status text not null default 'Pending',
  created_at timestamptz not null default now(),
  paid_at timestamptz
);
-- share_payments are looked up by shop_id on every dashboard load.
create index if not exists idx_share_payments_shop_id on public.share_payments (shop_id);
create index if not exists idx_share_payments_status on public.share_payments (status);

-- ─── Migration for existing databases ───
-- (safe to run — no-op when the column already exists)
alter table public.orders add column if not exists payment_method text not null default 'UPI';
alter table public.shops add column if not exists is_removed boolean not null default false;
alter table public.shops add column if not exists admin_dues_balance integer not null default 0;
alter table public.shops add column if not exists admin_dues_last_paid_at timestamptz;
alter table public.shops add column if not exists upi_enabled boolean not null default true;
alter table public.shops add column if not exists cod_enabled boolean not null default true;
create index if not exists idx_users_role on public.users (role);
create index if not exists idx_registrations_created_at on public.user_registrations (created_at);
-- Migration: email uniqueness for existing databases (no-op when already applied).
create unique index if not exists idx_users_email_unique
  on public.users (lower(email)) where email <> '';

-- ─── Optional: default admin user (password: 8989, bcrypt hash) ───
-- The admin login also falls back to DEFAULT_SUPER_ADMIN_EMAIL/PASSWORD in .env,
-- so this insert is optional. Uncomment and adjust the email if you want a
-- real DB-backed admin account:
-- insert into public.users (username, password_hash, name, email, role)
-- values ('12', '<bcrypt-hash-of-8989>', 'Administrator', '12@gmail.com', 'admin')
-- on conflict (username) do nothing;

-- ══════════════════════════════════════════════════════════════════════
-- DETOMSITE v2 — Multi-shop ordering, batch stock, complaints, etc.
-- Run this block AFTER the original schema (safe to re-run — idempotent).
-- ══════════════════════════════════════════════════════════════════════

-- ─── New columns on existing tables ───
alter table public.shops add column if not exists whatsapp_number text not null default '';
alter table public.shops add column if not exists ordering_position integer not null default 0;
alter table public.shops add column if not exists is_featured boolean not null default false;
alter table public.shops add column if not exists shop_image text not null default '';

alter table public.orders add column if not exists parent_order_id text;
alter table public.orders add column if not exists batch_type text not null default 'Afternoon';
alter table public.orders add column if not exists is_combo boolean not null default false;

-- ─── Delivery batches ───
create table if not exists public.delivery_batches (
  id bigserial primary key,
  date_key text not null,
  batch_type text not null check (batch_type in ('Afternoon', 'Night')),
  accepted_until text not null,
  delivery_window text not null,
  status text not null default 'Active',
  created_at timestamptz not null default now(),
  unique (date_key, batch_type)
);

-- ─── Product stock (per delivery batch) ───
create table if not exists public.product_stock (
  id bigserial primary key,
  product_id text not null references public.products(id) on delete cascade,
  date_key text not null,
  batch_type text not null,
  total_stock integer not null default 0,
  sold integer not null default 0,
  created_at timestamptz not null default now(),
  unique (product_id, date_key, batch_type)
);
create index if not exists idx_product_stock_lookup on public.product_stock (product_id, date_key, batch_type);

-- ─── Parent orders (one per student checkout, wraps shop sub-orders) ───
create table if not exists public.parent_orders (
  id text primary key,
  token integer not null,
  date_key text not null default '',
  student_name text not null,
  student_phone text not null default '',
  student_email text not null default '',
  student_id text not null default '',
  total integer not null default 0,
  payment_method text not null default 'UPI',
  payment_status text not null default 'Pending',
  delivery_location text not null default '',
  status text not null default 'Pending',
  created_at timestamptz not null default now()
);
create index if not exists idx_parent_orders_created on public.parent_orders (created_at desc);
create index if not exists idx_parent_orders_status on public.parent_orders (status);
create index if not exists idx_parent_orders_date on public.parent_orders (date_key);

-- ─── Shop sub-orders (one per shop within a parent order) ───
create table if not exists public.shop_sub_orders (
  id text primary key,
  parent_order_id text not null references public.parent_orders(id) on delete cascade,
  shop_id text not null references public.shops(id) on delete cascade,
  shop_name text not null default '',
  shop_phone text not null default '',
  shop_whatsapp text not null default '',
  token integer not null,
  items_summary text not null default '',
  subtotal integer not null default 0,
  commission_5pct integer not null default 0,
  status text not null default 'Pending',
  batch_type text not null default 'Afternoon',
  rejection_reason text not null default '',
  accepted_at timestamptz,
  prepared_at timestamptz,
  ready_at timestamptz,
  completed_at timestamptz,
  delivered_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists idx_shop_sub_orders_parent on public.shop_sub_orders (parent_order_id);
create index if not exists idx_shop_sub_orders_shop on public.shop_sub_orders (shop_id, status);
create index if not exists idx_shop_sub_orders_status on public.shop_sub_orders (status);

-- ─── Order items (line items per sub-order) ───
create table if not exists public.order_items (
  id bigserial primary key,
  sub_order_id text not null references public.shop_sub_orders(id) on delete cascade,
  product_id text not null,
  product_name text not null default '',
  price integer not null default 0,
  quantity integer not null default 1,
  total integer not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists idx_order_items_sub on public.order_items (sub_order_id);

-- ─── Complaints (student-reported issues within 30 min) ───
create table if not exists public.complaints (
  id text primary key,
  parent_order_id text not null,
  sub_order_id text not null,
  student_name text not null default '',
  student_phone text not null default '',
  shop_id text not null default '',
  shop_name text not null default '',
  subject text not null default '',
  message text not null default '',
  proof_url text not null default '',
  status text not null default 'Open',
  admin_notes text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists idx_complaints_status on public.complaints (status);
create index if not exists idx_complaints_shop on public.complaints (shop_id);

-- ─── Refunds ───
create table if not exists public.refunds (
  id text primary key,
  parent_order_id text not null,
  sub_order_id text not null,
  student_name text not null default '',
  shop_name text not null default '',
  original_amount integer not null default 0,
  refund_amount integer not null default 0,
  refund_type text not null default 'Full',
  refund_utr text not null default '',
  status text not null default 'Pending',
  admin_notes text not null default '',
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists idx_refunds_status on public.refunds (status);

-- ─── Settlements (9 PM daily batch) ───
create table if not exists public.settlements (
  id text primary key,
  shop_id text not null references public.shops(id) on delete cascade,
  shop_name text not null default '',
  date_key text not null,
  gross_sales integer not null default 0,
  commission_5pct integer not null default 0,
  refunds_adjusted integer not null default 0,
  net_payable integer not null default 0,
  cod_collected integer not null default 0,
  status text not null default 'Pending',
  settlement_utr text not null default '',
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists idx_settlements_date on public.settlements (date_key);
create index if not exists idx_settlements_shop on public.settlements (shop_id);

-- ─── Menu change requests (shop edits require admin approval) ───
create table if not exists public.menu_change_requests (
  id text primary key,
  shop_id text not null,
  product_id text not null,
  change_type text not null default 'edit',
  field_name text not null default '',
  old_value text not null default '',
  new_value text not null default '',
  status text not null default 'Pending',
  admin_notes text not null default '',
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);
create index if not exists idx_menu_change_status on public.menu_change_requests (status);
create index if not exists idx_menu_change_shop on public.menu_change_requests (shop_id);

-- ─── Shop announcements (notification bar on student page) ───
create table if not exists public.shop_announcements (
  id text primary key,
  shop_id text not null references public.shops(id) on delete cascade,
  message text not null default '',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists idx_shop_announcements_shop on public.shop_announcements (shop_id);

-- ─── Favorites ───
create table if not exists public.favorites (
  id bigserial primary key,
  student_phone text not null,
  product_id text not null references public.products(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (student_phone, product_id)
);

-- ─── WhatsApp logs ───
create table if not exists public.whatsapp_logs (
  id bigserial primary key,
  phone text not null default '',
  message_type text not null default '',
  message text not null default '',
  status text not null default 'sent',
  order_id text,
  created_at timestamptz not null default now()
);

-- ─── Audit logs ───
create table if not exists public.audit_logs (
  id bigserial primary key,
  actor text not null default '',
  actor_role text not null default '',
  action text not null default '',
  target_type text not null default '',
  target_id text not null default '',
  details text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_logs_actor on public.audit_logs (actor);
create index if not exists idx_audit_logs_created on public.audit_logs (created_at desc);

-- ─── UTR uniqueness constraint (one payment per UTR) ───
-- Only enforce when utr_number is non-empty
create unique index if not exists idx_payments_utr_unique
  on public.payments (utr_number) where utr_number IS NOT NULL AND utr_number <> '';

-- ─── Default delivery batches for today ───
-- These insert no-ops on conflict so they're safe to run repeatedly.
insert into public.delivery_batches (date_key, batch_type, accepted_until, delivery_window)
select to_char(now() at time zone 'Asia/Kolkata', 'YYYY-MM-DD'), 'Afternoon', '12:30 PM', '1:00 PM - 1:30 PM'
where not exists (
  select 1 from public.delivery_batches where date_key = to_char(now() at time zone 'Asia/Kolkata', 'YYYY-MM-DD') and batch_type = 'Afternoon'
);
insert into public.delivery_batches (date_key, batch_type, accepted_until, delivery_window)
select to_char(now() at time zone 'Asia/Kolkata', 'YYYY-MM-DD'), 'Night', '6:00 PM', '7:30 PM - 8:00 PM'
where not exists (
  select 1 from public.delivery_batches where date_key = to_char(now() at time zone 'Asia/Kolkata', 'YYYY-MM-DD') and batch_type = 'Night'
);
