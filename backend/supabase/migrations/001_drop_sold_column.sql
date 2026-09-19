-- Migration: Drop the sold column from product_stock table
-- This removes the separate sold tracking, now using total_stock directly

-- Drop the sold column if it exists
ALTER TABLE public.product_stock DROP COLUMN IF EXISTS sold;

-- Add a comment explaining the change
COMMENT ON COLUMN public.product_stock.total_stock IS 'Current available stock for the batch (previously tracked as total_stock - sold)';
