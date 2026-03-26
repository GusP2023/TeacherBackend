-- Migración: Soporte para eventos "extra" sin enrollment_id
-- Fecha: 2025-12-14
-- Descripción: 
--   1. Hacer enrollment_id nullable en la tabla classes
--   2. Agregar campo notes para título de eventos extra
--   3. Cambiar ondelete de CASCADE a SET NULL para enrollment_id

-- PASO 1: Agregar campo notes (si no existe)
ALTER TABLE classes 
ADD COLUMN IF NOT EXISTS notes TEXT;

-- PASO 2: Hacer enrollment_id nullable
-- Primero eliminar la restricción FK existente
ALTER TABLE classes 
DROP CONSTRAINT IF EXISTS classes_enrollment_id_fkey;

-- Modificar la columna para permitir NULL
ALTER TABLE classes 
ALTER COLUMN enrollment_id DROP NOT NULL;

-- Recrear la FK con SET NULL en lugar de CASCADE
ALTER TABLE classes 
ADD CONSTRAINT classes_enrollment_id_fkey 
FOREIGN KEY (enrollment_id) 
REFERENCES enrollments(id) 
ON DELETE SET NULL;

-- Comentario para documentar el cambio
COMMENT ON COLUMN classes.enrollment_id IS 'ID de la inscripción (NULL para eventos tipo extra)';
COMMENT ON COLUMN classes.notes IS 'Notas adicionales (usado para título en eventos extra)';
