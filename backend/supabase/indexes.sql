-- ============================================================
-- DETOMSITE — Production migration: run this in
-- Supabase Dashboard → SQL Editor → New query → Run
--
-- What this fixes:
--   1. "Failed to add product" in the vendor app (missing columns
--      on the products table crash the INSERT with a 500).
--   2. Slow vendor dashboard / order history (missing indexes make
--      Postgres scan entire tables on every request).
-- All statements are idempotent — safe to run more than once.
-- ============================================================

-- ─── 1. Missing products columns (fixes "Failed to add product") ───
alter table public.products add column if not exists pending_price integer;
alter table public.products add column if not exists prep_time integer not null default 10;
alter table public.products add column if not exists available boolean not null default true;

-- ─── 2. Vendor portal indexes (fixes slow dashboard / history) ───
-- Vendors look up their shop by email on every request.
create index if not exists idx_shops_shopkeeper_email on public.shops (shopkeeper_email);

-- Vendor dashboard/history: orders for one shop, newest token first.
create index if not exists idx_orders_shop_id_token on public.orders (shop_id, token desc);
create index if not exists idx_orders_shop_id on public.orders (shop_id);
create index if not exists idx_orders_status on public.orders (status);
create index if not exists idx_orders_created_at on public.orders (created_at);

-- Products menu per shop.
create index if not exists idx_products_shop_id on public.products (shop_id);

-- Share payments (vendor → admin 5%) are read by shop on dashboard load.
create index if not exists idx_share_payments_shop_id on public.share_payments (shop_id);
create index if not exists idx_share_payments_status on public.share_payments (status);

-- Web push subscriptions for the vendor app are looked up by shop on every
-- order placement (the push delivery query).
create table if not exists public.push_subscriptions (
  endpoint text primary key,
  shop_id text not null references public.shops(id) on delete cascade,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_push_subscriptions_shop_id on public.push_subscriptions (shop_id);

-- ─── 3. Verify (should return one row per index) ───
select indexname from pg_indexes
where schemaname = 'public'
  and indexname in (
    'idx_shops_shopkeeper_email',
    'idx_orders_shop_id_token',
    'idx_orders_shop_id',
    'idx_orders_status',
    'idx_orders_created_at',
    'idx_products_shop_id',
    'idx_share_payments_shop_id',
    'idx_share_payments_status',
    'idx_push_subscriptions_shop_id'
  )
order by indexname;
