-- Trusted ownership is assigned only by the authenticated backend.
-- Do not backfill from names, phone numbers or legacy client student_id.
alter table public.orders add column if not exists owner_user_id text not null default '';
alter table public.parent_orders add column if not exists owner_user_id text not null default '';
