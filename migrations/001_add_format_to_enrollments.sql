-- =====================================================
-- MIGRACIÓN: Agregar campo 'format' a tabla enrollments
-- Fecha: 2025-10-21
-- Descripción: Agrega el campo 'format' para definir si
--              las clases de una inscripción son individuales
--              o grupales.
-- =====================================================

-- 1. Agregar columna 'format' a la tabla enrollments
ALTER TABLE enrollments
ADD COLUMN format VARCHAR(20) NOT NULL DEFAULT 'individual';

-- 2. Agregar comentario a la columna
COMMENT ON COLUMN enrollments.format IS 'Formato de las clases: individual o group';

-- 3. Agregar constraint para validar valores permitidos
ALTER TABLE enrollments
ADD CONSTRAINT check_enrollment_format
CHECK (format IN ('individual', 'group'));

-- 4. Crear índice para mejorar performance (opcional)
-- CREATE INDEX idx_enrollments_format ON enrollments(format);

-- =====================================================
-- VALIDACIÓN
-- =====================================================
-- Para verificar que la migración funcionó:
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'enrollments' AND column_name = 'format';

-- =====================================================
-- ROLLBACK (si necesitas revertir)
-- =====================================================
-- ALTER TABLE enrollments DROP CONSTRAINT IF EXISTS check_enrollment_format;
-- ALTER TABLE enrollments DROP COLUMN IF EXISTS format;
