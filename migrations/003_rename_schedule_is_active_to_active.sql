-- Migration: Rename schedule.is_active to schedule.active
-- Date: 2025-02-09
-- Reason: Cambio de nomenclatura para consistencia

-- Renombrar columna is_active a active en tabla schedules
ALTER TABLE schedules 
RENAME COLUMN is_active TO active;

-- Verificación
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'schedules' 
  AND column_name = 'active';
