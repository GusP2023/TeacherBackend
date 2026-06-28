-- 015_add_time_to_notes.sql
-- Cambia la columna due_date de DATE a TIMESTAMPTZ

ALTER TABLE enrollment_notes 
ALTER COLUMN due_date TYPE TIMESTAMPTZ 
USING due_date::TIMESTAMPTZ;
