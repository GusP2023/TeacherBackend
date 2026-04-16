-- Migration: 008_add_partial_sessions_to_enrollments.sql
-- Description: Add partial_sessions JSONB field to enrollments table for storing partial recovery sessions

ALTER TABLE enrollments
ADD COLUMN partial_sessions JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN enrollments.partial_sessions IS 'Array of partial recovery sessions: [{date: "YYYY-MM-DD", time: "HH:MM", minutes: 15|30}]';