-- Script para limpiar clases duplicadas en Neon
-- Ejecutar en Neon Console: https://console.neon.tech

-- Paso 1: Ver duplicados (sin eliminar)
SELECT enrollment_id, date, time, type, COUNT(*) as count,
       array_agg(id ORDER BY id) as ids
FROM classes
WHERE status != 'cancelled'
GROUP BY enrollment_id, date, time, type
HAVING COUNT(*) > 1
ORDER BY count DESC;

-- Paso 2: Para cada grupo de duplicados, mantener solo el ID más bajo y eliminar los demás
-- (ajusta los IDs según lo que veas en el resultado del Paso 1)

-- Ejemplo: Si hay duplicados con IDs [123, 456, 789], mantener 123 y eliminar 456,789:
-- DELETE FROM classes WHERE id IN (456, 789);

-- Para automatizar, puedes usar esta query que mantiene el ID mínimo por grupo:
DELETE FROM classes
WHERE id NOT IN (
    SELECT DISTINCT ON (enrollment_id, date, time, type) id
    FROM classes
    WHERE status != 'cancelled'
    ORDER BY enrollment_id, date, time, type, id ASC
);