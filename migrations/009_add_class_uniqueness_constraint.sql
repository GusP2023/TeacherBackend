-- Migration: Add unique constraint to prevent duplicate classes
-- Prevents multiple classes with same enrollment_id + date + time + type (excluding cancelled)

-- First, clean any existing duplicates (run cleanup_duplicates.sql first)

-- Add unique index (allows multiple cancelled for same slot)
CREATE UNIQUE INDEX IF NOT EXISTS idx_classes_unique_active
ON classes (enrollment_id, date, time, type)
WHERE status != 'cancelled';

-- Alternative: Add unique constraint (stricter, no exceptions)
-- ALTER TABLE classes
-- ADD CONSTRAINT classes_unique_active
-- UNIQUE (enrollment_id, date, time, type)
-- DEFERRABLE INITIALLY DEFERRED;