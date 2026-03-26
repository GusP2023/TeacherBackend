-- Agregar campo manual_credit_dates para tracking de créditos manuales
-- Fecha: 2026-02-12

-- Agregar columna de tipo array de fechas
ALTER TABLE enrollments 
ADD COLUMN manual_credit_dates TEXT[] DEFAULT ARRAY[]::TEXT[];

-- Comentario para documentación
COMMENT ON COLUMN enrollments.manual_credit_dates IS 'Array de fechas de créditos agregados manualmente (formato ISO: YYYY-MM-DD). Cada elemento representa 1 crédito con su fecha de origen.';
