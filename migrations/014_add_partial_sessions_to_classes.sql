-- Migration: 014_add_partial_sessions_to_classes.sql
-- Description: Add partial_sessions JSONB field to classes table for storing completed recovery sessions on recovery classes

ALTER TABLE classes
ADD COLUMN partial_sessions JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN classes.partial_sessions IS 'Array of completed partial recovery sessions attached to recovery classes: [{date: "YYYY-MM-DD", time: "HH:MM", minutes: 15|30}]';
